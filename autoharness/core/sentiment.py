"""User sentiment detection — frustration keyword analysis.

Detects signals of user frustration from message content to enable
adaptive behavior (more careful responses, backoff from aggressive actions).

The detector is intentionally lightweight — pure regex matching with no
ML dependencies — so it can run on every user turn without measurable cost.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frustration patterns — compiled regexes for fast matching
# ---------------------------------------------------------------------------

FRUSTRATION_PATTERNS: frozenset[str] = frozenset(
    {
        r"\bwtf\b",
        r"\bwhat the (hell|fuck|heck)\b",
        r"\bbroken\b",
        r"\buseless\b",
        r"\bstupid\b",
        r"\bidiot(ic)?\b",
        r"\bterrible\b",
        r"\bhorrible\b",
        r"\bawful\b",
        r"\bdoesn'?t work\b",
        r"\bnot working\b",
        r"\bfail(ed|ing|s)?\b",
        r"\bwaste of time\b",
        r"\bgive up\b",
        r"\bgave up\b",
        r"\bfrust?rat(ed|ing)\b",
        r"\bannoy(ed|ing)\b",
        r"\bstop (doing|messing|breaking)\b",
        r"\byou (keep|always) (break|mess|screw|fail)\w*\b",
        r"\bwhy (won'?t|can'?t|doesn'?t)\b",
        r"\bI said\b",
        r"\bI already told you\b",
        r"\bread (the|my) (message|question|instructions?)\b",
    }
)

_COMPILED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in FRUSTRATION_PATTERNS
)


# ---------------------------------------------------------------------------
# Frustration levels
# ---------------------------------------------------------------------------


class FrustrationLevel(str, Enum):
    """Graduated frustration severity."""

    none = "none"
    mild = "mild"
    strong = "strong"


# ---------------------------------------------------------------------------
# FrustrationSignal — result of detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrustrationSignal:
    """Result of frustration detection on a piece of text.

    Attributes:
        level: Overall frustration severity.
        keywords_matched: Specific patterns that matched.
    """

    level: FrustrationLevel
    keywords_matched: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_frustrated(self) -> bool:
        """Return ``True`` if any frustration was detected."""
        return self.level != FrustrationLevel.none


# ---------------------------------------------------------------------------
# Detection function
# ---------------------------------------------------------------------------

# Thresholds for level assignment
_MILD_THRESHOLD = 1
_STRONG_THRESHOLD = 3


def detect_frustration(text: str) -> FrustrationSignal:
    """Scan *text* for frustration signals.

    Args:
        text: User message content.

    Returns:
        A :class:`FrustrationSignal` with the detected level and matched
        keywords.
    """
    if not text:
        return FrustrationSignal(level=FrustrationLevel.none)

    matched: list[str] = []
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            matched.append(pattern.pattern)

    if len(matched) >= _STRONG_THRESHOLD:
        level = FrustrationLevel.strong
    elif len(matched) >= _MILD_THRESHOLD:
        level = FrustrationLevel.mild
    else:
        level = FrustrationLevel.none

    signal = FrustrationSignal(level=level, keywords_matched=tuple(matched))

    if signal.is_frustrated:
        logger.debug(
            "Frustration detected (level=%s, matches=%d): %s",
            signal.level,
            len(matched),
            matched,
        )

    return signal
