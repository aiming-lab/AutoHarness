"""Detects when system prompt changes would break the prompt cache."""

from __future__ import annotations

import hashlib


class CacheBreakDetector:
    """Tracks system prompt hash to detect cache-breaking changes."""

    def __init__(self) -> None:
        self._last_hash: str | None = None
        self._break_count: int = 0

    def check(self, prompt_text: str) -> bool:
        """Returns True if the prompt has changed (cache break)."""
        current_hash = hashlib.sha256(prompt_text.encode()).hexdigest()
        if self._last_hash is not None and current_hash != self._last_hash:
            self._break_count += 1
            self._last_hash = current_hash
            return True
        self._last_hash = current_hash
        return False

    @property
    def break_count(self) -> int:
        """Return the total number of cache breaks detected."""
        return self._break_count

    def notify_compaction(self) -> None:
        """Log when compaction causes a cache break."""
        self._break_count += 1
