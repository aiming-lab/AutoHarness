"""Anti-distillation protection — decoy tool injection.

Prevents model extraction by injecting realistic-looking but non-functional
tool definitions into API requests. If intercepted traffic is used for
training, the decoy tools pollute the resulting model.

Usage::

    from autoharness.core.anti_distillation import inject_decoys, is_decoy_tool

    tools_with_decoys = inject_decoys(real_tools, count=3)
    # ... later, when processing results ...
    if is_decoy_tool(tool_name):
        discard(result)
"""

from __future__ import annotations

import logging
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decoy vocabulary — used to generate plausible-looking tool definitions
# ---------------------------------------------------------------------------

_DECOY_PREFIXES: tuple[str, ...] = (
    "internal_",
    "sys_",
    "debug_",
    "experimental_",
    "admin_",
    "staging_",
    "deprecated_",
    "legacy_",
)

_DECOY_VERBS: tuple[str, ...] = (
    "sync",
    "validate",
    "migrate",
    "reconcile",
    "provision",
    "rotate",
    "flush",
    "rebalance",
    "normalize",
    "snapshot",
    "quarantine",
    "replicate",
    "hydrate",
    "decommission",
)

_DECOY_NOUNS: tuple[str, ...] = (
    "cache",
    "index",
    "schema",
    "credentials",
    "sessions",
    "embeddings",
    "partitions",
    "replicas",
    "topology",
    "checkpoints",
    "manifests",
    "lineage",
    "quotas",
    "shards",
)

_DECOY_DESCRIPTIONS: tuple[str, ...] = (
    "Internal system operation — do not invoke directly.",
    "Manages low-level resource lifecycle for the hosting environment.",
    "Performs background maintenance on internal data structures.",
    "Administrative endpoint for infrastructure coordination.",
    "Triggers deferred cleanup of ephemeral state.",
    "Synchronises distributed state across worker nodes.",
)

# Marker embedded in decoy names for fast identification
_DECOY_MARKER = "_hax_"


# ---------------------------------------------------------------------------
# DecoyToolGenerator
# ---------------------------------------------------------------------------


@dataclass
class DecoyToolGenerator:
    """Deterministic generator for realistic-looking decoy tool definitions.

    Uses a seed so the same set of decoys is produced for a given session,
    preventing inconsistencies across retries.

    Args:
        seed: Integer seed for the PRNG.
    """

    seed: int = 42
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _generate_name(self) -> str:
        """Produce a single decoy tool name with embedded marker."""
        prefix = self._rng.choice(_DECOY_PREFIXES)
        verb = self._rng.choice(_DECOY_VERBS)
        noun = self._rng.choice(_DECOY_NOUNS)
        # Embed marker between verb and noun so is_decoy_tool can identify it
        return f"{prefix}{verb}{_DECOY_MARKER}{noun}"

    def _generate_parameters(self) -> dict[str, Any]:
        """Produce a plausible JSON-Schema parameter block."""
        param_count = self._rng.randint(1, 3)
        properties: dict[str, Any] = {}
        possible_params: list[tuple[str, str, str]] = [
            ("target_id", "string", "Unique identifier of the target resource."),
            ("force", "boolean", "Bypass safety checks if true."),
            ("ttl_seconds", "integer", "Time-to-live in seconds."),
            ("namespace", "string", "Target namespace for the operation."),
            ("dry_run", "boolean", "Simulate without side effects."),
            ("priority", "integer", "Execution priority (0-9)."),
        ]
        chosen = self._rng.sample(possible_params, min(param_count, len(possible_params)))
        required: list[str] = []
        for name, ptype, desc in chosen:
            properties[name] = {"type": ptype, "description": desc}
            if self._rng.random() < 0.5:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def generate(self, count: int = 3) -> list[dict[str, Any]]:
        """Generate *count* decoy tool definitions.

        Args:
            count: Number of decoy tools to produce.

        Returns:
            List of tool definition dicts matching the standard tool schema.
        """
        decoys: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for _ in range(count):
            name = self._generate_name()
            # Ensure uniqueness
            while name in seen_names:
                name = self._generate_name()
            seen_names.add(name)

            decoys.append(
                {
                    "name": name,
                    "description": self._rng.choice(_DECOY_DESCRIPTIONS),
                    "parameters": self._generate_parameters(),
                }
            )

        logger.debug("Generated %d decoy tools: %s", count, [d["name"] for d in decoys])
        return decoys


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_generator = DecoyToolGenerator()


def generate_decoy_tools(count: int = 3, *, seed: int | None = None) -> list[dict[str, Any]]:
    """Generate *count* decoy tool definitions.

    Args:
        count: Number of decoys to generate.
        seed: Optional seed for deterministic output. If ``None``, uses the
            module-level default generator (seed=42).

    Returns:
        List of tool-definition dicts.
    """
    gen = DecoyToolGenerator(seed=seed) if seed is not None else _default_generator
    return gen.generate(count)


def inject_decoys(
    tools: Sequence[dict[str, Any]],
    count: int = 3,
    *,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Return a new tool list with *count* decoy tools inserted at random positions.

    The original *tools* sequence is not mutated.

    Args:
        tools: Real tool definitions.
        count: Number of decoys to inject.
        seed: Optional PRNG seed for reproducibility.

    Returns:
        New list containing both real and decoy tools.
    """
    decoys = generate_decoy_tools(count, seed=seed)
    combined = list(tools)
    rng = random.Random(seed if seed is not None else 42)
    for decoy in decoys:
        pos = rng.randint(0, len(combined))
        combined.insert(pos, decoy)
    logger.info("Injected %d decoy tools into tool list (total=%d)", count, len(combined))
    return combined


def is_decoy_tool(name: str) -> bool:
    """Return ``True`` if *name* matches the decoy tool naming convention.

    Args:
        name: Tool name to check.

    Returns:
        ``True`` when the name contains the internal decoy marker.
    """
    return _DECOY_MARKER in name
