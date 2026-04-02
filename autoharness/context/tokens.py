"""Token counting and budget tracking for context management.

Provides rough token estimation and a budget tracker that monitors
usage against a configurable window size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Byte-per-token heuristics
# ---------------------------------------------------------------------------

BYTES_PER_TOKEN_DEFAULT: int = 4
"""Average bytes per token for natural-language text."""

BYTES_PER_TOKEN_JSON: int = 2
"""Average bytes per token for structured JSON (more punctuation)."""

IMAGE_MAX_TOKEN_SIZE: int = 2000
"""Fixed token estimate for any image/document content block."""


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string.

    Uses the ~4 characters per token heuristic, which is a reasonable
    approximation for English text with the Claude/GPT tokenizers.

    Parameters
    ----------
    text : str
        The text to estimate tokens for.

    Returns
    -------
    int
        Estimated token count (minimum 1 for non-empty text).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_tokens_by_type(text: str, content_type: str = "text") -> int:
    """Estimate token count with content-type-aware byte ratios.

    Parameters
    ----------
    text : str
        The text to estimate tokens for.
    content_type : str
        Either ``"text"`` (default) or ``"json"``.  JSON content uses a
        lower bytes-per-token ratio because of higher punctuation density.

    Returns
    -------
    int
        Estimated token count (minimum 1 for non-empty text).
    """
    if not text:
        return 0
    bpt = BYTES_PER_TOKEN_JSON if content_type == "json" else BYTES_PER_TOKEN_DEFAULT
    return max(1, len(text) // bpt)


@dataclass
class TokenUsage:
    """Tracks token usage from a single API response.

    Attributes
    ----------
    input_tokens : int
        Number of input tokens consumed.
    output_tokens : int
        Number of output tokens consumed.
    cache_creation_input_tokens : int
        Tokens written to the prompt cache.
    cache_read_input_tokens : int
        Tokens read from the prompt cache.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input(self) -> int:
        """Total input tokens including cache operations."""
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    @property
    def total(self) -> int:
        """Grand total of all token usage."""
        return self.total_input + self.output_tokens


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages.

    Handles both simple string content and structured content blocks
    (Anthropic-style ``[{"type": "text", "text": "..."}]``).

    Parameters
    ----------
    messages : list[dict]
        List of message dicts with ``role`` and ``content`` keys.

    Returns
    -------
    int
        Estimated total token count across all messages.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    # Handle image / document blocks with fixed token size
                    if block_type in ("image", "document"):
                        total += IMAGE_MAX_TOKEN_SIZE
                        continue
                    # Handle text blocks
                    text = block.get("text", "")
                    if text:
                        total += estimate_tokens(text)
                    # Handle tool_result content
                    inner_content = block.get("content", "")
                    if isinstance(inner_content, str) and inner_content:
                        total += estimate_tokens(inner_content)
                elif isinstance(block, str):
                    total += estimate_tokens(block)
        # Add small overhead per message for role/structure
        total += 4
    return total


class TokenBudget:
    """Tracks token usage against a maximum budget.

    Parameters
    ----------
    max_tokens : int
        Maximum context window size in tokens.
    reserve : int
        Tokens to reserve for the response (default 13000).
    """

    def __init__(self, max_tokens: int, reserve: int = 13000) -> None:
        self.max_tokens = max_tokens
        self.reserve = reserve
        self._input_tokens_used: int = 0
        self._output_tokens_used: int = 0

    @property
    def effective_window(self) -> int:
        """Maximum tokens available for input (max - reserve)."""
        return self.max_tokens - self.reserve

    @property
    def current_usage(self) -> int:
        """Total tokens used so far (input + output)."""
        return self._input_tokens_used + self._output_tokens_used

    @property
    def available(self) -> int:
        """Tokens remaining before hitting the effective limit.

        Returns max_tokens - current_usage - reserve. May be negative
        if the budget has been exceeded.
        """
        return self.max_tokens - self.current_usage - self.reserve

    @property
    def usage_ratio(self) -> float:
        """Current usage as a fraction of the effective window."""
        ew = self.effective_window
        if ew <= 0:
            return 1.0
        return self.current_usage / ew

    @property
    def should_compact(self) -> bool:
        """True when usage exceeds 93% of the effective window."""
        return self.usage_ratio > 0.93

    @property
    def should_warn(self) -> bool:
        """True when usage exceeds 80% of the effective window."""
        return self.usage_ratio > 0.80

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record token usage from an API call.

        Parameters
        ----------
        input_tokens : int
            Number of input/prompt tokens consumed.
        output_tokens : int
            Number of output/completion tokens consumed.
        """
        self._input_tokens_used += input_tokens
        self._output_tokens_used += output_tokens

        if self.should_warn:
            logger.warning(
                "TokenBudget: usage at %.1f%% (%d/%d effective)",
                self.usage_ratio * 100,
                self.current_usage,
                self.effective_window,
            )

    def reset(self) -> None:
        """Reset usage counters to zero."""
        self._input_tokens_used = 0
        self._output_tokens_used = 0
