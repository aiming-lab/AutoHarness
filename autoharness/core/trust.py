"""Session-level progressive trust model.

Tracks user approvals within a session so that once a user approves
a specific type of operation, similar operations are auto-approved
for the remainder of the session (or until trust decay).

Trust levels:
  untrusted -> session_trusted -> auto_approved

Uses denial tracking and session-level trust escalation.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass
class TrustEntry:
    """A single trust approval record."""

    tool_name: str
    pattern: str  # The operation pattern that was approved
    approved_at: float  # time.monotonic()
    count: int = 1


class SessionTrustState:
    """Tracks trust state within a single governance session.

    When a user approves an 'ask' decision, the approval pattern is recorded.
    Subsequent similar tool calls can be auto-approved without re-asking.

    Parameters
    ----------
    trust_decay_seconds : float
        How long an approval remains valid. Default 3600 (1 hour).
        Set to 0 to disable decay (approvals last entire session).
    max_auto_approvals : int
        Maximum number of auto-approvals per pattern before re-asking.
        Default 50. Set to 0 for unlimited.
    """

    def __init__(
        self,
        trust_decay_seconds: float = 3600,
        max_auto_approvals: int = 50,
    ) -> None:
        self._trust_decay = trust_decay_seconds
        self._max_auto = max_auto_approvals
        self._approvals: dict[str, TrustEntry] = {}  # key = "tool:pattern"
        self._denied_patterns: set[str] = set()

    def record_approval(self, tool_name: str, reason: str) -> None:
        """Record that the user approved an ask decision."""
        key = self._make_key(tool_name, reason)
        existing = self._approvals.get(key)
        if existing:
            existing.approved_at = time.monotonic()
            existing.count += 1
        else:
            self._approvals[key] = TrustEntry(
                tool_name=tool_name,
                pattern=reason,
                approved_at=time.monotonic(),
            )
        # Remove from denied if previously denied
        self._denied_patterns.discard(key)

    def record_denial(self, tool_name: str, reason: str) -> None:
        """Record that the user denied an ask decision."""
        key = self._make_key(tool_name, reason)
        self._denied_patterns.add(key)
        self._approvals.pop(key, None)

    def is_trusted(self, tool_name: str, reason: str) -> bool:
        """Check if this tool+reason combination has been previously approved."""
        key = self._make_key(tool_name, reason)

        # Explicitly denied -- never auto-approve
        if key in self._denied_patterns:
            return False

        entry = self._approvals.get(key)
        if entry is None:
            return False

        # Check decay
        if self._trust_decay > 0:
            elapsed = time.monotonic() - entry.approved_at
            if elapsed > self._trust_decay:
                del self._approvals[key]
                return False

        # Check max auto-approvals
        return not (self._max_auto > 0 and entry.count >= self._max_auto)

    def clear(self) -> None:
        """Reset all trust state."""
        self._approvals.clear()
        self._denied_patterns.clear()

    @property
    def approval_count(self) -> int:
        return len(self._approvals)

    @staticmethod
    def _make_key(tool_name: str, reason: str) -> str:
        # Normalize the reason to group similar ask decisions
        # Strip specific values to match on pattern type
        normalized = re.sub(r"'[^']*'", "'...'", reason)
        normalized = re.sub(r"\"[^\"]*\"", '"..."', normalized)
        return f"{tool_name}:{normalized}"
