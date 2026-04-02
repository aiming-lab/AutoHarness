"""Feature flag system — runtime capability toggles.

Provides compile-time and runtime feature flags with environment
variable overrides. Flags follow the pattern AUTOHARNESS_FF_<NAME>.

Example::

    flags = FeatureFlags.from_env()
    if flags.is_enabled("ANTI_DISTILLATION"):
        tools = inject_decoys(tools, count=3)
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default flag values — True means enabled by default
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, bool] = {
    "ANTI_DISTILLATION": False,
    "FRUSTRATION_DETECTION": False,
    "MODEL_ROUTING": False,
    "SWARM_MODE": False,
    "COORDINATOR_MODE": True,
}

_ENV_PREFIX = "AUTOHARNESS_FF_"


# ---------------------------------------------------------------------------
# FeatureFlags (singleton)
# ---------------------------------------------------------------------------


@dataclass
class FeatureFlags:
    """Runtime feature flag store with env-var overrides.

    Thread-safe singleton. Reads ``AUTOHARNESS_FF_<NAME>`` environment
    variables at construction time; individual flags can be toggled at
    runtime via :meth:`set`.
    """

    _flags: dict[str, bool] = field(default_factory=lambda: dict(_DEFAULTS))
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False
    )

    # -- Singleton plumbing --------------------------------------------------

    _instance: ClassVar[FeatureFlags | None] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def instance(cls) -> FeatureFlags:
        """Return the global singleton, creating it on first call."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls.from_env()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (mainly for tests)."""
        with cls._instance_lock:
            cls._instance = None

    # -- Factory -------------------------------------------------------------

    @classmethod
    def from_env(cls) -> FeatureFlags:
        """Create a :class:`FeatureFlags` with defaults merged with env vars.

        Environment variables are read as ``AUTOHARNESS_FF_<NAME>``.
        Truthy values: ``1``, ``true``, ``yes`` (case-insensitive).
        """
        flags = dict(_DEFAULTS)
        for key, _default in _DEFAULTS.items():
            env_val = os.environ.get(f"{_ENV_PREFIX}{key}")
            if env_val is not None:
                flags[key] = env_val.strip().lower() in ("1", "true", "yes")
                logger.debug("Feature flag %s overridden to %s via env", key, flags[key])
        return cls(_flags=flags)

    # -- Public API ----------------------------------------------------------

    def is_enabled(self, flag: str) -> bool:
        """Return whether *flag* is currently enabled.

        Args:
            flag: Flag name (e.g. ``"ANTI_DISTILLATION"``).

        Returns:
            ``True`` if the flag is enabled, ``False`` if disabled or unknown.
        """
        with self._lock:
            enabled = self._flags.get(flag, False)
        return enabled

    def set(self, flag: str, enabled: bool) -> None:
        """Set *flag* to *enabled* at runtime.

        Args:
            flag: Flag name.
            enabled: Whether the flag should be on.
        """
        with self._lock:
            self._flags[flag] = enabled
        logger.info("Feature flag %s set to %s", flag, enabled)

    def all_flags(self) -> dict[str, bool]:
        """Return a snapshot of all current flag values."""
        with self._lock:
            return dict(self._flags)
