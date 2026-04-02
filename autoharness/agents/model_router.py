"""Intelligent model routing — cost-optimal model selection.

Routes tasks to the most appropriate model tier based on estimated
complexity, reducing costs while maintaining quality.

Usage::

    router = ModelRouter()
    model_id = router.route("Search for files matching *.py", provider="anthropic")
    # -> "claude-3-5-haiku-latest"

    model_id = router.route("Design a microservice architecture for ...", provider="anthropic")
    # -> "claude-opus-4-0520"
"""

from __future__ import annotations

import logging
import re
from enum import IntEnum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------


class ModelTier(IntEnum):
    """Model capability tiers, ordered by cost/capability."""

    FAST = 1       # Haiku-class — search, simple edits, docs
    STANDARD = 2   # Sonnet-class — most coding tasks
    PREMIUM = 3    # Opus-class — architecture, security, complex debugging


# ---------------------------------------------------------------------------
# Model maps — tier -> model ID per provider
# ---------------------------------------------------------------------------

MODEL_MAP: dict[str, dict[ModelTier, str]] = {
    "anthropic": {
        ModelTier.FAST: "claude-3-5-haiku-latest",
        ModelTier.STANDARD: "claude-sonnet-4-20250514",
        ModelTier.PREMIUM: "claude-opus-4-0520",
    },
    "openai": {
        ModelTier.FAST: "gpt-4o-mini",
        ModelTier.STANDARD: "gpt-4o",
        ModelTier.PREMIUM: "o3",
    },
}

# ---------------------------------------------------------------------------
# Complexity keyword heuristics
# ---------------------------------------------------------------------------

_PREMIUM_PATTERNS: frozenset[str] = frozenset(
    {
        r"\barchitect(ure)?\b",
        r"\bdesign\s+(system|pattern|decision|database|schema|api)\b",
        r"\b(database|db)\s+schema\b",
        r"\bschema\s+design\b",
        r"\bsecurity\s+(audit|review|analy)\w*\b",
        r"\bthreat\s+model\b",
        r"\brefactor\s+(entire|whole|complete)\b",
        r"\bcomplex\s+debug\b",
        r"\broot\s+cause\s+analy\w*\b",
        r"\bplanning\b",
        r"\bstrategic\b",
        r"\bmigration\b",
        r"\bperformance\s+optimi[sz]\w*\b",
    }
)

_FAST_PATTERNS: frozenset[str] = frozenset(
    {
        r"\bsearch\b",
        r"\bfind\s+(file|function|class|import)\w*\b",
        r"\blist\b",
        r"\blook\s*up\b",
        r"\bread\s+(file|content)\b",
        r"\bformat\b",
        r"\brename\b",
        r"\bsummar(y|i[sz]e)\b",
        r"\btranslat(e|ion)\b",
        r"\btypo\b",
        r"\bspelling\b",
        r"\bsimple\s+(fix|change|edit|update)\b",
    }
)

_COMPILED_PREMIUM: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _PREMIUM_PATTERNS
)

_COMPILED_FAST: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _FAST_PATTERNS
)

# Length thresholds (character count)
_LONG_TASK_THRESHOLD = 2000
_SHORT_TASK_THRESHOLD = 200


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Routes tasks to the cost-optimal model tier.

    Uses keyword heuristics and task length to estimate complexity,
    then maps the resulting tier to a concrete model ID.

    Args:
        provider: Default provider name (key in :data:`MODEL_MAP`).
        model_map: Optional custom model map override.
    """

    def __init__(
        self,
        provider: str = "anthropic",
        model_map: dict[str, dict[ModelTier, str]] | None = None,
    ) -> None:
        self.provider = provider
        self._model_map = model_map or MODEL_MAP

    def estimate_complexity(self, task: str) -> ModelTier:
        """Estimate the complexity tier needed for *task*.

        Heuristics (in priority order):
        1. Premium keyword patterns -> PREMIUM
        2. Fast keyword patterns (and short text) -> FAST
        3. Very long tasks -> STANDARD (likely complex)
        4. Default -> STANDARD

        Args:
            task: Task description or user message.

        Returns:
            The estimated :class:`ModelTier`.
        """
        if not task:
            return ModelTier.STANDARD

        # Check for premium-tier signals
        premium_hits = sum(1 for p in _COMPILED_PREMIUM if p.search(task))
        if premium_hits >= 1:
            logger.debug("Premium pattern matched (%d hits) for task", premium_hits)
            return ModelTier.PREMIUM

        # Check for fast-tier signals
        fast_hits = sum(1 for p in _COMPILED_FAST if p.search(task))
        if fast_hits >= 1 and len(task) < _LONG_TASK_THRESHOLD:
            logger.debug("Fast pattern matched (%d hits) for short task", fast_hits)
            return ModelTier.FAST

        # Long tasks default to standard (complexity likely warrants it)
        if len(task) >= _LONG_TASK_THRESHOLD:
            return ModelTier.STANDARD

        return ModelTier.STANDARD

    def route(
        self,
        task: str,
        min_tier: ModelTier = ModelTier.FAST,
        *,
        provider: str | None = None,
    ) -> str:
        """Return the concrete model ID for *task*.

        Args:
            task: Task description.
            min_tier: Minimum tier to use regardless of heuristics.
            provider: Provider name override.

        Returns:
            Model identifier string suitable for API calls.

        Raises:
            KeyError: If the provider is not in the model map.
        """
        prov = provider or self.provider
        estimated = self.estimate_complexity(task)
        effective = max(estimated, min_tier)

        tier_map = self._model_map[prov]
        model_id = tier_map[effective]

        logger.info(
            "Routed task to %s (tier=%s, estimated=%s, min=%s, provider=%s)",
            model_id,
            effective.name,
            estimated.name,
            min_tier.name,
            prov,
        )
        return model_id
