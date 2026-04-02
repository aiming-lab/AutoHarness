"""Restrict agent actions to configurable working hours.

Blocks or warns when tool calls are made outside of defined working hours.
Useful for preventing unattended agent operations during nights or weekends.

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()
    marketplace.install("working-hours")

Or register directly::

    from autoharness.core.hooks import HookRegistry
    from autoharness.marketplace.community_hooks.working_hours import check_working_hours

    registry = HookRegistry()
    registry.register("pre_tool_use", check_working_hours)

Configuration via environment variables:
    AUTOHARNESS_WORK_START: Start hour in 24h format (default: 9)
    AUTOHARNESS_WORK_END: End hour in 24h format (default: 18)
    AUTOHARNESS_WORK_TIMEZONE: Timezone name (default: UTC)
    AUTOHARNESS_WORK_DAYS: Comma-separated weekday numbers, 0=Mon (default: 0,1,2,3,4)
    AUTOHARNESS_WORK_MODE: "deny" to block, "warn" to allow with warning (default: warn)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from autoharness.core.hooks import hook
from autoharness.core.types import HookAction, HookResult, RiskAssessment, ToolCall

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

HOOK_METADATA = {
    "name": "working-hours",
    "description": "Restrict agent actions to configurable working hours",
    "event": "pre_tool_use",
    "author": "AutoHarness Community",
    "version": "1.0.0",
    "tags": ["scheduling", "safety", "working-hours"],
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _get_int_env(key: str, default: int) -> int:
    """Read an integer from an environment variable with a fallback."""
    raw = os.environ.get(key, "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid int for %s: %r, using default %d", key, raw, default)
    return default


def _get_timezone() -> ZoneInfo | timezone:
    """Get the configured timezone."""
    tz_name = os.environ.get("AUTOHARNESS_WORK_TIMEZONE", "UTC")
    if tz_name == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "Unknown timezone %r, falling back to UTC. "
            "Use a valid IANA timezone name (e.g., 'America/New_York').",
            tz_name,
        )
        return timezone.utc


def _get_work_days() -> set[int]:
    """Get configured working days as a set of weekday numbers (0=Monday)."""
    raw = os.environ.get("AUTOHARNESS_WORK_DAYS", "0,1,2,3,4")
    try:
        return {int(d.strip()) for d in raw.split(",") if d.strip()}
    except ValueError:
        logger.warning(
            "Invalid AUTOHARNESS_WORK_DAYS: %r, using default Mon-Fri", raw
        )
        return {0, 1, 2, 3, 4}


# Working hours configuration
_WORK_START = _get_int_env("AUTOHARNESS_WORK_START", 9)
_WORK_END = _get_int_env("AUTOHARNESS_WORK_END", 18)
_WORK_TZ = _get_timezone()
_WORK_DAYS = _get_work_days()
_WORK_MODE = os.environ.get("AUTOHARNESS_WORK_MODE", "warn").lower()

# Day name mapping for readable messages
_DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def is_within_working_hours(dt: datetime | None = None) -> tuple[bool, str]:
    """Check if the given datetime falls within working hours.

    Parameters
    ----------
    dt : datetime | None
        The datetime to check. If None, uses the current time.

    Returns
    -------
    tuple[bool, str]
        (is_within, reason_if_not)
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    # Convert to configured timezone
    local_dt = dt.astimezone(_WORK_TZ)
    current_hour = local_dt.hour
    current_day = local_dt.weekday()
    day_name = _DAY_NAMES.get(current_day, str(current_day))

    tz_name = os.environ.get("AUTOHARNESS_WORK_TIMEZONE", "UTC")

    # Check if it's a working day
    if current_day not in _WORK_DAYS:
        working_day_names = sorted(
            [_DAY_NAMES[d] for d in _WORK_DAYS], key=lambda x: list(_DAY_NAMES.values()).index(x)
        )
        return False, (
            f"Outside working days: {day_name} is not a working day. "
            f"Working days: {', '.join(working_day_names)} ({tz_name})."
        )

    # Check if it's within working hours
    if not (_WORK_START <= current_hour < _WORK_END):
        return False, (
            f"Outside working hours: current time is {local_dt.strftime('%H:%M')} {tz_name}. "
            f"Working hours: {_WORK_START:02d}:00-{_WORK_END:02d}:00."
        )

    return True, ""


# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------


@hook("pre_tool_use", name="working_hours")
def check_working_hours(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict[str, Any],
) -> HookResult:
    """Check if the current time is within configured working hours.

    Outside working hours, the hook either warns or denies tool calls
    depending on the ``AUTOHARNESS_WORK_MODE`` setting.

    Read-only tool calls (Read, Glob, Grep, search) are always allowed
    regardless of working hours.

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
        Allow during working hours; warn or deny outside of them.
    """
    # Allow read-only operations regardless of time
    read_only_tools = {
        "Read", "Glob", "Grep", "Search", "WebSearch", "WebFetch",
        "file_read", "search", "list_files",
    }
    if tool_call.tool_name in read_only_tools:
        return HookResult(action=HookAction.allow)

    within, reason = is_within_working_hours()

    if within:
        return HookResult(action=HookAction.allow)

    if _WORK_MODE == "deny":
        return HookResult(
            action=HookAction.deny,
            reason=f"Tool call blocked: {reason}",
            severity="error",
        )

    # Default: warn but allow
    return HookResult(
        action=HookAction.allow,
        reason=f"Working hours warning: {reason}",
        severity="warning",
    )
