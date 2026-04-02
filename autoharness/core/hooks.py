"""Hook Registry — manages registration and execution of pre/post tool use hooks.

Hooks are functions that run before or after tool execution, providing
guardrails such as secret scanning, path guarding, risk-based gating,
config protection, and output sanitization.

Profiles control which built-in hooks are active:
  - minimal:  secret_scanner, path_guard
  - standard: minimal + risk_classifier, output_sanitizer
  - strict:   standard + config_protector
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDecision,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolResult,
)
from autoharness.rules.builtin import BUILTIN_RULES

_F = TypeVar("_F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HookEntry — typed container for a registered hook
# ---------------------------------------------------------------------------


@dataclass
class HookEntry:
    """A single registered hook with priority and timeout metadata."""

    name: str
    handler: Callable[..., Any]
    priority: int = 100  # Lower number = higher priority, runs first
    timeout: float = 10.0  # seconds, 0 = no timeout


def _run_with_timeout(func: Callable[..., Any], args: tuple[Any, ...], timeout: float) -> Any:
    """Run a function with a timeout. Returns result or raises TimeoutError."""
    if timeout <= 0:
        return func(*args)

    result: list[Any] = [None]
    error: list[BaseException | None] = [None]

    def target() -> None:
        try:
            result[0] = func(*args)
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        raise TimeoutError(f"Hook timed out after {timeout}s")
    if error[0]:
        raise error[0]
    return result[0]


# ---------------------------------------------------------------------------
# Module-level decorator registry
# ---------------------------------------------------------------------------

_REGISTERED_HOOKS: dict[str, list[Callable[..., Any]]] = {
    "pre_tool_use": [],
    "post_tool_use": [],
    "on_block": [],
}


def hook(event: str, name: str | None = None) -> Callable[[_F], _F]:
    """Decorator to register a custom hook function.

    Usage::

        @hook("pre_tool_use", name="my_scanner")
        def my_scanner(tool_call, risk, context):
            ...
            return HookResult(action=HookAction.allow, reason="clean")
    """

    def decorator(func: _F) -> _F:
        hook_name = name or func.__name__
        func._hook_name = hook_name  # type: ignore[attr-defined]
        func._hook_event = event  # type: ignore[attr-defined]
        _REGISTERED_HOOKS.setdefault(event, []).append(func)
        return func

    return decorator


# ---------------------------------------------------------------------------
# Compiled patterns for built-in hooks
# ---------------------------------------------------------------------------

# Secret patterns compiled from the secrets_in_content rules
_SECRET_COMPILED: list[tuple[str, re.Pattern[str]]] = []

# Protected config patterns
_CONFIG_COMPILED: list[re.Pattern[str]] = []

_PATTERNS_INITIALIZED = False


def _ensure_patterns() -> None:
    """Lazily compile regex patterns from builtin rules on first use."""
    global _PATTERNS_INITIALIZED
    if _PATTERNS_INITIALIZED:
        return

    # Secrets — pull from secrets_in_content category
    secrets_by_level = BUILTIN_RULES.get("secrets_in_content", {})
    for _level, patterns in secrets_by_level.items():
        for rp in patterns:
            try:
                compiled = re.compile(rp.pattern)
                _SECRET_COMPILED.append((rp.description, compiled))
            except re.error:
                logger.warning("Failed to compile secret pattern: %s", rp.pattern)

    # Protected config file patterns — common linter/formatter configs
    _protected_config_patterns = [
        r"\.eslintrc(?:\.(?:js|cjs|mjs|json|yml|yaml))?$",
        r"\.prettierrc(?:\.(?:js|cjs|mjs|json|yml|yaml|toml))?$",
        r"prettier\.config\.(?:js|cjs|mjs)$",
        r"biome\.jsonc?$",
        r"ruff\.toml$",
        r"\.flake8$",
        r"\.pylintrc$",
        r"pyproject\.toml$",
        r"tsconfig(?:\..*)?\.json$",
        r"\.stylelintrc(?:\.(?:js|cjs|mjs|json|yml|yaml))?$",
        r"\.editorconfig$",
        r"\.rustfmt\.toml$",
        r"clippy\.toml$",
        r"\.golangci\.ya?ml$",
        r"\.rubocop\.ya?ml$",
    ]
    for pat in _protected_config_patterns:
        try:
            _CONFIG_COMPILED.append(re.compile(pat))
        except re.error:
            logger.warning("Failed to compile config pattern: %s", pat)

    _PATTERNS_INITIALIZED = True


# ---------------------------------------------------------------------------
# Helper functions for extracting data from the new ToolCall model
# ---------------------------------------------------------------------------

_PATH_TRAVERSAL_PATTERN = re.compile(r"(?:^|/)\.\.(?:/|$)")

_PATH_KEYS = frozenset({
    "file_path", "path", "file", "directory", "dir", "dest", "destination",
    "command",  # bash commands may contain paths
})


def _extract_paths(tool_call: ToolCall) -> list[str]:
    """Extract file path strings from a tool call's tool_input dict."""
    paths: list[str] = []
    for key in _PATH_KEYS:
        val = tool_call.tool_input.get(key)
        if isinstance(val, str) and val:
            paths.append(val)
    # Scan all string values for path-like content
    for val in tool_call.tool_input.values():
        if isinstance(val, str) and "/" in val and len(val) < 500 and val not in paths:
            paths.append(val)
    return paths


def _collect_text(tool_call: ToolCall) -> str:
    """Collect all scannable text from a tool call's inputs."""
    parts: list[str] = []
    for val in tool_call.tool_input.values():
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, dict):
            # Recurse one level into nested dicts
            for nested_val in val.values():
                if isinstance(nested_val, str):
                    parts.append(nested_val)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ShellHook — external process hooks (Hook I/O Protocol, compatible with Claude Code)
# ---------------------------------------------------------------------------


class ShellHook:
    """A hook that executes an external command via subprocess.

    Implements the Hook I/O protocol (compatible with Claude Code):

    - **Input**: Tool call data is sent as JSON to the hook process via stdin.
    - **Output**: Hook decision as JSON on stdout.
    - **Exit codes**: 0 = allow (stdout parsed), 1 = error (treat as allow
      with warning), 2 = deny.

    Parameters
    ----------
    command : str
        Shell command to execute.
    timeout : float
        Maximum seconds to wait for the process.  Defaults to 10.
    matcher : str | None
        Regex pattern to match against tool names.  If ``None``, the hook
        matches all tools.
    """

    def __init__(
        self,
        command: str,
        timeout: float = 10.0,
        matcher: str | None = None,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self.matcher = matcher

    def matches(self, tool_name: str) -> bool:
        """Return True if this hook should run for the given tool name."""
        if not self.matcher:
            return True
        return bool(re.match(self.matcher, tool_name))

    def execute(self, input_data: dict[str, Any]) -> HookResult:
        """Run the shell command with JSON on stdin, parse stdout.

        Returns
        -------
        HookResult
            The parsed decision from the shell hook.
        """
        stdin_data = json.dumps(input_data)
        try:
            proc = subprocess.run(
                self.command,
                shell=True,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return HookResult(
                action=HookAction.allow,
                reason=f"Hook timed out after {self.timeout}s",
                severity="warning",
            )

        # Exit code 2 => deny
        if proc.returncode == 2:
            reason = (
                proc.stdout.strip() or proc.stderr.strip()
                or "Denied by shell hook"
            )
            # Try to parse JSON from stdout for a structured reason
            try:
                data = json.loads(proc.stdout)
                reason = data.get("reason", reason)
            except (json.JSONDecodeError, TypeError):
                pass
            return HookResult(
                action=HookAction.deny,
                reason=reason,
                severity="error",
            )

        # Exit code 1 => error, treat as allow with warning
        if proc.returncode == 1:
            return HookResult(
                action=HookAction.allow,
                reason=f"Shell hook error: {proc.stderr[:200]}",
                severity="warning",
            )

        # Exit code 0 => parse stdout for structured response
        if proc.stdout.strip():
            try:
                data = json.loads(proc.stdout)
                action_str = data.get("decision", "allow")
                action_map = {
                    "allow": HookAction.allow,
                    "deny": HookAction.deny,
                    "ask": HookAction.ask,
                }
                return HookResult(
                    action=action_map.get(action_str, HookAction.allow),
                    reason=data.get("reason"),
                    modified_input=data.get("updatedInput"),
                )
            except (json.JSONDecodeError, TypeError):
                pass

        return HookResult(action=HookAction.allow, reason="Shell hook passed")

    def __repr__(self) -> str:
        return (
            f"<ShellHook command={self.command!r} "
            f"timeout={self.timeout} matcher={self.matcher!r}>"
        )


# ---------------------------------------------------------------------------
# HookRegistry
# ---------------------------------------------------------------------------

_PROFILE_LEVELS = {"minimal": 0, "standard": 1, "strict": 2}


class HookRegistry:
    """Manages registration and ordered execution of lifecycle hooks.

    Parameters
    ----------
    profile : str
        One of ``"minimal"``, ``"standard"``, ``"strict"``.  Controls which
        built-in hooks are registered at init time.
    project_root : str | None
        Root directory for path-guard scope checking.  Defaults to cwd.
    """

    def __init__(
        self,
        profile: str = "standard",
        project_root: str | None = None,
    ) -> None:
        if profile not in _PROFILE_LEVELS:
            raise ValueError(
                f"Unknown profile {profile!r}. "
                f"Choose from: {', '.join(_PROFILE_LEVELS)}"
            )
        self._profile = profile
        self._profile_level = _PROFILE_LEVELS[profile]
        self._project_root = os.path.realpath(project_root or os.getcwd())

        # Hook storage: event -> list of HookEntry
        self._pre_hooks: list[HookEntry] = []
        self._post_hooks: list[HookEntry] = []
        self._block_hooks: list[HookEntry] = []

        # Lifecycle hook storage: event name -> list of HookEntry
        self._lifecycle_hooks: dict[str, list[HookEntry]] = {
            "SessionStart": [],
            "SessionEnd": [],
            "PreCompact": [],
            "PostCompact": [],
            "Stop": [],
            "SubagentStart": [],
            "SubagentStop": [],
            "PermissionDenied": [],
            "PostToolUseFailure": [],
        }

        # Shell hook storage: event -> list of (name, ShellHook)
        self._shell_hooks: dict[str, list[tuple[str, ShellHook]]] = {
            "pre_tool_use": [],
            "post_tool_use": [],
            "on_block": [],
        }

        # Ensure compiled patterns are ready
        _ensure_patterns()

        # Register built-in hooks based on profile level
        self._register_builtin_hooks()

        logger.debug(
            "HookRegistry initialized: profile=%s, project_root=%s, "
            "pre_hooks=%d, post_hooks=%d",
            profile,
            self._project_root,
            len(self._pre_hooks),
            len(self._post_hooks),
        )

    # ------------------------------------------------------------------
    # Built-in hook registration
    # ------------------------------------------------------------------

    def _register_builtin_hooks(self) -> None:
        """Register built-in hooks according to the active profile."""
        # minimal+ hooks (priority 10 — built-ins run early)
        if self._profile_level >= 0:
            self._pre_hooks.append(HookEntry(
                "secret_scanner", self._secret_scanner,
                priority=10, timeout=10.0,
            ))
            self._pre_hooks.append(HookEntry(
                "path_guard", self._path_guard,
                priority=10, timeout=10.0,
            ))

        # standard+ hooks
        if self._profile_level >= 1:
            self._pre_hooks.append(HookEntry(
                "risk_classifier", self._risk_classifier_hook,
                priority=20, timeout=10.0,
            ))
            self._post_hooks.append(HookEntry(
                "output_sanitizer", self._output_sanitizer,
                priority=10, timeout=10.0,
            ))

        # strict+ hooks
        if self._profile_level >= 2:
            self._pre_hooks.append(HookEntry(
                "config_protector", self._config_protector,
                priority=20, timeout=10.0,
            ))

    # ------------------------------------------------------------------
    # Built-in pre-hooks
    # ------------------------------------------------------------------

    def _secret_scanner(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> HookResult:
        """Scan tool call inputs for secrets (API keys, passwords, tokens).

        Active at profile: minimal+
        """
        text = _collect_text(tool_call)
        if not text.strip():
            return HookResult(action=HookAction.allow)

        for description, pattern in _SECRET_COMPILED:
            match = pattern.search(text)
            if match:
                matched_text = match.group(0)
                # Truncate for logging safety
                redacted = matched_text[:8] + "..." if len(matched_text) > 8 else "***"
                logger.warning(
                    "Secret detected by secret_scanner: %s (matched: %s)",
                    description,
                    redacted,
                )
                return HookResult(
                    action=HookAction.deny,
                    reason=f"Secret detected in tool input: {description}",
                    severity="error",
                )

        return HookResult(action=HookAction.allow)

    def _path_guard(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> HookResult:
        """Check that file paths stay within the project scope.

        Detects ``../`` traversal sequences and paths that resolve outside
        the project root directory.

        Active at profile: minimal+
        """
        paths = _extract_paths(tool_call)
        if not paths:
            return HookResult(action=HookAction.allow)

        for raw_path in paths:
            # Check for explicit traversal patterns
            if _PATH_TRAVERSAL_PATTERN.search(raw_path):
                return HookResult(
                    action=HookAction.deny,
                    reason=f"Path traversal detected: {raw_path!r}",
                    severity="error",
                )

            # Resolve and check containment
            try:
                resolved = os.path.realpath(raw_path)
            except (OSError, ValueError):
                continue  # Can't resolve — skip rather than false-positive

            if (
                not resolved.startswith(self._project_root + os.sep)
                and resolved != self._project_root
            ):
                # Allow /tmp and other common safe system paths
                safe_prefixes = (
                    "/tmp", "/var/tmp", "/dev/null", "/dev/stderr", "/dev/stdout",
                )
                if not any(resolved.startswith(p) for p in safe_prefixes):
                    return HookResult(
                        action=HookAction.deny,
                        reason=(
                            f"Path escapes project directory: {raw_path!r} "
                            f"resolves to {resolved!r} "
                            f"(project root: {self._project_root!r})"
                        ),
                        severity="error",
                    )

        return HookResult(action=HookAction.allow)

    def _risk_classifier_hook(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> HookResult:
        """Translate a RiskAssessment into a hook action.

        Mapping:
          - critical -> deny
          - high     -> ask
          - medium   -> allow (logged by audit engine)
          - low      -> allow (no action needed)

        Active at profile: standard+
        """
        if risk.level == RiskLevel.critical:
            return HookResult(
                action=HookAction.deny,
                reason=f"Critical risk: {risk.reason}",
                severity="error",
            )
        elif risk.level == RiskLevel.high:
            return HookResult(
                action=HookAction.ask,
                reason=f"High risk requires confirmation: {risk.reason}",
                severity="warning",
            )
        elif risk.level == RiskLevel.medium:
            return HookResult(
                action=HookAction.allow,
                reason=f"Medium risk (logged): {risk.reason}",
                severity="warning",
            )
        else:
            return HookResult(
                action=HookAction.allow,
                severity="info",
            )

    def _config_protector(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> HookResult:
        """Block modifications to linter/formatter configuration files.

        The philosophy: if the linter complains, fix the code — don't weaken
        the linter.

        Active at profile: strict+
        """
        # Only relevant for write-type tools
        write_tools = {"file_write", "file_edit", "Edit", "Write"}
        if tool_call.tool_name not in write_tools:
            return HookResult(action=HookAction.allow)

        paths = _extract_paths(tool_call)
        for raw_path in paths:
            basename = os.path.basename(raw_path)
            for pattern in _CONFIG_COMPILED:
                if pattern.search(basename) or pattern.search(raw_path):
                    return HookResult(
                        action=HookAction.deny,
                        reason=(
                            f"Modification to protected config file blocked: "
                            f"{basename!r}. Fix the code, don't weaken the linter."
                        ),
                        severity="error",
                    )

        return HookResult(action=HookAction.allow)

    # ------------------------------------------------------------------
    # Built-in post-hooks
    # ------------------------------------------------------------------

    def _output_sanitizer(
        self,
        tool_call: ToolCall,
        result: ToolResult,
        context: dict[str, Any],
    ) -> HookResult:
        """Scan tool output for leaked secrets and replace with [REDACTED].

        Active at profile: standard+

        Because ToolResult is frozen, we cannot mutate it in place.  Instead
        we return a ``sanitize`` action with the cleaned text in
        ``sanitized_output``.  The caller is responsible for constructing a
        new ToolResult with the sanitized output.
        """
        output_text = str(result.output) if result.output is not None else ""
        if not output_text.strip():
            return HookResult(action=HookAction.allow)

        sanitized = output_text
        found_any = False

        for description, pattern in _SECRET_COMPILED:
            new_text, count = pattern.subn("[REDACTED]", sanitized)
            if count > 0:
                found_any = True
                logger.warning(
                    "Output sanitizer redacted %d occurrence(s) of: %s",
                    count,
                    description,
                )
                sanitized = new_text

        if found_any:
            return HookResult(
                action=HookAction.sanitize,
                reason="Secrets redacted from tool output",
                severity="warning",
                sanitized_output=sanitized,
            )

        return HookResult(action=HookAction.allow)

    # ------------------------------------------------------------------
    # Public registration API
    # ------------------------------------------------------------------

    def register(
        self,
        event: str,
        hook_func: Callable[..., Any],
        name: str | None = None,
        priority: int = 100,
        timeout: float = 10.0,
    ) -> None:
        """Register a hook function for a given event.

        Parameters
        ----------
        event : str
            One of ``"pre_tool_use"``, ``"post_tool_use"``, ``"on_block"``.
        hook_func : Callable
            The hook function.  Signature depends on event type.
        name : str | None
            Display name for logging; defaults to ``hook_func.__name__``.
        priority : int
            Lower number = higher priority (runs first).  Default 100.
        timeout : float
            Maximum seconds for hook execution.  0 = no timeout.  Default 10.
        """
        hook_name = (
            name
            or getattr(hook_func, "_hook_name", None)
            or hook_func.__name__
        )

        entry = HookEntry(
            name=hook_name,
            handler=hook_func,
            priority=priority,
            timeout=timeout,
        )

        if event == "pre_tool_use":
            self._pre_hooks.append(entry)
            self._pre_hooks.sort(key=lambda e: e.priority)
        elif event == "post_tool_use":
            self._post_hooks.append(entry)
            self._post_hooks.sort(key=lambda e: e.priority)
        elif event == "on_block":
            self._block_hooks.append(entry)
            self._block_hooks.sort(key=lambda e: e.priority)
        else:
            raise ValueError(
                f"Unknown hook event {event!r}. "
                "Choose from: pre_tool_use, post_tool_use, on_block"
            )

        logger.debug(
            "Registered hook: event=%s, name=%s, priority=%d, timeout=%.1f",
            event, hook_name, priority, timeout,
        )

    def register_from_decorators(self) -> None:
        """Pick up all ``@hook``-decorated functions from the module-level registry."""
        for event, funcs in _REGISTERED_HOOKS.items():
            for func in funcs:
                hook_name = getattr(func, "_hook_name", func.__name__)
                self.register(event, func, name=hook_name)
        logger.debug(
            "Registered %d decorator hooks",
            sum(len(v) for v in _REGISTERED_HOOKS.values()),
        )

    def register_hooks(self, hooks: list[Callable[..., Any]]) -> None:
        """Register a list of hook functions.

        Each function must have ``_hook_event`` and optionally ``_hook_name``
        attributes (set by the ``@hook`` decorator).  If ``_hook_event`` is
        missing, the hook is registered as ``pre_tool_use`` by default.
        """
        for func in hooks:
            event = getattr(func, "_hook_event", "pre_tool_use")
            name = getattr(func, "_hook_name", func.__name__)
            self.register(event, func, name=name)

    def register_shell_hook(
        self,
        event: str,
        command: str,
        timeout: float = 10.0,
        matcher: str | None = None,
        name: str | None = None,
    ) -> None:
        """Register a shell hook for a given event.

        Parameters
        ----------
        event : str
            One of ``"pre_tool_use"``, ``"post_tool_use"``, ``"on_block"``.
        command : str
            Shell command to execute.  Receives JSON on stdin.
        timeout : float
            Maximum seconds to wait for the process.
        matcher : str | None
            Regex pattern to match tool names.  ``None`` matches all.
        name : str | None
            Display name for logging; defaults to the command string.
        """
        if event not in self._shell_hooks:
            raise ValueError(
                f"Unknown hook event {event!r}. "
                "Choose from: pre_tool_use, post_tool_use, on_block"
            )

        hook_name = name or f"shell:{command}"
        shell_hook = ShellHook(
            command=command, timeout=timeout, matcher=matcher
        )
        self._shell_hooks[event].append((hook_name, shell_hook))
        logger.debug(
            "Registered shell hook: event=%s, name=%s, command=%s",
            event,
            hook_name,
            command,
        )

    def register_lifecycle_hook(
        self,
        event: str,
        handler: Callable[..., Any],
        name: str | None = None,
        priority: int = 100,
        timeout: float = 10.0,
    ) -> None:
        """Register a handler for a lifecycle event.

        Parameters
        ----------
        event : str
            One of the lifecycle event names: ``"SessionStart"``,
            ``"SessionEnd"``, ``"PreCompact"``, ``"PostCompact"``,
            ``"Stop"``, ``"SubagentStart"``, ``"SubagentStop"``,
            ``"PermissionDenied"``, ``"PostToolUseFailure"``.
        handler : Callable
            A function that accepts a single ``context: dict`` argument.
        name : str | None
            Display name for logging; defaults to ``handler.__name__``.
        priority : int
            Lower number = higher priority (runs first).  Default 100.
        timeout : float
            Maximum seconds for handler execution.  0 = no timeout.
        """
        if event not in self._lifecycle_hooks:
            valid = ", ".join(sorted(self._lifecycle_hooks))
            raise ValueError(
                f"Unknown lifecycle event {event!r}. Choose from: {valid}"
            )

        hook_name = name or str(getattr(handler, "__name__", "anonymous"))
        entry = HookEntry(
            name=hook_name,
            handler=handler,
            priority=priority,
            timeout=timeout,
        )
        self._lifecycle_hooks[event].append(entry)
        self._lifecycle_hooks[event].sort(key=lambda e: e.priority)
        logger.debug(
            "Registered lifecycle hook: event=%s, name=%s, priority=%d",
            event,
            hook_name,
            priority,
        )

    def fire_lifecycle_event(
        self,
        event: str,
        context: dict[str, Any],
    ) -> list[HookResult]:
        """Fire all handlers registered for a lifecycle event.

        Lifecycle hooks are informational — they do not short-circuit on
        deny.  Exceptions in individual handlers are caught and logged
        so that one failing handler does not prevent others from running.

        Parameters
        ----------
        event : str
            The lifecycle event name (e.g. ``"SessionStart"``).
        context : dict
            Arbitrary context data passed to each handler.

        Returns
        -------
        list[HookResult]
            Results from all handlers that were executed.
        """
        if event not in self._lifecycle_hooks:
            valid = ", ".join(sorted(self._lifecycle_hooks))
            raise ValueError(
                f"Unknown lifecycle event {event!r}. Choose from: {valid}"
            )

        results: list[HookResult] = []
        for entry in self._lifecycle_hooks[event]:
            try:
                result = _run_with_timeout(
                    entry.handler, (context,), entry.timeout
                )
                if isinstance(result, HookResult):
                    results.append(result)
                elif result is not None:
                    results.append(
                        HookResult(
                            action=HookAction.allow,
                            reason=str(result),
                        )
                    )
                else:
                    results.append(HookResult(action=HookAction.allow))
            except TimeoutError:
                logger.warning(
                    "Lifecycle hook %s timed out after %.1fs for event %s",
                    entry.name,
                    entry.timeout,
                    event,
                )
                results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Hook {entry.name!r} timed out after {entry.timeout}s",
                        severity="warning",
                    )
                )
            except Exception:
                logger.exception(
                    "Lifecycle hook %s raised an exception for event %s",
                    entry.name,
                    event,
                )
                results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Hook {entry.name!r} raised an exception (see logs)",
                        severity="warning",
                    )
                )

        logger.debug(
            "Fired lifecycle event %s: %d handler(s) executed",
            event,
            len(results),
        )
        return results

    def run_failure_hooks(
        self,
        tool_call: ToolCall,
        error: Exception,
        context: dict[str, Any],
    ) -> list[HookResult]:
        """Run all PostToolUseFailure hooks.

        Convenience method for the common pattern of notifying hooks when
        a tool execution fails.

        Parameters
        ----------
        tool_call : ToolCall
            The tool call that failed.
        error : Exception
            The exception that was raised.
        context : dict
            Pipeline context (session_id, project_dir, etc.).

        Returns
        -------
        list[HookResult]
            Results from all failure handlers.
        """
        failure_context = {
            **context,
            "tool_call": tool_call,
            "tool_name": tool_call.tool_name,
            "tool_input": tool_call.tool_input,
            "error": str(error),
            "error_type": type(error).__name__,
        }
        return self.fire_lifecycle_event("PostToolUseFailure", failure_context)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_pre_hooks(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> list[HookResult]:
        """Run all pre_tool_use hooks in registration order.

        Short-circuits on the first ``deny`` result but still records all
        results up to and including that point.

        Returns
        -------
        list[HookResult]
            Results from all hooks that were executed.
        """
        results: list[HookResult] = []
        denied = False

        for entry in self._pre_hooks:
            try:
                result = _run_with_timeout(
                    entry.handler, (tool_call, risk, context), entry.timeout
                )
                if not isinstance(result, HookResult):
                    logger.warning(
                        "Hook %s returned %s instead of HookResult; wrapping",
                        entry.name,
                        type(result).__name__,
                    )
                    result = HookResult(
                        action=HookAction.allow,
                        reason=str(result),
                    )
                results.append(result)

                if result.action == HookAction.deny:
                    logger.info(
                        "Pre-hook %s denied tool call %s: %s",
                        entry.name,
                        tool_call.tool_name,
                        result.reason,
                    )
                    denied = True
                    break  # Short-circuit on deny

            except TimeoutError:
                logger.warning("Pre-hook %s timed out after %.1fs", entry.name, entry.timeout)
                results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Hook {entry.name!r} timed out after {entry.timeout}s",
                        severity="warning",
                    )
                )
            except Exception:
                logger.exception("Pre-hook %s raised an exception", entry.name)
                # Hook errors should not block execution — record and continue
                results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Hook {entry.name!r} raised an exception (see logs)",
                        severity="warning",
                    )
                )

        # Run shell hooks (if not already denied)
        if not denied:
            for hook_name, shell_hook in self._shell_hooks.get("pre_tool_use", []):
                if not shell_hook.matches(tool_call.tool_name):
                    continue
                try:
                    input_data = {
                        "tool_name": tool_call.tool_name,
                        "tool_input": tool_call.tool_input,
                        "session_id": tool_call.session_id or "",
                        "risk_level": risk.level.value,
                    }
                    result = shell_hook.execute(input_data)
                    results.append(result)

                    if result.action == HookAction.deny:
                        logger.info(
                            "Shell pre-hook %s denied tool call %s: %s",
                            hook_name,
                            tool_call.tool_name,
                            result.reason,
                        )
                        denied = True
                        break
                except Exception:
                    logger.exception(
                        "Shell pre-hook %s raised an exception", hook_name
                    )
                    results.append(
                        HookResult(
                            action=HookAction.allow,
                            reason=f"Shell hook {hook_name!r} raised an exception (see logs)",
                            severity="warning",
                        )
                    )

        if not denied:
            logger.debug(
                "All %d pre-hooks passed for tool %s",
                len(self._pre_hooks) + len(self._shell_hooks.get("pre_tool_use", [])),
                tool_call.tool_name,
            )

        return results

    def run_post_hooks(
        self,
        tool_call: ToolCall,
        result: ToolResult,
        context: dict[str, Any],
    ) -> tuple[ToolResult, list[HookResult]]:
        """Run all post_tool_use hooks.

        Post-hooks may request output sanitization. Because ``ToolResult`` is
        frozen, callers must construct a new ``ToolResult`` if a hook returns
        ``HookAction.sanitize`` with a ``sanitized_output`` value.

        Returns
        -------
        tuple[ToolResult, list[HookResult]]
            The (potentially replaced) tool result and all hook results.
        """
        hook_results: list[HookResult] = []
        current_result = result

        for entry in self._post_hooks:
            try:
                hr = _run_with_timeout(
                    entry.handler, (tool_call, current_result, context), entry.timeout
                )
                if not isinstance(hr, HookResult):
                    hr = HookResult(
                        action=HookAction.allow,
                        reason=str(hr),
                    )
                hook_results.append(hr)

                # If a hook requests sanitization, rebuild the ToolResult
                if (
                    hr.action == HookAction.sanitize
                    and hr.sanitized_output is not None
                ):
                    current_result = ToolResult(
                        tool_name=current_result.tool_name,
                        status=current_result.status,
                        output=hr.sanitized_output,
                        error=current_result.error,
                        duration_ms=current_result.duration_ms,
                        sanitized=True,
                        blocked_reason=current_result.blocked_reason,
                    )

            except TimeoutError:
                logger.warning("Post-hook %s timed out after %.1fs", entry.name, entry.timeout)
                hook_results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Hook {entry.name!r} timed out after {entry.timeout}s",
                        severity="warning",
                    )
                )
            except Exception:
                logger.exception("Post-hook %s raised an exception", entry.name)
                hook_results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Hook {entry.name!r} raised an exception (see logs)",
                        severity="warning",
                    )
                )

        # Run shell post-hooks
        for hook_name, shell_hook in self._shell_hooks.get("post_tool_use", []):
            if not shell_hook.matches(tool_call.tool_name):
                continue
            try:
                input_data = {
                    "tool_name": tool_call.tool_name,
                    "tool_input": tool_call.tool_input,
                    "session_id": tool_call.session_id or "",
                    "output": (
                        str(current_result.output)
                        if current_result.output is not None
                        else ""
                    ),
                    "status": current_result.status,
                }
                hr = shell_hook.execute(input_data)
                hook_results.append(hr)
            except Exception:
                logger.exception(
                    "Shell post-hook %s raised an exception", hook_name
                )
                hook_results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Shell hook {hook_name!r} raised an exception (see logs)",
                        severity="warning",
                    )
                )

        return current_result, hook_results

    def run_block_hooks(
        self,
        tool_call: ToolCall,
        decision: PermissionDecision,
        context: dict[str, Any],
    ) -> None:
        """Notify on_block hooks that an action was blocked.

        These hooks are informational — their return values are ignored.
        """
        for entry in self._block_hooks:
            try:
                _run_with_timeout(
                    entry.handler, (tool_call, decision, context), entry.timeout
                )
            except TimeoutError:
                logger.warning("Block hook %s timed out after %.1fs", entry.name, entry.timeout)
            except Exception:
                logger.exception("Block hook %s raised an exception", entry.name)

        # Run shell block hooks
        for hook_name, shell_hook in self._shell_hooks.get("on_block", []):
            if not shell_hook.matches(tool_call.tool_name):
                continue
            try:
                input_data = {
                    "tool_name": tool_call.tool_name,
                    "tool_input": tool_call.tool_input,
                    "session_id": tool_call.session_id or "",
                    "decision": decision.action,
                    "reason": decision.reason,
                }
                shell_hook.execute(input_data)
            except Exception:
                logger.exception(
                    "Shell block hook %s raised an exception", hook_name
                )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def profile(self) -> str:
        """The active profile name."""
        return self._profile

    @property
    def project_root(self) -> str:
        """The resolved project root directory."""
        return self._project_root

    def list_hooks(self) -> dict[str, list[str]]:
        """Return a mapping of event -> list of hook names (callable + shell).

        Includes both tool-use hooks and lifecycle hooks.
        """
        result: dict[str, list[str]] = {
            "pre_tool_use": (
                [entry.name for entry in self._pre_hooks]
                + [name for name, _ in self._shell_hooks.get("pre_tool_use", [])]
            ),
            "post_tool_use": (
                [entry.name for entry in self._post_hooks]
                + [name for name, _ in self._shell_hooks.get("post_tool_use", [])]
            ),
            "on_block": (
                [entry.name for entry in self._block_hooks]
                + [name for name, _ in self._shell_hooks.get("on_block", [])]
            ),
        }
        # Include lifecycle events that have at least one handler
        for event, entries in self._lifecycle_hooks.items():
            if entries:
                result[event] = [entry.name for entry in entries]
        return result

    def __repr__(self) -> str:
        counts = {k: len(v) for k, v in self.list_hooks().items() if v}
        return f"<HookRegistry profile={self._profile!r} hooks={counts}>"
