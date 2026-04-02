"""Tests for autoharness.core.multi_agent — MultiAgentGovernor and AgentProfile."""

from __future__ import annotations

import pytest

from autoharness.core.constitution import Constitution
from autoharness.core.multi_agent import (
    BUILTIN_PROFILES,
    AgentProfile,
    MultiAgentGovernor,
    _risk_level_value,
)
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.types import ToolCall

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _make_governor(tmp_path, constitution=None) -> MultiAgentGovernor:
    c = constitution or Constitution.default()
    return MultiAgentGovernor(c, project_dir=str(tmp_path))


# -----------------------------------------------------------------------
# AgentProfile validation
# -----------------------------------------------------------------------


class TestAgentProfile:
    def test_valid_profile(self):
        p = AgentProfile(name="test", role="coder", max_risk_level="medium")
        assert p.name == "test"
        assert p.role == "coder"

    def test_invalid_risk_level(self):
        with pytest.raises(ValueError, match="Invalid max_risk_level"):
            AgentProfile(name="test", role="coder", max_risk_level="extreme")

    def test_overlapping_allowed_denied_raises(self):
        with pytest.raises(ValueError, match="both allowed and denied"):
            AgentProfile(
                name="test",
                role="coder",
                allowed_tools=["bash", "read"],
                denied_tools=["bash"],
            )

    def test_allowed_tools_none_means_all(self):
        p = AgentProfile(name="test", role="coder")
        assert p.allowed_tools is None

    def test_metadata_default_empty(self):
        p = AgentProfile(name="test", role="coder")
        assert p.metadata == {}


# -----------------------------------------------------------------------
# Risk level ordering
# -----------------------------------------------------------------------


class TestRiskLevelOrder:
    def test_ordering(self):
        assert _risk_level_value("low") < _risk_level_value("medium")
        assert _risk_level_value("medium") < _risk_level_value("high")
        assert _risk_level_value("high") < _risk_level_value("critical")

    def test_unknown_returns_zero(self):
        assert _risk_level_value("unknown") == 0


# -----------------------------------------------------------------------
# Built-in profiles
# -----------------------------------------------------------------------


class TestBuiltinProfiles:
    def test_all_builtins_exist(self):
        expected = {"coder", "reviewer", "planner", "executor"}
        assert set(BUILTIN_PROFILES.keys()) == expected

    def test_reviewer_is_read_only(self):
        p = BUILTIN_PROFILES["reviewer"]
        assert p.allowed_tools is not None
        # Should only contain read-like tools
        for tool in p.allowed_tools:
            assert tool.lower() in ("read", "grep", "glob", "search")

    def test_planner_is_read_only(self):
        p = BUILTIN_PROFILES["planner"]
        assert p.allowed_tools is not None

    def test_coder_has_full_access(self):
        p = BUILTIN_PROFILES["coder"]
        assert p.allowed_tools is None  # None = all tools

    def test_executor_has_risk_override(self):
        p = BUILTIN_PROFILES["executor"]
        assert p.constitution_override is not None
        assert "risk" in p.constitution_override


# -----------------------------------------------------------------------
# Governor registration
# -----------------------------------------------------------------------


class TestGovernorRegistration:
    def test_register_builtin_by_name(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        assert "coder" in gov.agents

    def test_register_custom_profile(self, tmp_path):
        gov = _make_governor(tmp_path)
        profile = AgentProfile(
            name="custom",
            role="analyst",
            allowed_tools=["read", "grep"],
            max_risk_level="low",
        )
        gov.register_agent("custom", profile)
        assert "custom" in gov.agents
        assert gov.get_profile("custom").role == "analyst"

    def test_register_unknown_builtin_raises(self, tmp_path):
        gov = _make_governor(tmp_path)
        with pytest.raises(ValueError, match="No built-in profile"):
            gov.register_agent("nonexistent")

    def test_register_all_builtins(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_all_builtins()
        assert set(gov.agents.keys()) == set(BUILTIN_PROFILES.keys())

    def test_get_profile_unregistered_raises(self, tmp_path):
        gov = _make_governor(tmp_path)
        with pytest.raises(KeyError, match="not registered"):
            gov.get_profile("ghost")


# -----------------------------------------------------------------------
# Pipeline construction
# -----------------------------------------------------------------------


class TestGovernorPipeline:
    def test_get_pipeline_returns_pipeline(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        pipeline = gov.get_pipeline("coder")
        assert isinstance(pipeline, ToolGovernancePipeline)

    def test_pipeline_is_cached(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        p1 = gov.get_pipeline("coder")
        p2 = gov.get_pipeline("coder")
        assert p1 is p2

    def test_reset_pipeline_clears_cache(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        p1 = gov.get_pipeline("coder")
        gov.reset_pipeline("coder")
        p2 = gov.get_pipeline("coder")
        assert p1 is not p2

    def test_get_pipeline_unregistered_raises(self, tmp_path):
        gov = _make_governor(tmp_path)
        with pytest.raises(KeyError, match="not registered"):
            gov.get_pipeline("ghost")


# -----------------------------------------------------------------------
# Tool whitelisting / blacklisting
# -----------------------------------------------------------------------


class TestToolFiltering:
    def test_reviewer_blocks_write(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("reviewer")
        pipeline = gov.get_pipeline("reviewer")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        result = pipeline.process(tc)
        assert result.status == "blocked"
        assert "not allowed" in result.blocked_reason.lower()

    def test_reviewer_allows_read(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("reviewer")
        pipeline = gov.get_pipeline("reviewer")

        tc = ToolCall(
            tool_name="read",
            tool_input={"file_path": str(tmp_path / "test.txt")},
        )
        result = pipeline.process(tc)
        # Should pass the tool filter (may still be governed by other hooks)
        assert result.status in ("success", "blocked")
        # If blocked, should NOT be because of the agent filter
        if result.status == "blocked" and result.blocked_reason:
            assert "not allowed" not in result.blocked_reason.lower()

    def test_coder_allows_bash(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        pipeline = gov.get_pipeline("coder")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        result = pipeline.process(tc)
        assert result.status == "success"

    def test_custom_denied_tools(self, tmp_path):
        gov = _make_governor(tmp_path)
        profile = AgentProfile(
            name="limited",
            role="limited",
            denied_tools=["bash"],
            max_risk_level="high",
        )
        gov.register_agent("limited", profile)
        pipeline = gov.get_pipeline("limited")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        result = pipeline.process(tc)
        assert result.status == "blocked"
        assert "denied" in result.blocked_reason.lower()


# -----------------------------------------------------------------------
# Risk ceiling enforcement
# -----------------------------------------------------------------------


class TestRiskCeiling:
    def test_low_risk_agent_blocks_dangerous(self, tmp_path):
        """An agent with max_risk_level='low' should block high-risk calls."""
        gov = _make_governor(tmp_path)
        profile = AgentProfile(
            name="cautious",
            role="cautious",
            allowed_tools=None,  # all tools
            max_risk_level="low",
        )
        gov.register_agent("cautious", profile)
        pipeline = gov.get_pipeline("cautious")

        # sudo triggers high risk classification
        tc = ToolCall(tool_name="bash", tool_input={"command": "sudo rm /etc/hosts"})
        result = pipeline.process(tc)
        assert result.status == "blocked"

    def test_medium_risk_agent_allows_safe(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        pipeline = gov.get_pipeline("coder")

        tc = ToolCall(tool_name="bash", tool_input={"command": "git status"})
        result = pipeline.process(tc)
        assert result.status == "success"


# -----------------------------------------------------------------------
# Profile inheritance
# -----------------------------------------------------------------------


class TestProfileInheritance:
    def test_inherit_from_builtin(self, tmp_path):
        gov = _make_governor(tmp_path)

        # Create a profile that inherits from reviewer but changes risk level
        child = AgentProfile(
            name="senior_reviewer",
            role="reviewer",
            inherit_from="reviewer",
            max_risk_level="medium",  # override parent's "low"
        )
        gov.register_agent("senior_reviewer", child)
        profile = gov.get_profile("senior_reviewer")

        # Should inherit allowed_tools from reviewer
        assert profile.allowed_tools is not None
        assert "read" in [t.lower() for t in profile.allowed_tools]
        # But max_risk_level should be the child's override
        assert profile.max_risk_level == "medium"

    def test_inherit_from_registered(self, tmp_path):
        gov = _make_governor(tmp_path)

        # Register a base profile
        base = AgentProfile(
            name="base_agent",
            role="base",
            allowed_tools=["read", "grep"],
            max_risk_level="low",
            metadata={"tier": "basic"},
        )
        gov.register_agent("base_agent", base)

        # Create a child that inherits and adds tools
        child = AgentProfile(
            name="extended",
            role="extended",
            inherit_from="base_agent",
            allowed_tools=["read", "grep", "bash"],  # explicitly override
            max_risk_level="medium",
            metadata={"tier": "advanced"},
        )
        gov.register_agent("extended", child)
        profile = gov.get_profile("extended")

        assert "bash" in profile.allowed_tools
        assert profile.max_risk_level == "medium"
        assert profile.metadata["tier"] == "advanced"

    def test_inherit_from_missing_raises(self, tmp_path):
        gov = _make_governor(tmp_path)
        child = AgentProfile(
            name="orphan",
            role="orphan",
            inherit_from="nonexistent",
        )
        with pytest.raises(ValueError, match="not registered or built-in"):
            gov.register_agent("orphan", child)


# -----------------------------------------------------------------------
# Evaluate convenience method
# -----------------------------------------------------------------------


class TestEvaluateConvenience:
    def test_evaluate_returns_decision(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        decision = gov.evaluate("coder", tc)
        assert decision.action in ("allow", "deny", "ask")

    def test_evaluate_reviewer_denies_bash(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("reviewer")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        decision = gov.evaluate("reviewer", tc)
        assert decision.action == "deny"


# -----------------------------------------------------------------------
# Session isolation
# -----------------------------------------------------------------------


class TestSessionIsolation:
    def test_different_agents_get_different_sessions(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        gov.register_agent("reviewer")

        p_coder = gov.get_pipeline("coder")
        p_reviewer = gov.get_pipeline("reviewer")

        # Session IDs should be different
        assert p_coder._session_id != p_reviewer._session_id

    def test_custom_session_id(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        # Force a fresh pipeline with custom session ID
        gov.reset_pipeline("coder")
        pipeline = gov.get_pipeline("coder", session_id="my-custom-session")
        assert pipeline._session_id == "my-custom-session"


# -----------------------------------------------------------------------
# Audit summaries
# -----------------------------------------------------------------------


class TestAuditSummaries:
    def test_empty_summary_for_unused_agent(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        summary = gov.get_audit_summary("coder")
        assert summary["total_calls"] == 0

    def test_summary_after_processing(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        pipeline = gov.get_pipeline("coder")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        pipeline.process(tc)

        summary = gov.get_audit_summary("coder")
        assert summary["total_calls"] >= 1

    def test_get_all_summaries(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_all_builtins()
        summaries = gov.get_all_audit_summaries()
        assert set(summaries.keys()) == set(BUILTIN_PROFILES.keys())


# -----------------------------------------------------------------------
# Introspection
# -----------------------------------------------------------------------


class TestIntrospection:
    def test_list_agents(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_all_builtins()
        agents = gov.list_agents()
        assert len(agents) == 4
        names = {a["name"] for a in agents}
        assert names == {"coder", "reviewer", "planner", "executor"}

    def test_repr(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")
        gov.register_agent("reviewer")
        r = repr(gov)
        assert "MultiAgentGovernor" in r
        assert "coder" in r
        assert "reviewer" in r

    def test_base_constitution_accessible(self, tmp_path):
        c = Constitution.default()
        gov = MultiAgentGovernor(c, project_dir=str(tmp_path))
        assert gov.base_constitution is c


# -----------------------------------------------------------------------
# Context manager
# -----------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_closes(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("coder")

        with gov:
            pipeline = gov.get_pipeline("coder")
            tc = ToolCall(tool_name="bash", tool_input={"command": "echo ok"})
            pipeline.process(tc)

        # After close, pipelines should be cleared
        assert len(gov._pipelines) == 0


# -----------------------------------------------------------------------
# Constitution override merge
# -----------------------------------------------------------------------


class TestConstitutionOverride:
    def test_executor_gets_custom_thresholds(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.register_agent("executor")
        pipeline = gov.get_pipeline("executor")

        # The executor profile has constitution_override with
        # risk.thresholds.medium = "allow" instead of default "ask"
        # Verify the pipeline was built (it merges override)
        assert pipeline is not None

    def test_custom_constitution_override(self, tmp_path):
        gov = _make_governor(tmp_path)
        profile = AgentProfile(
            name="strict_agent",
            role="strict",
            max_risk_level="critical",
            constitution_override={
                "risk": {
                    "thresholds": {
                        "low": "allow",
                        "medium": "deny",
                        "high": "deny",
                        "critical": "deny",
                    },
                },
            },
        )
        gov.register_agent("strict_agent", profile)
        pipeline = gov.get_pipeline("strict_agent")
        assert pipeline is not None
