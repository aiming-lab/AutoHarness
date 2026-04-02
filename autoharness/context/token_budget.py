"""User-facing token budget syntax parsing and continuation messages.

Allows users to express token budgets in natural language (e.g.,
``"+500k"``, ``"use 2M tokens"``, ``"spend 1B tokens"``) and provides
utilities for budget-aware continuation prompts.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches: +500k, +2M, +1B (standalone)
_PLUS_PATTERN = re.compile(
    r"\+\s*(\d+(?:\.\d+)?)\s*([kKmMbBgG])\b"
)

# Matches: "use 500k tokens", "spend 2M tokens", "budget 1B"
_VERB_PATTERN = re.compile(
    r"(?:use|spend|budget|allocate)\s+(\d+(?:\.\d+)?)\s*([kKmMbBgG])(?:\s+tokens?)?\b",
    re.IGNORECASE,
)

_MULTIPLIERS: dict[str, int] = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "g": 1_000_000_000,
}


def _parse_number_with_suffix(digits: str, suffix: str) -> int:
    """Convert a number string + suffix character to an integer."""
    multiplier = _MULTIPLIERS.get(suffix.lower(), 1)
    return int(float(digits) * multiplier)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_token_budget(text: str) -> int | None:
    """Parse a token budget from user text.

    Supports formats like:
    - ``"+500k"`` -> 500 000
    - ``"use 2M tokens"`` -> 2 000 000
    - ``"spend 1B tokens"`` -> 1 000 000 000

    Parameters
    ----------
    text : str
        User message text to scan.

    Returns
    -------
    int or None
        The parsed token budget, or ``None`` if no budget was found.
    """
    if not text:
        return None

    for pattern in (_PLUS_PATTERN, _VERB_PATTERN):
        match = pattern.search(text)
        if match:
            return _parse_number_with_suffix(match.group(1), match.group(2))

    return None


def find_token_budget_positions(text: str) -> list[tuple[int, int]]:
    """Find all token budget expressions in *text*.

    Parameters
    ----------
    text : str
        User message text to scan.

    Returns
    -------
    list[tuple[int, int]]
        List of ``(start, end)`` character positions for each match.
    """
    positions: list[tuple[int, int]] = []

    if not text:
        return positions

    for pattern in (_PLUS_PATTERN, _VERB_PATTERN):
        for match in pattern.finditer(text):
            positions.append((match.start(), match.end()))

    # Sort by start position, deduplicate overlapping spans
    positions.sort()
    return positions


def get_budget_continuation_message(
    pct: float,
    turn_tokens: int,
    budget: int,
) -> str:
    """Generate a budget-status continuation message for the user.

    Parameters
    ----------
    pct : float
        Fraction of budget consumed (0.0 to 1.0+).
    turn_tokens : int
        Tokens used in the current turn.
    budget : int
        Total token budget.

    Returns
    -------
    str
        A human-readable message about budget consumption.
    """
    remaining = budget - int(pct * budget)
    pct_display = min(100.0, pct * 100)

    if pct >= 1.0:
        return (
            f"Token budget exhausted ({budget:,} tokens). "
            f"This turn used {turn_tokens:,} tokens."
        )

    if pct >= 0.9:
        return (
            f"Token budget nearly exhausted: {pct_display:.0f}% used "
            f"({remaining:,} tokens remaining). "
            f"This turn used {turn_tokens:,} tokens."
        )

    if pct >= 0.5:
        return (
            f"Token budget: {pct_display:.0f}% used "
            f"({remaining:,} tokens remaining). "
            f"This turn used {turn_tokens:,} tokens."
        )

    return (
        f"Token budget: {pct_display:.0f}% used "
        f"({remaining:,} tokens remaining)."
    )
