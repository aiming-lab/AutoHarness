"""Tool name matcher for hook routing.

Supports regex patterns like 'Bash|Edit|Write|*' for matching tool names.
Used by the hook system to route hooks to specific tools.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

class ToolMatcher:
    """Matches tool names against patterns for hook routing."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self._compiled = self._compile(pattern)

    def matches(self, tool_name: str) -> bool:
        """Check if a tool name matches this pattern."""
        if self.pattern == "*":
            return True
        return bool(self._compiled.fullmatch(tool_name))

    @staticmethod
    def _compile(pattern: str) -> re.Pattern[str]:
        """Compile a tool matcher pattern to regex.

        Supports:
        - '*' = match any tool
        - 'Bash' = exact match
        - 'Bash|Edit|Write' = match any of these
        - 'Bash*' = prefix match
        """
        if pattern == "*":
            return re.compile(".*")

        # If pattern contains | (OR), treat as alternation
        if "|" in pattern:
            parts = [re.escape(p.strip()) for p in pattern.split("|")]
            return re.compile("|".join(parts), re.IGNORECASE)

        # Convert glob-style * to regex
        escaped = re.escape(pattern)
        escaped = escaped.replace(r"\*", ".*")
        return re.compile(escaped, re.IGNORECASE)

    def __repr__(self) -> str:
        return f"ToolMatcher({self.pattern!r})"
