"""Tests for autoharness.core.turn_governor — TurnGovernor turn-level governance."""

from __future__ import annotations

from autoharness.core.constitution import Constitution
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.turn_governor import TurnGovernor, TurnStats
from autoharness.core.types import PermissionDecision, RiskLevel, ToolCall

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _tc(name: str = "bash", cmd: str = "echo hi") -> ToolCall:
    return ToolCall(tool_name=name, tool_input={"command": cmd})


def _allow(risk: RiskLevel = RiskLevel.low) -> PermissionDecision:
    return PermissionDecision(action="allow", reason="ok", source="test", risk_level=risk)


def _deny(risk: RiskLevel = RiskLevel.low) -> PermissionDecision:
    return PermissionDecision(action="deny", reason="no", source="test", risk_level=risk)


# -----------------------------------------------------------------------
# TurnStats defaults
# -----------------------------------------------------------------------


class TestTurnStats:
    def test_defaults(self):
        stats = TurnStats()
        assert stats.tool_calls == 0
        assert stats.denied_calls == 0
        assert stats.consecutive_denials == 0
        assert stats.max_risk_seen == RiskLevel.low
        assert stats.total_duration_ms == 0.0
        assert stats.started_at > 0


# -----------------------------------------------------------------------
# TurnGovernor — iteration limits
# -----------------------------------------------------------------------


class TestIterationLimits:
    def test_under_limit_allows(self):
        gov = TurnGovernor(max_iterations=5)
        for _ in range(4):
            assert gov.check_turn_limits(_tc()) is None
            gov.record_result(_allow(), RiskLevel.low)
        # 5th call should still be allowed (we've done 4)
        assert gov.check_turn_limits(_tc()) is None

    def test_at_limit_denies(self):
        gov = TurnGovernor(max_iterations=3)
        for _ in range(3):
            gov.check_turn_limits(_tc())
            gov.record_result(_allow(), RiskLevel.low)
        # 4th call: tool_calls == 3 == max_iterations -> deny
        result = gov.check_turn_limits(_tc())
        assert result is not None
        assert result.action == "deny"
        assert "iteration limit" in result.reason.lower()
        assert result.source == "turn_governor"


# -----------------------------------------------------------------------
# TurnGovernor — denial spiral detection
# -----------------------------------------------------------------------


class TestDenialSpiral:
    def test_consecutive_denials_triggers(self):
        gov = TurnGovernor(max_consecutive_denials=3, max_iterations=100)
        for _ in range(3):
            gov.check_turn_limits(_tc())
            gov.record_result(_deny(), RiskLevel.low)
        result = gov.check_turn_limits(_tc())
        assert result is not None
        assert result.action == "deny"
        assert "denial spiral" in result.reason.lower()

    def test_allow_resets_consecutive_denials(self):
        gov = TurnGovernor(max_consecutive_denials=3, max_iterations=100)
        # Two denials
        for _ in range(2):
            gov.check_turn_limits(_tc())
            gov.record_result(_deny(), RiskLevel.low)
        # One allow resets counter
        gov.check_turn_limits(_tc())
        gov.record_result(_allow(), RiskLevel.low)
        # Two more denials — still under threshold
        for _ in range(2):
            gov.check_turn_limits(_tc())
            gov.record_result(_deny(), RiskLevel.low)
        assert gov.check_turn_limits(_tc()) is None


# -----------------------------------------------------------------------
# TurnGovernor — cumulative risk
# -----------------------------------------------------------------------


class TestCumulativeRisk:
    def test_low_risk_accumulates_slowly(self):
        gov = TurnGovernor(cumulative_risk_threshold=10, max_iterations=100)
        for _ in range(9):
            gov.check_turn_limits(_tc())
            gov.record_result(_allow(), RiskLevel.low)
        # 9 low-risk calls = score 9, threshold 10 -> still ok
        assert gov.check_turn_limits(_tc()) is None

    def test_high_risk_accumulates_fast(self):
        gov = TurnGovernor(cumulative_risk_threshold=25, max_iterations=100)
        for _ in range(3):
            gov.check_turn_limits(_tc())
            gov.record_result(_allow(), RiskLevel.high)  # weight 10 each
        # Score = 30 >= 25 -> deny
        result = gov.check_turn_limits(_tc())
        assert result is not None
        assert result.action == "deny"
        assert "cumulative risk" in result.reason.lower()

    def test_critical_risk_triggers_quickly(self):
        gov = TurnGovernor(cumulative_risk_threshold=100, max_iterations=100)
        gov.check_turn_limits(_tc())
        gov.record_result(_allow(), RiskLevel.critical)  # weight 50
        gov.check_turn_limits(_tc())
        gov.record_result(_allow(), RiskLevel.critical)  # weight 50, total 100
        result = gov.check_turn_limits(_tc())
        assert result is not None
        assert result.action == "deny"


# -----------------------------------------------------------------------
# TurnGovernor — rate limiting
# -----------------------------------------------------------------------


class TestRateLimiting:
    def test_rate_limit_enforced(self):
        gov = TurnGovernor(rate_limit_per_minute=3, max_iterations=100)
        for _ in range(3):
            assert gov.check_turn_limits(_tc()) is None
            gov.record_result(_allow(), RiskLevel.low)
        result = gov.check_turn_limits(_tc())
        assert result is not None
        assert result.action == "deny"
        assert "rate limit" in result.reason.lower()

    def test_rate_limit_zero_means_unlimited(self):
        gov = TurnGovernor(rate_limit_per_minute=0, max_iterations=1000)
        for _ in range(100):
            assert gov.check_turn_limits(_tc()) is None
            gov.record_result(_allow(), RiskLevel.low)


# -----------------------------------------------------------------------
# TurnGovernor — new_turn resets
# -----------------------------------------------------------------------


class TestNewTurn:
    def test_new_turn_returns_previous_stats(self):
        gov = TurnGovernor(max_iterations=100)
        gov.check_turn_limits(_tc())
        gov.record_result(_allow(), RiskLevel.medium)
        gov.check_turn_limits(_tc())
        gov.record_result(_deny(), RiskLevel.high)

        prev = gov.new_turn()
        assert prev.tool_calls == 2
        assert prev.denied_calls == 1
        assert prev.max_risk_seen == RiskLevel.high

    def test_new_turn_resets_state(self):
        gov = TurnGovernor(max_iterations=3)
        for _ in range(3):
            gov.check_turn_limits(_tc())
            gov.record_result(_allow(), RiskLevel.low)
        # At limit now
        assert gov.check_turn_limits(_tc()) is not None
        # Reset
        gov.new_turn()
        assert gov.check_turn_limits(_tc()) is None
        assert gov.stats.tool_calls == 0

    def test_new_turn_resets_cumulative_risk(self):
        gov = TurnGovernor(cumulative_risk_threshold=20, max_iterations=100)
        for _ in range(3):
            gov.check_turn_limits(_tc())
            gov.record_result(_allow(), RiskLevel.high)  # 30 total
        assert gov.check_turn_limits(_tc()) is not None
        gov.new_turn()
        assert gov.check_turn_limits(_tc()) is None


# -----------------------------------------------------------------------
# TurnGovernor — max_risk_seen tracking
# -----------------------------------------------------------------------


class TestMaxRiskTracking:
    def test_max_risk_updates(self):
        gov = TurnGovernor(max_iterations=100)
        gov.record_result(_allow(), RiskLevel.low)
        assert gov.stats.max_risk_seen == RiskLevel.low
        gov.record_result(_allow(), RiskLevel.high)
        assert gov.stats.max_risk_seen == RiskLevel.high
        gov.record_result(_allow(), RiskLevel.medium)
        # Should stay at high
        assert gov.stats.max_risk_seen == RiskLevel.high


# -----------------------------------------------------------------------
# Pipeline integration
# -----------------------------------------------------------------------


class TestPipelineIntegration:
    def test_turn_governor_accessible(self, tmp_path):
        pipeline = ToolGovernancePipeline(
            constitution=Constitution.default(),
            project_dir=str(tmp_path),
            session_id="test",
        )
        assert pipeline.turn_governor is not None
        assert isinstance(pipeline.turn_governor, TurnGovernor)

    def test_turn_governor_tracks_calls(self, tmp_path):
        pipeline = ToolGovernancePipeline(
            constitution=Constitution.default(),
            project_dir=str(tmp_path),
            session_id="test",
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        pipeline.process(tc)
        assert pipeline.turn_governor.stats.tool_calls == 1

    def test_turn_governor_tracks_blocks(self, tmp_path):
        pipeline = ToolGovernancePipeline(
            constitution=Constitution.default(),
            project_dir=str(tmp_path),
            session_id="test",
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})
        pipeline.process(tc)
        assert pipeline.turn_governor.stats.denied_calls >= 1

    def test_iteration_limit_in_pipeline(self, tmp_path):
        pipeline = ToolGovernancePipeline(
            constitution=Constitution.default(),
            project_dir=str(tmp_path),
            session_id="test",
        )
        # Set a very low limit
        pipeline._turn_governor = TurnGovernor(max_iterations=2)
        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        r1 = pipeline.process(tc)
        r2 = pipeline.process(tc)
        r3 = pipeline.process(tc)
        assert r1.status == "success"
        assert r2.status == "success"
        assert r3.status == "blocked"
        assert "iteration limit" in r3.blocked_reason.lower()

    def test_existing_tests_unaffected(self, tmp_path):
        """Sanity check: basic allow/deny still works with turn governor."""
        pipeline = ToolGovernancePipeline(
            constitution=Constitution.default(),
            project_dir=str(tmp_path),
            session_id="test",
        )
        safe = ToolCall(tool_name="bash", tool_input={"command": "git status"})
        dangerous = ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})
        assert pipeline.process(safe).status == "success"
        assert pipeline.process(dangerous).status == "blocked"
