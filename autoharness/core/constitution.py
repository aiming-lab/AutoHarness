"""Constitution Engine — loads, validates, merges, and provides access to governance configuration.

The Constitution is the central configuration object for AutoHarness. It defines:
- Identity metadata
- Governance rules (what behaviors to enforce)
- Tool permissions (what tools can do)
- Risk assessment configuration
- Hook profiles (lifecycle callbacks)
- Audit settings

A constitution can be loaded from YAML files, dicts, or YAML strings.
Multiple constitutions can be merged (project + user + defaults) with
later values taking priority.
"""

from __future__ import annotations

import logging
import os
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from autoharness.core.types import (
    ConstitutionConfig,
    Enforcement,
    HookProfile,
    PermissionDefaults,
    Rule,
    RuleSeverity,
    ToolPermission,
)

logger = logging.getLogger(__name__)


class ConstitutionError(Exception):
    """Raised when a constitution cannot be loaded or is fundamentally invalid."""


class Constitution:
    """The governance constitution for an AutoHarness session.

    Provides typed, validated access to all configuration sections and
    supports merging multiple constitutions with override semantics.
    """

    def __init__(self, config: ConstitutionConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Factory classmethods
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> Constitution:
        """Load a constitution from a YAML file on disk.

        Args:
            path: Filesystem path to a YAML constitution file.

        Returns:
            A validated Constitution instance.

        Raises:
            ConstitutionError: If the file cannot be read or parsed.
            FileNotFoundError: If the path does not exist.
        """
        filepath = Path(path)
        if not filepath.exists():
            raise FileNotFoundError(f"Constitution file not found: {filepath}")
        if not filepath.is_file():
            raise ConstitutionError(f"Constitution path is not a file: {filepath}")

        try:
            raw = filepath.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConstitutionError(f"Cannot read constitution file {filepath}: {exc}") from exc

        return cls.from_yaml(raw)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> Constitution:
        """Load a constitution from a YAML string.

        Args:
            yaml_str: Raw YAML content.

        Returns:
            A validated Constitution instance.

        Raises:
            ConstitutionError: If the YAML is malformed or validation fails.
        """
        try:
            data = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise ConstitutionError(f"Invalid YAML in constitution: {exc}") from exc

        if data is None:
            data = {}

        if not isinstance(data, dict):
            raise ConstitutionError(
                f"Constitution YAML must be a mapping, got {type(data).__name__}"
            )

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Constitution:
        """Load a constitution from a dictionary.

        Unknown top-level keys emit warnings but do not cause errors,
        allowing forward-compatible constitution files.

        Args:
            data: Dictionary of constitution configuration.

        Returns:
            A validated Constitution instance.

        Raises:
            ConstitutionError: If required fields fail Pydantic validation.
        """
        known_keys = set(ConstitutionConfig.model_fields.keys())
        unknown_keys = set(data.keys()) - known_keys
        for key in sorted(unknown_keys):
            warnings.warn(
                f"Unknown constitution field '{key}' will be ignored",
                UserWarning,
                stacklevel=2,
            )

        try:
            config = ConstitutionConfig.model_validate(data)
        except ValidationError as exc:
            raise ConstitutionError(
                f"Constitution validation failed:\n{exc}"
            ) from exc

        return cls(config)

    @classmethod
    def default(cls) -> Constitution:
        """Create a sensible zero-config default constitution.

        Includes essential safety rules, restricted bash patterns,
        path safety for sensitive files, secret detection, standard
        hook profile, and audit enabled by default.

        Returns:
            A Constitution with production-safe defaults.
        """
        default_rules = [
            Rule(
                id="no-over-engineering",
                description="Prefer simple, minimal solutions over complex abstractions",
                severity=RuleSeverity.warning,
                enforcement=Enforcement.prompt,
            ),
            Rule(
                id="confirm-destructive-ops",
                description=(
                    "Destructive operations (delete, drop, reset --hard, push --force) "
                    "must be confirmed before execution"
                ),
                severity=RuleSeverity.error,
                enforcement=Enforcement.hook,
            ),
            Rule(
                id="no-config-weakening",
                description=(
                    "Do not disable safety features, skip hooks, or weaken security "
                    "settings (e.g., --no-verify, --insecure, disable_ssl)"
                ),
                severity=RuleSeverity.error,
                enforcement=Enforcement.hook,
            ),
            Rule(
                id="no-secret-exposure",
                description="Never commit, log, or transmit secrets, API keys, or credentials",
                severity=RuleSeverity.error,
                enforcement=Enforcement.hook,
            ),
            Rule(
                id="sensitive-path-guard",
                description="Warn before reading or modifying sensitive paths",
                severity=RuleSeverity.warning,
                enforcement=Enforcement.prompt,
            ),
        ]

        permissions = {
            "defaults": PermissionDefaults().model_dump(),
            "tools": {
                "bash": ToolPermission(
                    policy="restricted",
                    deny_patterns=[
                        r"rm\s+-rf\s+/",
                        r"rm\s+-rf\s+~",
                        r"rm\s+-rf\s+\$HOME",
                        r"mkfs\.",
                        r"dd\s+if=.*of=/dev/",
                        r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",  # fork bomb
                        r"chmod\s+-R\s+777\s+/",
                        r"curl\s+.*\|\s*(ba)?sh",
                        r"wget\s+.*\|\s*(ba)?sh",
                        r"git\s+push\s+.*--force\s+.*main",
                        r"git\s+push\s+.*--force\s+.*master",
                        r"git\s+reset\s+--hard",
                    ],
                ).model_dump(),
                "file_write": ToolPermission(
                    policy="restricted",
                    deny_patterns=[
                        r"\.env$",
                        r"\.env\.",
                        r"\.ssh/",
                        r"credentials\.json",
                        r"\.aws/credentials",
                        r"\.netrc",
                        r"id_rsa",
                        r"\.pem$",
                    ],
                ).model_dump(),
            },
        }

        risk = {
            "classifier": "rules",
            "thresholds": {
                "low": "allow",
                "medium": "ask",
                "high": "deny",
                "critical": "deny",
            },
            "custom_rules": [],
        }

        hooks = {
            "profile": HookProfile.standard.value,
            "pre": [],
            "post": [],
        }

        audit_cfg = {
            "enabled": True,
            "format": "jsonl",
            "output": "./audit.jsonl",
            "retention_days": 90,
            "include": [
                "tool_call",
                "tool_blocked",
                "tool_error",
                "hook_fired",
                "permission_check",
            ],
        }

        identity = {
            "name": "autoharness-default",
            "description": "Default AutoHarness constitution with essential safety rules",
            "boundaries": [],
        }

        config = ConstitutionConfig(
            identity=identity,
            rules=default_rules,
            permissions=permissions,
            risk=risk,
            hooks=hooks,
            audit=audit_cfg,
        )

        return cls(config)

    # ------------------------------------------------------------------
    # Cascading discovery
    # ------------------------------------------------------------------

    @classmethod
    def discover(cls, project_dir: str | Path | None = None) -> Constitution:
        """Discover and merge constitutions from a 3-level cascading config system.

        Priority (lowest to highest):
        1. User-level defaults: ``~/.autoharness/config.yaml``
           (or ``$AUTOHARNESS_CONFIG_HOME/config.yaml``)
        2. Project-level: searched in *project_dir* (or cwd) with this order:
           ``.autoharness.yaml``, ``constitution.yaml``,
           ``.autoharness/constitution.yaml``, ``autoharness.yaml``
        3. Local overrides: ``{project_dir}/.autoharness.local.yaml``
           (intended to be gitignored)

        All found files are deep-merged in priority order using
        :meth:`Constitution.merge`. If no files are found at all, falls back
        to :meth:`Constitution.default`.

        Args:
            project_dir: Project root directory to search. Defaults to cwd.

        Returns:
            A merged Constitution instance.
        """
        search_dir = Path(project_dir) if project_dir else Path.cwd()
        layers: list[Constitution] = []

        # Level 1: User-level defaults
        config_home = os.environ.get("AUTOHARNESS_CONFIG_HOME")
        if config_home:
            user_config = Path(config_home) / "config.yaml"
        else:
            user_config = Path.home() / ".autoharness" / "config.yaml"

        if user_config.is_file():
            logger.info("Loading user-level config: %s", user_config)
            try:
                layers.append(cls.load(user_config))
            except (ConstitutionError, FileNotFoundError) as exc:
                logger.warning("Failed to load user config %s: %s", user_config, exc)

        # Level 2: Project-level config (first match wins)
        project_candidates = (
            ".autoharness.yaml",
            "constitution.yaml",
            ".autoharness/constitution.yaml",
            "autoharness.yaml",
        )
        for candidate in project_candidates:
            candidate_path = search_dir / candidate
            if candidate_path.is_file():
                logger.info("Loading project-level config: %s", candidate_path)
                try:
                    layers.append(cls.load(candidate_path))
                except (ConstitutionError, FileNotFoundError) as exc:
                    logger.warning(
                        "Failed to load project config %s: %s", candidate_path, exc
                    )
                break  # first match only

        # Level 3: Local overrides (gitignored)
        local_override = search_dir / ".autoharness.local.yaml"
        if local_override.is_file():
            logger.info("Loading local override config: %s", local_override)
            try:
                layers.append(cls.load(local_override))
            except (ConstitutionError, FileNotFoundError) as exc:
                logger.warning(
                    "Failed to load local override %s: %s", local_override, exc
                )

        if not layers:
            logger.info("No constitution files discovered; using defaults")
            return cls.default()

        # Merge all layers: start with first, merge each subsequent layer on top
        result = layers[0]
        for layer in layers[1:]:
            result = cls.merge(result, layer)

        return result

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------

    @staticmethod
    def merge(base: Constitution, override: Constitution) -> Constitution:
        """Deep-merge two constitutions, with *override* taking priority.

        Merge semantics:
        - Scalar fields: override wins if set.
        - Rules: merged by ``id`` — override replaces matching rules,
          new rules are appended.
        - Tool permissions: merged by ``tool`` name, same logic.
        - Lists without identity keys (e.g., sensitive_paths): concatenated
          and deduplicated.
        - Nested models: recursively merged.

        Args:
            base: The lower-priority constitution (e.g., defaults).
            override: The higher-priority constitution (e.g., project).

        Returns:
            A new merged Constitution.
        """
        base_dict = base._config.model_dump()
        over_dict = override._config.model_dump()

        merged = _deep_merge_dicts(base_dict, over_dict)

        # Special handling: merge rules by id
        merged["rules"] = _merge_by_key(
            base_dict.get("rules", []),
            over_dict.get("rules", []),
            key="id",
        )

        # Special handling: merge tool permissions by tool name (dict-style)
        base_tools = base_dict.get("permissions", {}).get("tools", {})
        over_tools = over_dict.get("permissions", {}).get("tools", {})
        if "permissions" not in merged:
            merged["permissions"] = {}
        if isinstance(base_tools, dict) and isinstance(over_tools, dict):
            merged_tools = dict(base_tools)
            merged_tools.update(over_tools)
            merged["permissions"]["tools"] = merged_tools
        elif isinstance(base_tools, list) and isinstance(over_tools, list):
            merged["permissions"]["tools"] = _merge_by_key(base_tools, over_tools, key="tool")

        # Deduplicate list fields in risk config
        for list_field in ("sensitive_paths", "secret_patterns", "custom_rules"):
            if "risk" in merged and list_field in merged["risk"]:
                merged["risk"][list_field] = _deduplicate_ordered(merged["risk"][list_field])

        # Deduplicate hook lists
        if "hooks" in merged:
            for hook_field in ("pre", "post", "pre_action", "post_action", "on_error", "on_block"):
                if hook_field in merged["hooks"]:
                    merged["hooks"][hook_field] = _deduplicate_ordered(
                        merged["hooks"][hook_field]
                    )

        config = ConstitutionConfig.model_validate(merged)
        return Constitution(config)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> ConstitutionConfig:
        """The full validated configuration model."""
        return self._config

    @property
    def rules(self) -> list[Rule]:
        """All governance rules."""
        return self._config.rules

    @staticmethod
    def _as_dict(val: Any) -> dict[str, Any]:
        """Convert a Pydantic model or dict to a plain dict."""
        if hasattr(val, "model_dump"):
            result: dict[str, Any] = val.model_dump()
            return result
        if isinstance(val, dict):
            return val
        return {}

    @property
    def permissions(self) -> dict[str, Any]:
        """Tool permission configuration (dict with 'defaults' and 'tools')."""
        return self._as_dict(self._config.permissions)

    @property
    def risk_config(self) -> dict[str, Any]:
        """Risk assessment configuration (dict with 'classifier', 'thresholds', etc.)."""
        return self._as_dict(self._config.risk)

    @property
    def hook_config(self) -> dict[str, Any]:
        """Lifecycle hook configuration (dict with 'profile', 'pre', 'post')."""
        return self._as_dict(self._config.hooks)

    @property
    def audit_config(self) -> dict[str, Any]:
        """Audit logging configuration (dict with 'enabled', 'format', etc.)."""
        return self._as_dict(self._config.audit)

    @property
    def identity(self) -> dict[str, Any]:
        """Constitution identity metadata (dict with 'name', 'description', 'boundaries')."""
        return self._as_dict(self._config.identity)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_rules_for_enforcement(self, enforcement: str) -> list[Rule]:
        """Return all rules matching the given enforcement type.

        Args:
            enforcement: One of "prompt", "hook", "both"
                (or legacy "block", "warn", "audit", "review").

        Returns:
            List of matching rules, or empty list if none match.
        """
        try:
            target = Enforcement(enforcement)
        except ValueError:
            logger.warning("Unknown enforcement type '%s', returning empty list", enforcement)
            return []

        return [r for r in self._config.rules if r.enforcement == target]

    def get_tool_permission(self, tool_name: str) -> ToolPermission | None:
        """Get the permission config for a specific tool.

        Delegates to ConstitutionConfig.get_tool_permission which looks up
        the tool by name in the permissions.tools dict.

        Args:
            tool_name: The tool identifier (e.g., "bash", "file_write").

        Returns:
            The matching ToolPermission, or None if no tool-specific config exists.
        """
        return self._config.get_tool_permission(tool_name)

    def validate(self) -> list[str]:
        """Run validation checks and return a list of warnings.

        This does *not* raise on issues — structural errors are caught at
        load time by Pydantic. This method checks for softer issues like
        duplicate rule IDs, rules with no description, etc.

        Returns:
            A list of human-readable warning strings (empty if clean).
        """
        issues: list[str] = []

        # Check for duplicate rule IDs
        seen_ids: dict[str, int] = {}
        for rule in self._config.rules:
            seen_ids[rule.id] = seen_ids.get(rule.id, 0) + 1
        for rule_id, count in seen_ids.items():
            if count > 1:
                issues.append(f"Duplicate rule ID '{rule_id}' appears {count} times")

        # Check for rules without descriptions
        for rule in self._config.rules:
            if not rule.description:
                issues.append(f"Rule '{rule.id}' has no description")

        # Check for duplicate tool permissions
        tools_config = self.permissions.get("tools", {})
        if isinstance(tools_config, dict):
            # New-style dict: keys are tool names, no duplicates possible
            pass
        elif isinstance(tools_config, list):
            seen_tools: dict[str, int] = {}
            for tp in tools_config:
                tool = tp.get("tool", "") if isinstance(tp, dict) else getattr(tp, "tool", "")
                seen_tools[tool] = seen_tools.get(tool, 0) + 1
            for tool, count in seen_tools.items():
                if count > 1:
                    issues.append(f"Duplicate tool permission for '{tool}' appears {count} times")

        # Check identity
        id_dict = self.identity
        if not id_dict.get("name", ""):
            issues.append("Constitution has no identity name")

        return issues

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        name = self.identity.get("name", "unnamed")
        tools = self.permissions.get("tools", {})
        tools_count = len(tools) if isinstance(tools, (dict, list)) else 0
        return (
            f"Constitution(name={name!r}, "
            f"rules={len(self._config.rules)}, "
            f"tools={tools_count})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Constitution):
            return NotImplemented
        return self._config == other._config


# ======================================================================
# Private merge helpers
# ======================================================================


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two dicts; override values take priority.

    Lists are replaced (not concatenated) at this level — special list
    merging (by-key, dedup) is handled by the caller.
    """
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _merge_by_key(
    base_items: list[dict[str, Any]],
    override_items: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    """Merge two lists of dicts by a unique key field.

    Items in *override* replace matching items in *base*. New items from
    *override* are appended.
    """
    merged: dict[str, dict[str, Any]] = {}
    for item in base_items:
        k = item.get(key, "")
        merged[k] = deepcopy(item)
    for item in override_items:
        k = item.get(key, "")
        if k in merged:
            merged[k] = _deep_merge_dicts(merged[k], item)
        else:
            merged[k] = deepcopy(item)
    return list(merged.values())


def _deduplicate_ordered(items: list[Any]) -> list[Any]:
    """Deduplicate a list while preserving insertion order."""
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        # Only hashable items can be deduped; keep unhashable as-is
        try:
            if item not in seen:
                seen.add(item)
                result.append(item)
        except TypeError:
            result.append(item)
    return result
