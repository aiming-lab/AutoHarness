"""Hook profile system — minimal/standard/strict gating.

Environment variables:
  AUTOHARNESS_HOOK_PROFILE=standard    # minimal|standard|strict
  AUTOHARNESS_DISABLED_HOOKS=id1,id2   # comma-separated hook IDs
"""
from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger(__name__)

HookProfile = Literal["minimal", "standard", "strict"]

PROFILE_LEVELS: dict[HookProfile, int] = {
    "minimal": 1,
    "standard": 2,
    "strict": 3,
}

def get_hook_profile() -> HookProfile:
    """Get the current hook profile from environment."""
    raw = os.environ.get("AUTOHARNESS_HOOK_PROFILE", "standard").lower().strip()
    if raw in PROFILE_LEVELS:
        return raw  # type: ignore
    logger.warning("Unknown hook profile '%s', defaulting to 'standard'", raw)
    return "standard"

def get_disabled_hooks() -> set[str]:
    """Get the set of disabled hook IDs from environment."""
    raw = os.environ.get("AUTOHARNESS_DISABLED_HOOKS", "")
    if not raw.strip():
        return set()
    return {h.strip() for h in raw.split(",") if h.strip()}

def is_hook_enabled(
    hook_id: str,
    required_profile: HookProfile = "standard",
    profile: HookProfile | None = None,
    disabled: set[str] | None = None,
) -> bool:
    """Check if a hook should run given current profile and disabled set."""
    if profile is None:
        profile = get_hook_profile()
    if disabled is None:
        disabled = get_disabled_hooks()

    if hook_id in disabled:
        return False

    current_level = PROFILE_LEVELS.get(profile, 2)
    required_level = PROFILE_LEVELS.get(required_profile, 2)

    return current_level >= required_level

# Config protection patterns
CONFIG_PROTECTION_FILES = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yaml",
    ".prettierrc", ".prettierrc.js", ".prettierrc.json",
    "tsconfig.json", "tsconfig.build.json",
    ".flake8", "setup.cfg",  # Python linters
}

def is_config_protected(file_path: str) -> bool:
    """Check if a file path is a protected config file."""
    from pathlib import PurePosixPath
    name = PurePosixPath(file_path).name
    return name in CONFIG_PROTECTION_FILES
