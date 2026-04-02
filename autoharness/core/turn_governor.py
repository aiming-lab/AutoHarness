"""Turn Governor — governs entire agent turns, not just individual tool calls.

Tracks cumulative risk across multiple tool calls within a single turn,
enforces iteration limits, and detects denial spirals.

Enforces a max-iterations cap per turn and detects consecutive-denial
spirals (default threshold: 3).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import ClassVar

from autoharness.core.types import PermissionDecision, RiskLevel, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class TurnStats:
    """Statistics for a single agent turn."""

    tool_calls: int = 0
    denied_calls: int = 0
    consecutive_denials: int = 0
    max_risk_seen: RiskLevel = RiskLevel.low
    total_duration_ms: float = 0.0
    started_at: float = field(default_factory=time.monotonic)


class TurnGovernor:
    """Governs the behavior of an agent turn as a whole.

    Parameters
    ----------
    max_iterations : int
        Maximum tool calls allowed in a single turn. Default 50.
    max_consecutive_denials : int
        After N consecutive denials, escalate strategy. Default 5.
    cumulative_risk_threshold : int
        If cumulative risk exceeds this level, block remaining calls.
        Default 100.
    rate_limit_per_minute : int
        Maximum tool calls per minute. Default 60. 0 = unlimited.
    """

    RISK_WEIGHTS: ClassVar[dict[RiskLevel, int]] = {
        RiskLevel.low: 1,
        RiskLevel.medium: 3,
        RiskLevel.high: 10,
        RiskLevel.critical: 50,
    }

    def __init__(
        self,
        max_iterations: int = 50,
        max_consecutive_denials: int = 5,
        cumulative_risk_threshold: int = 100,
        rate_limit_per_minute: int = 60,
    ) -> None:
        self._max_iterations = max_iterations
        self._max_consecutive_denials = max_consecutive_denials
        self._risk_threshold = cumulative_risk_threshold
        self._rate_limit = rate_limit_per_minute

        self._current_turn = TurnStats()
        self._cumulative_risk_score = 0
        self._call_timestamps: list[float] = []

    def check_turn_limits(self, tool_call: ToolCall) -> PermissionDecision | None:
        """Check turn-level governance before processing a tool call.

        Returns a deny PermissionDecision if turn limits are exceeded,
        or None to allow the call to proceed.
        """
        # Check iteration limit
        if self._current_turn.tool_calls >= self._max_iterations:
            return PermissionDecision(
                action="deny",
                reason=f"Turn iteration limit exceeded ({self._max_iterations})",
                source="turn_governor",
            )

        # Check consecutive denial spiral
        if self._current_turn.consecutive_denials >= self._max_consecutive_denials:
            return PermissionDecision(
                action="deny",
                reason=(
                    f"Denial spiral detected "
                    f"({self._current_turn.consecutive_denials} consecutive denials)"
                ),
                source="turn_governor",
            )

        # Check cumulative risk
        if self._cumulative_risk_score >= self._risk_threshold:
            return PermissionDecision(
                action="deny",
                reason=f"Cumulative risk threshold exceeded (score={self._cumulative_risk_score})",
                source="turn_governor",
            )

        # Check rate limit
        if self._rate_limit > 0:
            now = time.monotonic()
            # Remove timestamps older than 60 seconds
            self._call_timestamps = [
                t for t in self._call_timestamps if now - t < 60
            ]
            if len(self._call_timestamps) >= self._rate_limit:
                return PermissionDecision(
                    action="deny",
                    reason=f"Rate limit exceeded ({self._rate_limit}/min)",
                    source="turn_governor",
                )
            self._call_timestamps.append(now)

        return None

    def record_result(
        self, decision: PermissionDecision, risk_level: RiskLevel
    ) -> None:
        """Record a tool call result for turn tracking."""
        self._current_turn.tool_calls += 1

        # Track max risk seen
        risk_order = [RiskLevel.low, RiskLevel.medium, RiskLevel.high, RiskLevel.critical]
        if risk_order.index(risk_level) > risk_order.index(
            self._current_turn.max_risk_seen
        ):
            self._current_turn.max_risk_seen = risk_level

        if decision.action == "deny":
            self._current_turn.denied_calls += 1
            self._current_turn.consecutive_denials += 1
        else:
            # Only accumulate risk for permitted (executed) calls.
            # Blocked/denied calls should not add to cumulative risk
            # since they were already prevented and no harm was done.
            weight = self.RISK_WEIGHTS.get(risk_level, 1)
            self._cumulative_risk_score += weight
            self._current_turn.consecutive_denials = 0

    def new_turn(self) -> TurnStats:
        """Start a new turn, returning stats from the previous turn."""
        prev = self._current_turn
        self._current_turn = TurnStats()
        self._cumulative_risk_score = 0
        return prev

    @property
    def stats(self) -> TurnStats:
        """Current turn statistics."""
        return self._current_turn
