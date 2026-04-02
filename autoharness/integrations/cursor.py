"""Cursor Integration — install AutoHarness rules into Cursor's rule system.

Cursor supports project-level rules via a ``.cursor/rules/`` directory
containing Markdown files. Starting from Cursor 0.50, it also supports
a hooks system via ``.cursor/hooks/``. This module manages installation,
uninstallation, and status checking of AutoHarness governance within Cursor.

Usage::

    from autoharness.integrations.cursor import CursorInstaller

    installer = CursorInstaller()
    installer.install(constitution_path="./constitution.yaml")
    installer.status()  # -> {"installed": True, ...}
    installer.uninstall()

Or via CLI::

    autoharness install cursor --constitution constitution.yaml
    autoharness uninstall cursor
    autoharness status cursor
"""

from __future__ import annotations

import logging
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CURSOR_DIR_DEFAULT = Path(".cursor")  # Project-local by convention

_RULES_DIR = "rules"
_HOOKS_DIR = "hooks"
_AUTOHARNESS_RULE_FILE = "autoharness.md"
_AUTOHARNESS_HOOK_SCRIPT = "autoharness-check.sh"
_AUTOHARNESS_CONFIG_DIR = "autoharness"
_CONSTITUTION_FILENAME = "constitution.yaml"
_AUDIT_DIR = "audit"

# Cursor hook support was introduced in version 0.50
_CURSOR_HOOKS_MIN_VERSION = "0.50"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CursorError(Exception):
    """Raised when Cursor integration encounters a problem."""


class CursorNotFoundError(CursorError):
    """Raised when the Cursor project directory cannot be located."""


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class CursorInstaller:
    """Install and manage AutoHarness rules in Cursor.

    Cursor uses a ``.cursor/rules/`` directory for behavior rules expressed
    as Markdown files. Each file becomes an instruction that Cursor's AI
    follows when generating or editing code.

    Parameters
    ----------
    project_dir : Path | None
        The project root directory. Defaults to the current working directory.
        The ``.cursor/`` directory will be created/managed inside this path.
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._cursor_dir = self._project_dir / _CURSOR_DIR_DEFAULT
        self._rules_dir = self._cursor_dir / _RULES_DIR
        self._hooks_dir = self._cursor_dir / _HOOKS_DIR
        self._autoharness_dir = self._cursor_dir / _AUTOHARNESS_CONFIG_DIR
        self._rule_file = self._rules_dir / _AUTOHARNESS_RULE_FILE
        self._hook_script = self._hooks_dir / _AUTOHARNESS_HOOK_SCRIPT
        self._constitution_dest = self._autoharness_dir / _CONSTITUTION_FILENAME
        self._audit_dir = self._autoharness_dir / _AUDIT_DIR

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(
        self,
        constitution_path: str | Path | None = None,
        enable_hooks: bool = True,
    ) -> dict[str, Any]:
        """Install AutoHarness rules into Cursor's rule system.

        Steps:
          1. Find or create ``.cursor/rules/`` directory
          2. Load and parse the constitution YAML
          3. Generate ``autoharness.md`` rule file from constitution
          4. Create ``.cursor/hooks/`` if ``enable_hooks`` is True
          5. Copy constitution to ``.cursor/autoharness/constitution.yaml``
          6. Create audit directory ``.cursor/autoharness/audit/``
          7. Configure audit logging

        Parameters
        ----------
        constitution_path : str | Path | None
            Path to a constitution YAML file. If None, uses the bundled
            default template.
        enable_hooks : bool
            Whether to install hook scripts (requires Cursor 0.50+).
            Defaults to True.

        Returns
        -------
        dict
            Summary of what was installed.

        Raises
        ------
        CursorError
            For permission or I/O errors.
        """
        self._verify_autoharness_cli()

        # Step 1: Ensure directories exist
        try:
            self._cursor_dir.mkdir(parents=True, exist_ok=True)
            self._rules_dir.mkdir(parents=True, exist_ok=True)
            self._autoharness_dir.mkdir(parents=True, exist_ok=True)
            self._audit_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise CursorError(
                f"Permission denied creating directories under {self._cursor_dir}. "
                f"Check filesystem permissions: {exc}"
            ) from exc
        except OSError as exc:
            raise CursorError(
                f"Failed to create directories under {self._cursor_dir}: {exc}"
            ) from exc

        # Step 2: Load constitution
        constitution = self._load_constitution(constitution_path)

        # Step 3: Generate the Cursor rule file
        rule_content = self._generate_rule_markdown(constitution)
        self._write_file_atomic(self._rule_file, rule_content)
        logger.info("Generated Cursor rule file: %s", self._rule_file)

        # Step 4: Install hooks if requested
        hooks_installed = False
        if enable_hooks:
            hooks_installed = self._install_hooks()

        # Step 5: Copy constitution
        constitution_copied = False
        if constitution_path is not None:
            constitution_copied = self._copy_constitution(Path(constitution_path))

        result = {
            "installed": True,
            "project_dir": str(self._project_dir),
            "cursor_dir": str(self._cursor_dir),
            "rule_file": str(self._rule_file),
            "hooks_installed": hooks_installed,
            "hook_script": str(self._hook_script) if hooks_installed else None,
            "autoharness_dir": str(self._autoharness_dir),
            "audit_dir": str(self._audit_dir),
            "constitution_copied": constitution_copied,
            "constitution_path": (
                str(self._constitution_dest) if constitution_copied else None
            ),
        }

        logger.info(
            "AutoHarness installed in Cursor: rule_file=%s, hooks=%s",
            self._rule_file,
            hooks_installed,
        )

        return result

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self) -> dict[str, Any]:
        """Remove AutoHarness rules and hooks from Cursor.

        Removes only AutoHarness-managed files; preserves other Cursor rules
        and hooks.

        Returns
        -------
        dict
            Summary of what was removed.
        """
        removed_files: list[str] = []

        # Remove rule file
        if self._rule_file.exists():
            try:
                self._rule_file.unlink()
                removed_files.append(str(self._rule_file))
                logger.info("Removed rule file: %s", self._rule_file)
            except OSError as exc:
                logger.warning("Could not remove rule file %s: %s", self._rule_file, exc)

        # Remove hook script
        if self._hook_script.exists():
            try:
                self._hook_script.unlink()
                removed_files.append(str(self._hook_script))
                logger.info("Removed hook script: %s", self._hook_script)
            except OSError as exc:
                logger.warning(
                    "Could not remove hook script %s: %s", self._hook_script, exc
                )

        # Remove autoharness config directory
        config_removed = False
        if self._autoharness_dir.exists():
            try:
                shutil.rmtree(self._autoharness_dir)
                config_removed = True
                logger.info("Removed AutoHarness config directory: %s", self._autoharness_dir)
            except OSError as exc:
                logger.warning(
                    "Could not remove AutoHarness config directory %s: %s",
                    self._autoharness_dir,
                    exc,
                )

        # Clean up empty directories (but don't remove if they have other files)
        for dir_path in (self._hooks_dir, self._rules_dir):
            if dir_path.exists() and not any(dir_path.iterdir()):
                try:
                    dir_path.rmdir()
                    logger.info("Removed empty directory: %s", dir_path)
                except OSError:
                    pass  # Not critical

        return {
            "uninstalled": True,
            "removed_files": removed_files,
            "config_removed": config_removed,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Check if AutoHarness is installed in Cursor.

        Returns
        -------
        dict
            Installation status including:
            - installed: bool
            - rule_file_present: bool
            - hooks_installed: bool
            - constitution_present: bool
            - audit_dir_present: bool
        """
        rule_file_present = self._rule_file.exists()
        hooks_installed = self._hook_script.exists()
        constitution_present = self._constitution_dest.exists()
        audit_dir_present = self._audit_dir.exists()

        installed = rule_file_present

        return {
            "installed": installed,
            "project_dir": str(self._project_dir),
            "cursor_dir": str(self._cursor_dir),
            "cursor_dir_exists": self._cursor_dir.exists(),
            "rule_file_present": rule_file_present,
            "rule_file_path": str(self._rule_file),
            "hooks_installed": hooks_installed,
            "hook_script_path": str(self._hook_script) if hooks_installed else None,
            "constitution_present": constitution_present,
            "constitution_path": (
                str(self._constitution_dest) if constitution_present else None
            ),
            "audit_dir_present": audit_dir_present,
            "audit_dir_path": str(self._audit_dir) if audit_dir_present else None,
            "autoharness_cli_available": shutil.which("autoharness") is not None,
        }

    # ------------------------------------------------------------------
    # Rule generation
    # ------------------------------------------------------------------

    def _generate_rule_markdown(self, constitution: dict[str, Any]) -> str:
        """Generate a Cursor-compatible Markdown rule file from the constitution.

        Translates constitution rules, permissions, and boundaries into
        clear Markdown instructions that Cursor's AI can follow.

        Parameters
        ----------
        constitution : dict
            Parsed constitution YAML data.

        Returns
        -------
        str
            Markdown content for the rule file.
        """
        sections: list[str] = []

        # Header
        identity = constitution.get("identity", {})
        project_name = identity.get("name", "project")
        description = identity.get("description", "")

        sections.append(
            f"# AutoHarness Governance Rules for {project_name}\n"
            f"\n"
            f"> Auto-generated by AutoHarness. Do not edit manually.\n"
            f"> Re-generate with: `autoharness install cursor`\n"
        )

        if description:
            sections.append(f"{description}\n")

        # Boundaries
        boundaries = identity.get("boundaries", [])
        if boundaries:
            lines = ["## Core Boundaries\n"]
            lines.append(
                "You MUST follow these boundaries at all times. "
                "Violations will be flagged and blocked.\n"
            )
            for boundary in boundaries:
                lines.append(f"- **{boundary}**")
            sections.append("\n".join(lines) + "\n")

        # Rules
        rules = constitution.get("rules", [])
        if rules:
            lines = ["## Behavioral Rules\n"]
            for rule in rules:
                rule_id = rule.get("id", "unknown")
                desc = rule.get("description", "").strip()
                severity = rule.get("severity", "warning")
                enforcement = rule.get("enforcement", "prompt")

                severity_icon = {
                    "error": "CRITICAL",
                    "warning": "WARNING",
                    "info": "INFO",
                }.get(severity, "INFO")

                lines.append(f"### [{severity_icon}] {rule_id}\n")
                lines.append(f"{desc}\n")

                # Include trigger patterns as context for Cursor
                triggers = rule.get("triggers", [])
                if triggers:
                    lines.append("**Detected patterns:**")
                    for trigger in triggers:
                        tool = trigger.get("tool", "any")
                        pattern = trigger.get("pattern", "")
                        lines.append(f"- Tool `{tool}`: `{pattern}`")
                    lines.append("")

                if enforcement == "hook":
                    lines.append(
                        "*Enforcement: Programmatically enforced. "
                        "AutoHarness will block violations automatically.*\n"
                    )
                elif enforcement == "both":
                    lines.append(
                        "*Enforcement: Both prompt guidance and programmatic enforcement.*\n"
                    )
                else:
                    lines.append(
                        "*Enforcement: Prompt guidance. Follow this rule in all responses.*\n"
                    )

            sections.append("\n".join(lines))

        # Permissions summary
        permissions = constitution.get("permissions", {})
        tools_config = permissions.get("tools", {})
        if tools_config:
            lines = ["## Tool Permissions\n"]
            lines.append(
                "The following tools have restricted permissions. "
                "Respect these restrictions when suggesting or executing commands.\n"
            )

            for tool_name, tool_cfg in tools_config.items():
                if isinstance(tool_cfg, dict):
                    policy = tool_cfg.get("policy", "allow")
                    lines.append(f"### {tool_name} (policy: {policy})\n")

                    deny_patterns = tool_cfg.get("deny_patterns", [])
                    if deny_patterns:
                        lines.append("**Blocked patterns (NEVER execute these):**")
                        for pat in deny_patterns:
                            lines.append(f"- `{pat}`")
                        lines.append("")

                    deny_paths = tool_cfg.get("deny_paths", [])
                    if deny_paths:
                        lines.append("**Blocked paths (NEVER access these):**")
                        for path in deny_paths:
                            lines.append(f"- `{path}`")
                        lines.append("")

                    ask_patterns = tool_cfg.get("ask_patterns", [])
                    if ask_patterns:
                        lines.append("**Patterns requiring confirmation:**")
                        for pat in ask_patterns:
                            lines.append(f"- `{pat}`")
                        lines.append("")

                    ask_paths = tool_cfg.get("ask_paths", [])
                    if ask_paths:
                        lines.append("**Paths requiring confirmation:**")
                        for path in ask_paths:
                            lines.append(f"- `{path}`")
                        lines.append("")

            sections.append("\n".join(lines))

        # Defaults
        defaults = permissions.get("defaults", {})
        if defaults:
            lines = ["## Default Policies\n"]
            unknown_tool = defaults.get("unknown_tool", "ask")
            unknown_path = defaults.get("unknown_path", "deny")

            lines.append(f"- Unknown tools: **{unknown_tool}** (ask before using)")
            lines.append(f"- Unknown paths: **{unknown_path}** (do not access)")
            lines.append(
                "- On error: **deny** (when in doubt, do not proceed)\n"
            )
            sections.append("\n".join(lines))

        # Risk thresholds
        risk = constitution.get("risk", {})
        thresholds = risk.get("thresholds", {})
        if thresholds:
            lines = ["## Risk Thresholds\n"]
            lines.append("When assessing the risk of an action:\n")
            for level, action in thresholds.items():
                lines.append(f"- **{level}** risk: {action}")
            lines.append("")
            sections.append("\n".join(lines))

        # Footer
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sections.append(
            f"---\n"
            f"*Generated by AutoHarness on {now}*\n"
        )

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Hook installation
    # ------------------------------------------------------------------

    def _install_hooks(self) -> bool:
        """Install AutoHarness hook scripts for Cursor 0.50+.

        Creates a shell script in ``.cursor/hooks/`` that invokes
        the AutoHarness CLI for pre-tool-use checks.

        Returns
        -------
        bool
            True if hooks were installed successfully.
        """
        try:
            self._hooks_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not create hooks directory %s: %s. "
                "Hook installation skipped (Cursor 0.50+ required).",
                self._hooks_dir,
                exc,
            )
            return False

        hook_content = textwrap.dedent("""\
            #!/usr/bin/env bash
            # AutoHarness pre-tool-use hook for Cursor
            # Auto-generated — do not edit manually.
            # Re-generate with: autoharness install cursor

            set -euo pipefail

            # Read tool call from stdin and pass to autoharness for checking
            if command -v autoharness &>/dev/null; then
                autoharness check --stdin --format hook
            else
                echo "Warning: autoharness CLI not found on PATH" >&2
                echo "Install with: pip install autoharness" >&2
                # Don't block — just warn
                exit 0
            fi
        """)

        try:
            self._write_file_atomic(self._hook_script, hook_content)
            # Make the hook script executable
            self._hook_script.chmod(0o755)
            logger.info("Installed hook script: %s", self._hook_script)
            return True
        except OSError as exc:
            logger.warning(
                "Could not install hook script %s: %s", self._hook_script, exc
            )
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _verify_autoharness_cli(self) -> None:
        """Warn (but don't fail) if the autoharness CLI is not on PATH."""
        if shutil.which("autoharness") is None:
            logger.warning(
                "The 'autoharness' CLI command was not found on PATH. "
                "Rules will be installed but hooks will fail at runtime unless "
                "autoharness is installed (pip install autoharness) and available on PATH."
            )

    def _load_constitution(
        self, constitution_path: str | Path | None
    ) -> dict[str, Any]:
        """Load and parse the constitution YAML file.

        Parameters
        ----------
        constitution_path : str | Path | None
            Path to the constitution file. If None, loads the bundled default.

        Returns
        -------
        dict
            Parsed constitution data.
        """
        if constitution_path is not None:
            source = Path(constitution_path)
            if not source.exists():
                raise CursorError(
                    f"Constitution file not found: {source}. "
                    f"Provide a valid path or omit to use defaults."
                )
            if not source.is_file():
                raise CursorError(
                    f"Constitution path is not a file: {source}"
                )
            try:
                text = source.read_text(encoding="utf-8")
            except (PermissionError, OSError) as exc:
                raise CursorError(
                    f"Cannot read constitution file {source}: {exc}"
                ) from exc
        else:
            # Load the bundled default template
            default_template = (
                Path(__file__).resolve().parent.parent / "templates" / "default.yaml"
            )
            if not default_template.exists():
                raise CursorError(
                    f"Default constitution template not found at {default_template}. "
                    f"Please provide a constitution path explicitly."
                )
            text = default_template.read_text(encoding="utf-8")

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise CursorError(
                f"Invalid YAML in constitution file: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise CursorError(
                f"Expected a YAML mapping at the top level, "
                f"got {type(data).__name__}."
            )

        return data

    def _copy_constitution(self, source: Path) -> bool:
        """Copy a constitution file to the autoharness config directory.

        Parameters
        ----------
        source : Path
            Path to the source constitution YAML file.

        Returns
        -------
        bool
            True if the file was copied successfully.

        Raises
        ------
        CursorError
            If the source file doesn't exist or can't be copied.
        """
        if not source.exists():
            raise CursorError(
                f"Constitution file not found: {source}. "
                f"Provide a valid path or omit to use defaults."
            )

        if not source.is_file():
            raise CursorError(
                f"Constitution path is not a file: {source}"
            )

        try:
            shutil.copy2(source, self._constitution_dest)
            logger.info(
                "Copied constitution: %s -> %s",
                source,
                self._constitution_dest,
            )
            return True
        except PermissionError as exc:
            raise CursorError(
                f"Permission denied copying constitution to "
                f"{self._constitution_dest}: {exc}"
            ) from exc
        except OSError as exc:
            raise CursorError(
                f"Failed to copy constitution to "
                f"{self._constitution_dest}: {exc}"
            ) from exc

    @staticmethod
    def _write_file_atomic(path: Path, content: str) -> None:
        """Write a file atomically via a temp file and rename.

        Parameters
        ----------
        path : Path
            Destination file path.
        content : str
            File content to write.

        Raises
        ------
        CursorError
            On permission or I/O errors.
        """
        try:
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.rename(path)
        except PermissionError as exc:
            raise CursorError(
                f"Permission denied writing {path}: {exc}"
            ) from exc
        except OSError as exc:
            raise CursorError(
                f"Failed to write {path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        installed = self.status().get("installed", False)
        return (
            f"<CursorInstaller project_dir={self._project_dir!r} "
            f"installed={installed}>"
        )
