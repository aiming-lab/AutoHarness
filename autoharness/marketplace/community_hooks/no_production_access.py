"""Block tool calls that target production environments.

Detects production indicators in URLs, file paths, environment variables,
configuration keys, and command arguments. Prevents accidental modification
of production systems by AI agents.

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()
    marketplace.install("no-production-access")

Or register directly::

    from autoharness.core.hooks import HookRegistry
    from autoharness.marketplace.community_hooks.no_production_access import (
        check_production_access,
    )

    registry = HookRegistry()
    registry.register("pre_tool_use", check_production_access)
"""

from __future__ import annotations

import re
from typing import Any

from autoharness.core.hooks import hook
from autoharness.core.types import HookAction, HookResult, RiskAssessment, ToolCall

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

HOOK_METADATA = {
    "name": "no-production-access",
    "description": "Block tool calls targeting production environments",
    "event": "pre_tool_use",
    "author": "AutoHarness Community",
    "version": "1.0.0",
    "tags": ["safety", "production", "environment"],
}

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# URL patterns that indicate production environments
_PROD_URL_PATTERNS = [
    re.compile(r"https?://(?:www\.)?prod(?:uction)?[\.\-]", re.IGNORECASE),
    re.compile(r"https?://[^/]*\.prod\.", re.IGNORECASE),
    re.compile(r"https?://api\.[^/]+\.com(?:/|$)", re.IGNORECASE),
    re.compile(r"https?://[^/]*prod[^/]*\.(?:com|io|net|org)(?:/|$)", re.IGNORECASE),
]

# Environment variable names that indicate production
_PROD_ENV_PATTERNS = [
    re.compile(r"\bPROD(?:UCTION)?_", re.IGNORECASE),
    re.compile(r"_PROD(?:UCTION)?\b", re.IGNORECASE),
    re.compile(r"\bNODE_ENV\s*=\s*['\"]?production['\"]?", re.IGNORECASE),
    re.compile(r"\bRAILS_ENV\s*=\s*['\"]?production['\"]?", re.IGNORECASE),
    re.compile(r"\bENV(?:IRONMENT)?\s*=\s*['\"]?prod(?:uction)?['\"]?", re.IGNORECASE),
    re.compile(r"\bFLASK_ENV\s*=\s*['\"]?production['\"]?", re.IGNORECASE),
    re.compile(r"\bAPP_ENV\s*=\s*['\"]?prod(?:uction)?['\"]?", re.IGNORECASE),
]

# Config keys and file paths indicating production
_PROD_CONFIG_PATTERNS = [
    re.compile(r"prod(?:uction)?\.(?:yml|yaml|json|toml|ini|cfg|conf)", re.IGNORECASE),
    re.compile(r"config[/\\]prod(?:uction)?", re.IGNORECASE),
    re.compile(r"deploy[/\\]prod(?:uction)?", re.IGNORECASE),
    re.compile(r"\.env\.prod(?:uction)?$", re.IGNORECASE),
]

# Command-line arguments indicating production targets
_PROD_CMD_PATTERNS = [
    re.compile(r"--(?:env|environment)\s*[=\s]\s*prod(?:uction)?", re.IGNORECASE),
    re.compile(r"--(?:stage|target)\s*[=\s]\s*prod(?:uction)?", re.IGNORECASE),
    re.compile(r"--prod(?:uction)?\b", re.IGNORECASE),
    re.compile(r"\bdeploy\s+(?:to\s+)?prod(?:uction)?", re.IGNORECASE),
    # Database connection strings with prod indicators
    re.compile(r"(?:mysql|postgres|mongodb|redis)://[^@]*@[^/]*prod", re.IGNORECASE),
]

# All patterns combined for efficient scanning
_ALL_PATTERNS: list[tuple[str, re.Pattern[str]]] = (
    [("production URL", p) for p in _PROD_URL_PATTERNS]
    + [("production environment variable", p) for p in _PROD_ENV_PATTERNS]
    + [("production config file", p) for p in _PROD_CONFIG_PATTERNS]
    + [("production command argument", p) for p in _PROD_CMD_PATTERNS]
)


# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------


def _collect_text(tool_call: ToolCall) -> str:
    """Collect all scannable text from a tool call's inputs."""
    parts: list[str] = []
    for val in tool_call.tool_input.values():
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, dict):
            for nested_val in val.values():
                if isinstance(nested_val, str):
                    parts.append(nested_val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
    return "\n".join(parts)


@hook("pre_tool_use", name="no_production_access")
def check_production_access(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict[str, Any],
) -> HookResult:
    """Block any tool call that targets a production environment.

    Scans all string values in the tool call's input for patterns that
    indicate production environments: URLs, environment variables,
    config file paths, and command arguments.

    Parameters
    ----------
    tool_call : ToolCall
        The incoming tool call to check.
    risk : RiskAssessment
        Pre-computed risk assessment (not used by this hook).
    context : dict
        Additional context (not used by this hook).

    Returns
    -------
    HookResult
        Deny if production indicators are found, allow otherwise.
    """
    text = _collect_text(tool_call)
    if not text.strip():
        return HookResult(action=HookAction.allow)

    for description, pattern in _ALL_PATTERNS:
        match = pattern.search(text)
        if match:
            matched_text = match.group(0)
            # Truncate for safety
            display = matched_text[:60] + "..." if len(matched_text) > 60 else matched_text
            return HookResult(
                action=HookAction.deny,
                reason=(
                    f"Production environment access blocked: {description} "
                    f"detected ({display!r}). Use a staging or development "
                    f"environment instead."
                ),
                severity="error",
            )

    return HookResult(action=HookAction.allow)
