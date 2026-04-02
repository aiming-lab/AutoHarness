"""Enhanced git safety rules for AI agents.

Enforces git best practices by blocking dangerous operations:
- No force push (especially to main/master)
- No push directly to main/master
- Branch naming convention enforcement
- No destructive resets on shared branches
- No deletion of protected branches

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()
    marketplace.install("git-safety")

Or register directly::

    from autoharness.core.hooks import HookRegistry
    from autoharness.marketplace.community_hooks.git_safety import check_git_safety

    registry = HookRegistry()
    registry.register("pre_tool_use", check_git_safety)

Configuration via environment variables:
    AUTOHARNESS_GIT_PROTECTED_BRANCHES: Comma-separated branch names (default: main,master,develop)
    AUTOHARNESS_GIT_BRANCH_PATTERN: Regex for valid branch names
        (default: ^(feat|fix|chore|docs|refactor|test|ci)/[a-z0-9._-]+$)
    AUTOHARNESS_GIT_ALLOW_FORCE_PUSH: Set to "true" to allow force push (default: false)
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
    "name": "git-safety",
    "description": "Enhanced git safety: no force push, branch protection, naming conventions",
    "event": "pre_tool_use",
    "author": "AutoHarness Community",
    "version": "1.0.0",
    "tags": ["git", "safety", "version-control"],
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PROTECTED_BRANCHES = {
    b.strip()
    for b in os.environ.get(
        "AUTOHARNESS_GIT_PROTECTED_BRANCHES", "main,master,develop"
    ).split(",")
    if b.strip()
}

_BRANCH_PATTERN_STR = os.environ.get(
    "AUTOHARNESS_GIT_BRANCH_PATTERN",
    r"^(feat|fix|chore|docs|refactor|test|ci)/[a-z0-9._-]+$",
)
try:
    _BRANCH_PATTERN = re.compile(_BRANCH_PATTERN_STR)
except re.error:
    logger.warning(
        "Invalid AUTOHARNESS_GIT_BRANCH_PATTERN: %r, using default",
        _BRANCH_PATTERN_STR,
    )
    _BRANCH_PATTERN = re.compile(
        r"^(feat|fix|chore|docs|refactor|test|ci)/[a-z0-9._-]+$"
    )

_ALLOW_FORCE_PUSH = os.environ.get(
    "AUTOHARNESS_GIT_ALLOW_FORCE_PUSH", "false"
).lower() == "true"

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Force push patterns
_FORCE_PUSH_RE = re.compile(
    r"git\s+push\s+.*(?:--force|-f)(?:\s|$)", re.IGNORECASE
)
_FORCE_PUSH_LEASE_RE = re.compile(
    r"git\s+push\s+.*--force-with-lease", re.IGNORECASE
)

# Push to protected branch
_PUSH_BRANCH_RE = re.compile(
    r"git\s+push\s+(?:\S+\s+)?(\S+?)(?:\s|:|$)", re.IGNORECASE
)

# Hard reset
_HARD_RESET_RE = re.compile(
    r"git\s+reset\s+--hard", re.IGNORECASE
)

# Branch deletion
_BRANCH_DELETE_RE = re.compile(
    r"git\s+branch\s+(?:-[dD]|--delete)\s+(\S+)", re.IGNORECASE
)

# Push delete (remote branch deletion)
_PUSH_DELETE_RE = re.compile(
    r"git\s+push\s+\S+\s+--delete\s+(\S+)", re.IGNORECASE
)
_PUSH_COLON_RE = re.compile(
    r"git\s+push\s+\S+\s+:(\S+)", re.IGNORECASE
)

# Checkout/switch to create new branch
_CHECKOUT_NEW_RE = re.compile(
    r"git\s+(?:checkout|switch)\s+(?:-b|-c|--create)\s+(\S+)", re.IGNORECASE
)

# Clean with force
_CLEAN_FORCE_RE = re.compile(
    r"git\s+clean\s+.*-f", re.IGNORECASE
)

# Rebase onto protected branch
_REBASE_RE = re.compile(
    r"git\s+rebase\s+(?:--onto\s+)?(\S+)", re.IGNORECASE
)


def _extract_command(tool_call: ToolCall) -> str | None:
    """Extract the command string from a tool call, if it's a shell command."""
    # Check common tool names for shell-like tools
    shell_tools = {"Bash", "bash", "shell", "terminal", "command", "exec"}
    if tool_call.tool_name not in shell_tools:
        return None

    cmd = tool_call.tool_input.get("command", "")
    if isinstance(cmd, str) and cmd.strip():
        return cmd

    return None


def _is_protected_branch(branch_name: str) -> bool:
    """Check if a branch name matches any protected branch."""
    # Strip refs prefix
    clean = branch_name.strip()
    for prefix in ("refs/heads/", "origin/", "upstream/"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]

    return clean in _PROTECTED_BRANCHES


# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------


@hook("pre_tool_use", name="git_safety")
def check_git_safety(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict[str, Any],
) -> HookResult:
    """Enforce git safety rules on shell commands.

    Checks for:
    1. Force push (blocked unless --force-with-lease or explicitly allowed)
    2. Push to protected branches (main, master, develop)
    3. Hard reset (blocked — use soft reset or revert instead)
    4. Deletion of protected branches
    5. Branch naming conventions on new branches
    6. git clean -f (dangerous file deletion)

    Parameters
    ----------
    tool_call : ToolCall
        The incoming tool call.
    risk : RiskAssessment
        Pre-computed risk assessment.
    context : dict
        Additional context.

    Returns
    -------
    HookResult
        Deny for dangerous git operations, allow otherwise.
    """
    cmd = _extract_command(tool_call)
    if cmd is None:
        return HookResult(action=HookAction.allow)

    # Only analyze git commands
    if "git " not in cmd and not cmd.strip().startswith("git"):
        return HookResult(action=HookAction.allow)

    # 1. Force push check
    if _FORCE_PUSH_RE.search(cmd) and not _ALLOW_FORCE_PUSH:
        # Allow --force-with-lease as a safer alternative
        if _FORCE_PUSH_LEASE_RE.search(cmd):
            return HookResult(
                action=HookAction.allow,
                reason="Force push with --force-with-lease allowed (safer alternative)",
                severity="warning",
            )
        return HookResult(
            action=HookAction.deny,
            reason=(
                "Force push blocked. Use --force-with-lease for a safer "
                "alternative, or set AUTOHARNESS_GIT_ALLOW_FORCE_PUSH=true "
                "to override."
            ),
            severity="error",
        )

    # 2. Push to protected branches
    push_match = _PUSH_BRANCH_RE.search(cmd)
    if push_match and "push" in cmd:
        target_branch = push_match.group(1)
        if _is_protected_branch(target_branch):
            # Check if this is a force push to a protected branch (extra dangerous)
            if _FORCE_PUSH_RE.search(cmd):
                return HookResult(
                    action=HookAction.deny,
                    reason=(
                        f"Force push to protected branch {target_branch!r} "
                        f"is strictly forbidden. Create a pull request instead."
                    ),
                    severity="error",
                )
            return HookResult(
                action=HookAction.ask,
                reason=(
                    f"Direct push to protected branch {target_branch!r}. "
                    f"Consider using a feature branch and pull request instead."
                ),
                severity="warning",
            )

    # 3. Hard reset
    if _HARD_RESET_RE.search(cmd):
        return HookResult(
            action=HookAction.deny,
            reason=(
                "git reset --hard blocked. This discards uncommitted changes "
                "irreversibly. Use 'git stash' or 'git reset --soft' instead."
            ),
            severity="error",
        )

    # 4. Branch deletion of protected branches
    for pattern in (_BRANCH_DELETE_RE, _PUSH_DELETE_RE, _PUSH_COLON_RE):
        match = pattern.search(cmd)
        if match:
            branch = match.group(1)
            if _is_protected_branch(branch):
                return HookResult(
                    action=HookAction.deny,
                    reason=(
                        f"Deletion of protected branch {branch!r} is forbidden. "
                        f"Protected branches: {', '.join(sorted(_PROTECTED_BRANCHES))}."
                    ),
                    severity="error",
                )

    # 5. Branch naming convention on new branches
    new_branch_match = _CHECKOUT_NEW_RE.search(cmd)
    if new_branch_match:
        branch_name = new_branch_match.group(1)
        if not _BRANCH_PATTERN.match(branch_name):
            return HookResult(
                action=HookAction.allow,
                reason=(
                    f"Branch name {branch_name!r} does not follow the naming "
                    f"convention: {_BRANCH_PATTERN_STR}. Consider renaming."
                ),
                severity="warning",
            )

    # 6. git clean -f
    if _CLEAN_FORCE_RE.search(cmd):
        return HookResult(
            action=HookAction.ask,
            reason=(
                "git clean -f permanently deletes untracked files. "
                "Run 'git clean -n' first to preview what will be removed."
            ),
            severity="warning",
        )

    return HookResult(action=HookAction.allow)
