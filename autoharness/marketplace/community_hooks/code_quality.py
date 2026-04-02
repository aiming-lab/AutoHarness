"""Block commits containing debug statements, console.log, or TODO/FIXME markers.

Scans tool call inputs (file writes, edits, and git commits) for common
code quality issues that should not be committed to version control:
- console.log / console.debug / console.warn / console.error
- debugger statements
- print() used for debugging (heuristic)
- TODO / FIXME / HACK / XXX comments in newly added code
- Commented-out code blocks

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()
    marketplace.install("code-quality")

Or register directly::

    from autoharness.core.hooks import HookRegistry
    from autoharness.marketplace.community_hooks.code_quality import check_code_quality

    registry = HookRegistry()
    registry.register("pre_tool_use", check_code_quality)

Configuration via environment variables:
    AUTOHARNESS_CODE_QUALITY_MODE: "deny" to block, "warn" to allow with warning (default: warn)
    AUTOHARNESS_CODE_QUALITY_SKIP_TOOLS: Comma-separated tool names to skip (default: "")
    AUTOHARNESS_CODE_QUALITY_ALLOW_TODO: Set to "true" to allow TODO/FIXME (default: false)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from autoharness.core.hooks import hook
from autoharness.core.types import HookAction, HookResult, RiskAssessment, ToolCall

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

HOOK_METADATA = {
    "name": "code-quality",
    "description": "Block commits containing console.log, debugger statements, or TODO/FIXME",
    "event": "pre_tool_use",
    "author": "AutoHarness Community",
    "version": "1.0.0",
    "tags": ["code-quality", "linting", "debugging"],
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MODE = os.environ.get("AUTOHARNESS_CODE_QUALITY_MODE", "warn").lower()

_SKIP_TOOLS = {
    t.strip()
    for t in os.environ.get("AUTOHARNESS_CODE_QUALITY_SKIP_TOOLS", "").split(",")
    if t.strip()
}

_ALLOW_TODO = os.environ.get(
    "AUTOHARNESS_CODE_QUALITY_ALLOW_TODO", "false"
).lower() == "true"

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# JavaScript/TypeScript console methods
_CONSOLE_LOG_RE = re.compile(
    r"\bconsole\s*\.\s*(?:log|debug|warn|error|info|trace|dir|table)\s*\(",
    re.MULTILINE,
)

# JavaScript/TypeScript debugger statement
_DEBUGGER_RE = re.compile(
    r"^\s*debugger\s*;?\s*$",
    re.MULTILINE,
)

# Python print used for debugging (heuristic: standalone print with debug-like content)
_PYTHON_DEBUG_PRINT_RE = re.compile(
    r"^\s*print\s*\(\s*(?:f?['\"](?:DEBUG|debug|>>>|---|\*\*\*|===|###))",
    re.MULTILINE,
)

# Python breakpoint / pdb
_PYTHON_DEBUGGER_RE = re.compile(
    r"^\s*(?:breakpoint\s*\(\)|import\s+pdb|pdb\s*\.\s*set_trace\s*\(\))",
    re.MULTILINE,
)

# Ruby debugging
_RUBY_DEBUG_RE = re.compile(
    r"^\s*(?:binding\.pry|byebug|debugger)\s*$",
    re.MULTILINE,
)

# TODO / FIXME / HACK / XXX markers
_TODO_RE = re.compile(
    r"(?:#|//|/\*|\*)\s*(?:TODO|FIXME|HACK|XXX)\b",
    re.MULTILINE | re.IGNORECASE,
)

# Large blocks of commented-out code (3+ consecutive comment lines that look like code)
_COMMENTED_CODE_RE = re.compile(
    r"(?:^\s*(?://|#)\s*(?:if|for|while|def|class|function|return|import|const|let|var)\b.*\n){3,}",
    re.MULTILINE,
)

# All patterns with descriptions
_QUALITY_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "console.log/debug statement", _CONSOLE_LOG_RE,
        "Remove console.log() calls before committing",
    ),
    ("debugger statement (JS/TS)", _DEBUGGER_RE, "Remove 'debugger' statements before committing"),
    (
        "debug print (Python)", _PYTHON_DEBUG_PRINT_RE,
        "Remove debug print() calls before committing",
    ),
    (
        "Python debugger/breakpoint", _PYTHON_DEBUGGER_RE,
        "Remove breakpoint()/pdb calls before committing",
    ),
    ("Ruby debugger", _RUBY_DEBUG_RE, "Remove binding.pry/byebug before committing"),
    (
        "commented-out code block", _COMMENTED_CODE_RE,
        "Remove commented-out code blocks before committing",
    ),
]

# TODO pattern handled separately due to config flag
_TODO_PATTERN = ("TODO/FIXME marker", _TODO_RE, "Resolve TODO/FIXME comments before committing")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

# Tools that write or modify code
_WRITE_TOOLS = {
    "Edit", "Write", "file_write", "file_edit",
    "Bash",  # Can write via shell
}


def _extract_content(tool_call: ToolCall) -> str | None:
    """Extract writable content from a tool call.

    Returns the text that will be written/committed, or None if the
    tool call does not write code.
    """
    tool = tool_call.tool_name

    if tool in ("Edit", "file_edit"):
        val: Any = tool_call.tool_input.get("new_string", "")
        return str(val) if val else None

    if tool in ("Write", "file_write"):
        val = tool_call.tool_input.get("content", "")
        return str(val) if val else None

    if tool == "Bash":
        cmd = tool_call.tool_input.get("command", "")
        if isinstance(cmd, str):
            # Check if it's a git commit (we scan the diff context if available)
            if "git commit" in cmd or "git add" in cmd:
                return cmd
            # Check for file writes via shell (echo, cat, tee)
            if any(op in cmd for op in (">>", "> ", "tee ", "cat <<", "cat >")):
                return cmd
        return None

    return None


def _get_file_extension(tool_call: ToolCall) -> str:
    """Determine the file extension from the tool call, if possible."""
    for key in ("file_path", "path", "file"):
        path = tool_call.tool_input.get(key, "")
        if isinstance(path, str) and "." in path:
            return path.rsplit(".", 1)[-1].lower()
    return ""


# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------


@hook("pre_tool_use", name="code_quality")
def check_code_quality(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict[str, Any],
) -> HookResult:
    """Scan tool call content for code quality issues.

    Checks file writes, edits, and git operations for debug statements,
    console.log calls, and TODO/FIXME markers that should not be committed.

    Parameters
    ----------
    tool_call : ToolCall
        The incoming tool call.
    risk : RiskAssessment
        Pre-computed risk assessment (not used by this hook).
    context : dict
        Additional context (not used by this hook).

    Returns
    -------
    HookResult
        Deny or warn if quality issues found, allow otherwise.
    """
    # Skip tools that don't write code
    if tool_call.tool_name not in _WRITE_TOOLS:
        return HookResult(action=HookAction.allow)

    # Skip explicitly excluded tools
    if tool_call.tool_name in _SKIP_TOOLS:
        return HookResult(action=HookAction.allow)

    content = _extract_content(tool_call)
    if not content or not content.strip():
        return HookResult(action=HookAction.allow)

    # Skip non-code files (markdown, yaml, json, etc.)
    ext = _get_file_extension(tool_call)
    non_code_extensions = {
        "md", "markdown", "txt", "yaml", "yml", "json", "toml",
        "ini", "cfg", "conf", "csv", "xml", "html", "css", "svg",
        "lock", "sum",
    }
    if ext in non_code_extensions:
        return HookResult(action=HookAction.allow)

    # Collect all findings
    findings: list[str] = []

    for description, pattern, suggestion in _QUALITY_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            count = len(matches)
            findings.append(
                f"{description} ({count} occurrence"
                f"{'s' if count > 1 else ''}): {suggestion}"
            )

    # Check TODO/FIXME separately (configurable)
    if not _ALLOW_TODO:
        description, pattern, suggestion = _TODO_PATTERN
        matches = pattern.findall(content)
        if matches:
            count = len(matches)
            findings.append(
                f"{description} ({count} occurrence"
                f"{'s' if count > 1 else ''}): {suggestion}"
            )

    if not findings:
        return HookResult(action=HookAction.allow)

    # Build the result message
    findings_text = "; ".join(findings)

    if _MODE == "deny":
        return HookResult(
            action=HookAction.deny,
            reason=f"Code quality issues found: {findings_text}",
            severity="error",
        )

    # Default: warn but allow
    return HookResult(
        action=HookAction.allow,
        reason=f"Code quality warnings: {findings_text}",
        severity="warning",
    )
