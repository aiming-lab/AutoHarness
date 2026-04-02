"""Error recovery utilities — max output retry, thinking preservation, API retry.

Handles:
- Max output token truncation recovery (retry up to 3 times)
- Thinking block preservation rules across turns
- API retry with exponential backoff
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
DEFAULT_MAX_RETRIES = 2
DEFAULT_INITIAL_BACKOFF_MS = 200
DEFAULT_MAX_BACKOFF_MS = 2000

@dataclass
class RetryConfig:
    max_retries: int = DEFAULT_MAX_RETRIES
    initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS
    max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS

def is_max_output_truncated(response: dict[str, Any]) -> bool:
    """Check if a response was truncated due to max_output_tokens."""
    return response.get("stop_reason") == "max_tokens"

def get_continuation_message() -> dict[str, str]:
    """Generate a continuation message for truncated output."""
    return {
        "role": "user",
        "content": "Your response was cut off. Please continue from where you left off.",
    }

class OutputRecoveryLoop:
    """Retries when model output is truncated by max_tokens."""

    def __init__(self, max_retries: int = MAX_OUTPUT_TOKENS_RECOVERY_LIMIT) -> None:
        self.max_retries = max_retries
        self._retry_count = 0

    def should_retry(self, response: dict[str, Any]) -> bool:
        if not is_max_output_truncated(response):
            self._retry_count = 0
            return False
        if self._retry_count >= self.max_retries:
            logger.warning("Max output recovery limit reached (%d)", self.max_retries)
            return False
        self._retry_count += 1
        return True

    def reset(self) -> None:
        self._retry_count = 0

def should_preserve_thinking(message: dict[str, Any]) -> bool:
    """Check if a message contains thinking blocks that must be preserved."""
    content = message.get("content", [])
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
        for b in content
    )

def validate_thinking_blocks(messages: list[dict[str, Any]]) -> list[str]:
    """Validate thinking block rules. Returns list of issues found."""
    issues = []
    for i, msg in enumerate(messages):
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        has_thinking = any(
            isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
            for b in content
        )
        if has_thinking:
            if msg.get("role") != "assistant":
                issues.append(f"Message {i}: thinking block in non-assistant message")
            if (
                content
                and isinstance(content[-1], dict)
                and content[-1].get("type") in ("thinking", "redacted_thinking")
            ):
                issues.append(f"Message {i}: thinking block is last in content")
    return issues

def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES

def compute_backoff_ms(attempt: int, config: RetryConfig | None = None) -> int:
    """Compute exponential backoff delay in milliseconds."""
    if config is None:
        config = RetryConfig()
    delay = config.initial_backoff_ms * (2 ** attempt)
    return int(min(delay, config.max_backoff_ms))

async def retry_with_backoff(
    fn: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> Any:
    """Execute fn with exponential backoff retry on failure."""
    if config is None:
        config = RetryConfig()

    last_error = None
    for attempt in range(config.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            if attempt < config.max_retries:
                delay = compute_backoff_ms(attempt, config) / 1000.0
                logger.debug(
                    "Retry %d/%d after %.1fs: %s",
                    attempt + 1, config.max_retries, delay, exc,
                )
                await asyncio.sleep(delay)

    raise last_error  # type: ignore
