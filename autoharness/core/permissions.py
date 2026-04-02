"""Permission Engine for AutoHarness.

A 3-level permission model (tool -> path -> operation) with layered
defense. Evaluates tool calls against constitution rules and returns
ALLOW / DENY / ASK decisions.

Decision priority (highest wins, matching resolveHookPermissionDecision):
  1. Explicit deny (constitution deny_paths/deny_patterns) -> ABSOLUTE DENY
  2. Hook deny -> ABSOLUTE DENY
  3. ask_patterns match -> ASK
  4. Risk >= threshold -> action based on threshold config
  5. Hook allow (CANNOT override denies above!) -> ALLOW
  6. Explicit allow_patterns/allow_paths -> ALLOW
  7. Tool default policy -> per-policy behavior
  8. Global default (unknown_tool) -> usually ASK
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDecision,
    PermissionDefaults,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolPermission,
)

logger = logging.getLogger("autoharness.permissions")

# Ordered risk levels for comparison
_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.low: 0,
    RiskLevel.medium: 1,
    RiskLevel.high: 2,
    RiskLevel.critical: 3,
}

# Tool names whose input typically contains a file path
_PATH_KEYS = ("file_path", "path", "filename", "file")
# Tool names that are bash-like and carry a command string
_BASH_TOOLS = {"bash", "shell", "terminal", "execute", "run"}


class PermissionEngine:
    """Evaluates tool calls against a 3-level permission model.

    Levels:
        1. **Tool level** -- is the tool allowed at all?
        2. **Path level** -- is the resolved file path permitted?
        3. **Operation level** -- is the command / operation string permitted?

    The engine combines these checks with hook results and risk assessment
    to produce a single ``PermissionDecision``.
    """

    def __init__(
        self,
        defaults: PermissionDefaults | dict[str, Any] | None = None,
        tools: dict[str, ToolPermission | dict[str, Any]] | None = None,
        *,
        project_dir: str | None = None,
    ) -> None:
        # Normalize defaults
        if defaults is None:
            self._defaults = PermissionDefaults()
        elif isinstance(defaults, dict):
            self._defaults = PermissionDefaults(**{
                k: v for k, v in defaults.items() if k in PermissionDefaults.model_fields
            })
        else:
            self._defaults = defaults

        # Normalize tool permissions: convert dicts to ToolPermission objects
        self._tools: dict[str, ToolPermission] = {}
        for name, tp in (tools or {}).items():
            if isinstance(tp, dict):
                # Ensure 'policy' field exists with a sensible default
                if "policy" not in tp:
                    tp = {**tp, "policy": "restricted"}
                try:
                    self._tools[name] = ToolPermission(**{
                        k: v for k, v in tp.items() if k in ToolPermission.model_fields
                    })
                except Exception:
                    logger.warning("Skipping invalid tool permission for %s", name)
            else:
                self._tools[name] = tp

        self._project_dir = project_dir or os.getcwd()
        # Pre-compile regex patterns per tool for performance
        self._compiled: dict[str, dict[str, list[re.Pattern[str]]]] = {}
        for name, tp in self._tools.items():
            self._compiled[name] = {
                "deny": self._compile_patterns(tp.deny_patterns, name, "deny"),
                "ask": self._compile_patterns(tp.ask_patterns, name, "ask"),
                "allow": self._compile_patterns(tp.allow_patterns, name, "allow"),
            }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        hook_results: list[HookResult],
    ) -> PermissionDecision:
        """Return the final permission decision for *tool_call*.

        Applies the 8-priority cascade described in the module docstring.
        """
        tool_name = tool_call.tool_name

        # -- Priority 1: Explicit constitution denies (path + operation) --
        path = self._extract_path(tool_call)
        command = self._extract_command(tool_call)

        path_decision = self.check_path_level(tool_name, path) if path else None
        op_decision = self.check_operation_level(tool_name, command) if command else None

        if path_decision and path_decision.action == "deny":
            logger.info(
                "DENY (constitution path deny) tool=%s path=%s", tool_name, path
            )
            return path_decision

        if op_decision and op_decision.action == "deny":
            logger.info(
                "DENY (constitution pattern deny) tool=%s command=%s",
                tool_name,
                _truncate(command),
            )
            return op_decision

        # -- Priority 2: Hook deny --
        for hr in hook_results:
            if hr.action == HookAction.deny:
                logger.info(
                    "DENY (hook) tool=%s reason=%s",
                    tool_name,
                    hr.reason,
                )
                return PermissionDecision(
                    action="deny", reason=hr.reason or "Blocked by hook", source="hook",
                )

        # -- Priority 1 (tool level deny check, slightly lower than path/op) --
        tool_decision = self.check_tool_level(tool_name)
        if tool_decision and tool_decision.action == "deny":
            logger.info("DENY (tool not allowed) tool=%s", tool_name)
            return tool_decision

        # -- Priority 3: ask_patterns / ask_paths --
        if path_decision and path_decision.action == "ask":
            logger.info(
                "ASK (constitution ask_path) tool=%s path=%s", tool_name, path
            )
            return path_decision

        if op_decision and op_decision.action == "ask":
            logger.info(
                "ASK (constitution ask_pattern) tool=%s command=%s",
                tool_name,
                _truncate(command),
            )
            return op_decision

        # -- Priority 4: Risk threshold (skipped — handled by pipeline) --

        # -- Priority 5: Hook allow (cannot override denies above) --
        hook_resolved = self._resolve_hook_permission(
            hook_results, PermissionDecision(action="ask", reason="default", source="hook"),
        )
        if hook_resolved.action == "allow":
            logger.info("ALLOW (hook) tool=%s", tool_name)
            return hook_resolved
        if hook_resolved.action == "ask":
            has_hook_ask = any(hr.action is HookAction.ask for hr in hook_results)
            if has_hook_ask:
                logger.info("ASK (hook) tool=%s", tool_name)
                return hook_resolved

        # -- Priority 6: Explicit allow_paths / allow_patterns --
        if path_decision and path_decision.action == "allow":
            logger.info(
                "ALLOW (constitution allow_path) tool=%s path=%s", tool_name, path
            )
            return path_decision

        if op_decision and op_decision.action == "allow":
            logger.info(
                "ALLOW (constitution allow_pattern) tool=%s command=%s",
                tool_name,
                _truncate(command),
            )
            return op_decision

        # -- Priority 7: Tool default policy --
        tp = self._tools.get(tool_name)
        if tp is not None and tp.policy is not None:
            logger.info(
                "%s (tool policy) tool=%s",
                tp.policy.upper(),
                tool_name,
            )
            policy_action: Literal["allow", "deny", "ask"] = (
                tp.policy if tp.policy in ("allow", "deny") else "ask"  # type: ignore[assignment]
            )
            return PermissionDecision(
                action=policy_action,
                reason=f"Tool policy: {tp.policy}",
                source="tool_policy",
            )

        # -- Priority 8: Global default --
        if tp is None:
            default_action = self._defaults.unknown_tool
            logger.info(
                "%s (unknown tool fallback) tool=%s",
                default_action.upper(),
                tool_name,
            )
            return PermissionDecision(
                action=default_action,
                reason=f"Unknown tool fallback: {default_action}",
                source="defaults",
            )

        # Known tool, no specific policy — use defaults
        return PermissionDecision(
            action="ask", reason="No specific policy matched", source="defaults",
        )

    # ------------------------------------------------------------------
    # Level 1: Tool
    # ------------------------------------------------------------------

    def check_tool_level(self, tool_name: str) -> PermissionDecision | None:
        """Check whether *tool_name* is allowed at the tool level.

        Returns a DENY decision if the tool is explicitly disallowed,
        ``None`` if no tool-level decision can be made (fall through).
        """
        tp = self._tools.get(tool_name)
        if tp is None:
            return None  # unknown — handled at priority 8
        if tp.policy == "deny":
            return PermissionDecision(
                action="deny",
                reason=f"Tool '{tool_name}' is denied by policy",
                source="tool_policy",
            )
        return None  # allowed at tool level, continue checking

    # ------------------------------------------------------------------
    # Level 2: Path
    # ------------------------------------------------------------------

    def check_path_level(
        self, tool_name: str, path: str | None
    ) -> PermissionDecision | None:
        """Check path-based permission for *tool_name* operating on *path*.

        Uses glob matching (``fnmatch``) with ``~`` and ``${PROJECT_DIR}``
        expansion.  Returns the most restrictive matching decision, or
        ``None`` if no path rules match.
        """
        if path is None:
            return None

        # Security Layer 1-4: TOCTOU attack vector detection
        toctou_reason = self._has_toctou_risk(path)
        if toctou_reason:
            logger.warning("DENY (TOCTOU risk) path=%s reason=%s", path, toctou_reason)
            return PermissionDecision(
                action="deny", reason=toctou_reason, source="toctou_guard",
            )

        # Security Layer 5: path traversal detection
        if self._is_traversal(path):
            logger.warning("DENY (path traversal detected) path=%s", path)
            return PermissionDecision(
                action="deny",
                reason=f"Path traversal detected: {path}",
                source="path_guard",
            )

        # Security Layer 8: dangerous removal target detection
        danger = self._is_dangerous_removal(path)
        if danger:
            logger.warning("DENY (dangerous path) path=%s", path)
            return PermissionDecision(
                action="deny", reason=danger, source="dangerous_path_guard",
            )

        tp = self._tools.get(tool_name)
        if tp is None:
            return None

        resolved = self._expand_path(path)

        # Deny takes absolute precedence
        for pattern in tp.deny_paths:
            if fnmatch.fnmatch(resolved, self._expand_path(pattern)):
                logger.debug("Path deny match: %s against %s", resolved, pattern)
                return PermissionDecision(
                    action="deny", reason=f"Path matches deny rule: {pattern}", source="deny_paths",
                )

        # Ask
        for pattern in tp.ask_paths:
            if fnmatch.fnmatch(resolved, self._expand_path(pattern)):
                logger.debug("Path ask match: %s against %s", resolved, pattern)
                return PermissionDecision(
                    action="ask", reason=f"Path matches ask rule: {pattern}", source="ask_paths",
                )

        # Allow
        for pattern in tp.allow_paths:
            if fnmatch.fnmatch(resolved, self._expand_path(pattern)):
                logger.debug("Path allow match: %s against %s", resolved, pattern)
                return PermissionDecision(
                    action="allow",
                    reason=f"Path matches allow rule: {pattern}",
                    source="allow_paths",
                )

        return None  # no path rule matched

    # ------------------------------------------------------------------
    # Level 3: Operation
    # ------------------------------------------------------------------

    def check_operation_level(
        self, tool_name: str, operation: str | None
    ) -> PermissionDecision | None:
        """Check operation/command-level permission using regex patterns.

        Returns the most restrictive matching decision, or ``None`` if no
        operation rules match.
        """
        if operation is None:
            return None

        compiled = self._compiled.get(tool_name)
        if compiled is None:
            return None

        # Deny first
        for rx in compiled["deny"]:
            if rx.search(operation):
                logger.debug(
                    "Operation deny match: %s against %s", _truncate(operation), rx.pattern
                )
                return PermissionDecision(
                    action="deny",
                    reason=f"Operation matches deny pattern: {rx.pattern}",
                    source="deny_patterns",
                )

        # Ask
        for rx in compiled["ask"]:
            if rx.search(operation):
                logger.debug(
                    "Operation ask match: %s against %s", _truncate(operation), rx.pattern
                )
                return PermissionDecision(
                    action="ask",
                    reason=f"Operation matches ask pattern: {rx.pattern}",
                    source="ask_patterns",
                )

        # Allow
        for rx in compiled["allow"]:
            if rx.search(operation):
                logger.debug(
                    "Operation allow match: %s against %s", _truncate(operation), rx.pattern
                )
                return PermissionDecision(
                    action="allow",
                    reason=f"Operation matches allow pattern: {rx.pattern}",
                    source="allow_patterns",
                )

        return None

    # ------------------------------------------------------------------
    # Hook resolution
    # ------------------------------------------------------------------

    def _resolve_hook_permission(
        self,
        hook_results: list[HookResult],
        base_decision: PermissionDecision,
    ) -> PermissionDecision:
        """Resolve hook results into a single permission decision.

        CRITICAL invariant: hook ALLOW can never override a constitution
        DENY.  Hook DENY always wins.  Hook ASK becomes the decision if
        nothing else denies.

        The *base_decision* is the fallback when no hook expresses an
        opinion.
        """
        has_deny = False
        has_allow = False
        has_ask = False

        for hr in hook_results:
            if hr.action is HookAction.deny:
                has_deny = True
            elif hr.action is HookAction.allow:
                has_allow = True
            elif hr.action is HookAction.ask:
                has_ask = True
            # SKIP is intentionally ignored

        # Deny always wins
        if has_deny:
            return PermissionDecision(action="deny", reason="Hook denied", source="hook")

        # ASK takes precedence over ALLOW among hooks
        if has_ask:
            return PermissionDecision(
                action="ask",
                reason="Hook requires confirmation",
                source="hook",
            )

        if has_allow:
            return PermissionDecision(action="allow", reason="Hook allowed", source="hook")

        return base_decision

    # ------------------------------------------------------------------
    # Input extraction helpers
    # ------------------------------------------------------------------

    def _extract_path(self, tool_call: ToolCall) -> str | None:
        """Extract a file path from the tool call input.

        Handles common tool schemas: ``file_path``, ``path``, ``filename``,
        as well as bash commands that reference file paths.
        """
        # Direct path keys
        for key in _PATH_KEYS:
            value = tool_call.tool_input.get(key)
            if value and isinstance(value, str):
                return str(value)

        # For bash-type tools, try to extract a path from the command string
        if tool_call.tool_name in _BASH_TOOLS:
            cmd = tool_call.tool_input.get("command", "")
            if isinstance(cmd, str):
                return self._path_from_command(cmd)

        return None

    def _extract_command(self, tool_call: ToolCall) -> str | None:
        """Extract the command string from bash-type tool calls."""
        if tool_call.tool_name in _BASH_TOOLS:
            cmd = tool_call.tool_input.get("command", "")
            if isinstance(cmd, str) and cmd:
                return cmd
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expand_path(self, path: str) -> str:
        """Expand ``~`` and ``${PROJECT_DIR}`` in a path string."""
        path = path.replace("${PROJECT_DIR}", self._project_dir)
        path = os.path.expanduser(path)
        # Normalise but don't resolve symlinks (we check traversal separately)
        return os.path.normpath(path)

    @staticmethod
    def _is_traversal(path: str) -> bool:
        """Detect directory traversal attempts (``..`` components, symlink tricks)."""
        if ".." in Path(path).parts:
            return True
        try:
            if os.path.islink(path):
                real = os.path.realpath(path)
                if not real.startswith(os.path.dirname(os.path.abspath(path))):
                    return True
        except OSError:
            pass
        return False

    @staticmethod
    def _has_toctou_risk(path: str) -> str | None:
        """Detect TOCTOU (time-of-check-time-of-use) attack vectors in paths.

        Returns a reason string if a risk is detected, None otherwise.

        Multi-layer path validation defense:
          1. UNC path blocking — prevents credential leak via \\\\server\\share
          2. Tilde variant rejection — ~user, ~+, ~- expand differently than ~
          3. Shell expansion syntax blocking — $VAR, ${VAR}, $(cmd), `cmd`, %VAR%
          4. Glob pattern blocking for write paths — *, ?, [] bypass dir checks
          5-8 handled by _is_traversal and check_path_level
        """
        # Layer 1: UNC path blocking (Windows credential leak)
        if path.startswith("\\\\") or path.startswith("//"):
            return f"UNC/network path detected: {path[:30]}"

        # Layer 2: Tilde variant rejection
        # ~user expands to that user's home, ~+ to $PWD, ~- to $OLDPWD
        if path.startswith("~") and len(path) > 1 and path[1] not in ("/", "\\"):
            return f"Tilde variant detected (potential TOCTOU): {path[:30]}"

        # Layer 3: Shell expansion syntax blocking
        # These are literal during validation but expanded by shell during execution
        shell_expansion_patterns = [
            ("$", "Shell variable expansion ($VAR)"),
            ("`", "Shell command substitution (`cmd`)"),
            ("%", "Windows environment variable (%VAR%)"),
        ]
        for char, reason in shell_expansion_patterns:
            if char in path:
                return f"{reason} in path: {path[:40]}"

        # Also check for $() and ${} explicitly
        if "$(" in path or "${" in path:
            return f"Shell command/variable expansion in path: {path[:40]}"

        # Layer 4: Glob pattern blocking (for paths that might bypass dir checks)
        glob_chars = set("*?[")
        if glob_chars.intersection(path):
            return f"Glob pattern in path (potential directory bypass): {path[:40]}"

        return None

    @staticmethod
    def _is_dangerous_removal(path: str) -> str | None:
        """Detect dangerous removal targets (rm /, rm ~, rm /usr, drive roots).

        Returns a reason string if dangerous, None otherwise.
        """
        normalized = os.path.normpath(path)
        # Dangerous root-level paths
        dangerous_paths = {
            "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64",
            "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys",
            "/tmp", "/usr", "/var",
            os.path.expanduser("~"),
        }
        if normalized in dangerous_paths:
            return f"Dangerous removal target: {normalized}"

        # Windows drive roots
        if len(normalized) <= 3 and normalized[1:2] == ":":
            return f"Drive root removal: {normalized}"

        return None

    @staticmethod
    def _path_from_command(cmd: str) -> str | None:
        """Best-effort extraction of a file path from a shell command.

        Looks for tokens that look like absolute or relative file paths.
        """
        for token in cmd.split():
            if token.startswith("/") or token.startswith("~") or token.startswith("./"):
                # Strip trailing punctuation that might be shell syntax
                cleaned = token.rstrip(";|&")
                if cleaned:
                    return cleaned
        return None

    @staticmethod
    def _compile_patterns(
        patterns: list[str], tool_name: str, category: str
    ) -> list[re.Pattern[str]]:
        """Compile a list of regex pattern strings, logging any errors."""
        compiled: list[re.Pattern[str]] = []
        for raw in patterns:
            try:
                compiled.append(re.compile(raw))
            except re.error as exc:
                logger.error(
                    "Invalid regex in %s.%s_patterns: %r — %s",
                    tool_name,
                    category,
                    raw,
                    exc,
                )
        return compiled


# ------------------------------------------------------------------
# Module-level utilities
# ------------------------------------------------------------------


def _truncate(s: str | None, max_len: int = 80) -> str:
    """Truncate a string for safe log output."""
    if s is None:
        return "<none>"
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."
