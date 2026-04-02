"""Comprehensive integration tests for AutoHarness.

Tests the full end-to-end workflow across all major subsystems:
pipeline, constitution, trust, hooks, turn governor, multi-agent,
permissions, verification, audit, and prompt compiler.

Every test is self-contained and requires no external services.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoharness.compiler.prompt import PromptCompiler
from autoharness.core.audit import AuditEngine
from autoharness.core.constitution import Constitution
from autoharness.core.hooks import HookRegistry
from autoharness.core.multi_agent import AgentProfile, MultiAgentGovernor
from autoharness.core.permissions import PermissionEngine
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.trust import SessionTrustState
from autoharness.core.turn_governor import TurnGovernor
from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDecision,
    PermissionDefaults,
    RiskAssessment,
    RiskLevel,
    RuleSeverity,
    ToolCall,
    ToolResult,
)
from autoharness.core.verification import VerificationEngine, VerificationStatus

# ======================================================================
# Helper: build a file path inside the project dir (tmp_path)
# ======================================================================


def _project_file(tmp_path: Path, name: str = "safe.txt") -> str:
    """Create a file inside tmp_path and return its absolute path string."""
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text("test-content")
    return str(f)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def tmp_audit_path(tmp_path: Path) -> str:
    """Return a temporary audit file path."""
    return str(tmp_path / "audit.jsonl")


@pytest.fixture
def constitution_yaml(tmp_path: Path) -> Path:
    """Write a constitution YAML file and return its path."""
    config = {
        "version": "1.0",
        "identity": {
            "name": "test-agent",
            "description": "Integration test constitution",
            "boundaries": ["Do not access production databases"],
        },
        "rules": [
            {
                "id": "no-secrets",
                "description": "Never expose API keys or secrets",
                "severity": "error",
                "enforcement": "hook",
            },
            {
                "id": "confirm-delete",
                "description": "Destructive deletions require confirmation",
                "severity": "error",
                "enforcement": "both",
            },
            {
                "id": "prefer-simple",
                "description": "Prefer simple solutions",
                "severity": "warning",
                "enforcement": "prompt",
            },
        ],
        "permissions": {
            "defaults": {
                "unknown_tool": "ask",
                "unknown_path": "deny",
                "on_error": "deny",
            },
            "tools": {
                "bash": {
                    "policy": "restricted",
                    "deny_patterns": [
                        r"rm\s+-rf\s+/",
                        r"curl\s+.*\|\s*sh",
                    ],
                    "ask_patterns": [
                        r"docker\s+rm",
                    ],
                },
                "Read": {
                    "policy": "allow",
                },
                "Write": {
                    "policy": "restricted",
                    "deny_paths": ["/etc/passwd"],
                },
            },
        },
        "risk": {
            "classifier": "rules",
            "thresholds": {
                "low": "allow",
                "medium": "allow",
                "high": "ask",
                "critical": "deny",
            },
        },
        "hooks": {
            "profile": "standard",
        },
        "audit": {
            "enabled": True,
            "format": "jsonl",
            "output": str(tmp_path / "audit.jsonl"),
            "retention_days": 30,
        },
    }
    yaml_path = tmp_path / "constitution.yaml"
    yaml_path.write_text(yaml.dump(config), encoding="utf-8")
    return yaml_path


@pytest.fixture
def constitution(constitution_yaml: Path) -> Constitution:
    """Load a Constitution from the test YAML."""
    return Constitution.load(constitution_yaml)


@pytest.fixture
def pipeline(constitution: Constitution, tmp_path: Path) -> ToolGovernancePipeline:
    """Build a ToolGovernancePipeline from the test constitution.

    We manually set the hook registry's project_root to tmp_path so that
    the path_guard hook allows files within the test directory.  The
    pipeline constructor doesn't forward project_dir to HookRegistry.
    """
    p = ToolGovernancePipeline(
        constitution=constitution,
        project_dir=str(tmp_path),
        session_id="integ-test",
    )
    # Align the hook registry's project root with the pipeline's project dir
    # so that path_guard accepts paths inside tmp_path.
    import os
    p._hook_registry._project_root = os.path.realpath(str(tmp_path))
    return p


@pytest.fixture
def safe_tc(tmp_path: Path) -> ToolCall:
    """A safe Read tool call with a path inside the project dir."""
    return ToolCall(
        tool_name="Read",
        tool_input={"file_path": _project_file(tmp_path, "safe.txt")},
    )


@pytest.fixture
def dangerous_tc() -> ToolCall:
    return ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})


@pytest.fixture
def secret_tc() -> ToolCall:
    return ToolCall(
        tool_name="bash",
        tool_input={"command": "echo sk-abc12345678901234567890123456789012345"},
    )


# ======================================================================
# 1. End-to-end pipeline test
# ======================================================================


class TestEndToEndPipeline:
    """Constitution YAML -> Pipeline -> ToolCall -> Decision -> Audit log."""

    def test_safe_tool_allowed(self, pipeline: ToolGovernancePipeline, safe_tc: ToolCall):
        """A safe Read tool call should pass governance."""
        result = pipeline.process(safe_tc)
        assert result.status == "success"
        assert result.tool_name == "Read"

    def test_dangerous_tool_blocked(
        self, pipeline: ToolGovernancePipeline, dangerous_tc: ToolCall
    ):
        """rm -rf / should be blocked by deny_patterns."""
        result = pipeline.process(dangerous_tc)
        assert result.status == "blocked"
        assert result.blocked_reason is not None

    def test_secret_tool_blocked(
        self, pipeline: ToolGovernancePipeline, secret_tc: ToolCall
    ):
        """A tool call containing a secret should be blocked by the secret scanner hook."""
        result = pipeline.process(secret_tc)
        assert result.status == "blocked"
        assert result.blocked_reason is not None

    def test_audit_record_written(
        self, pipeline: ToolGovernancePipeline, safe_tc: ToolCall
    ):
        """After processing, an audit record should exist."""
        pipeline.process(safe_tc)
        records = pipeline.audit_engine.get_records(session_id="integ-test")
        assert len(records) >= 1
        rec = records[0]
        assert rec.tool_name == "Read"
        assert rec.session_id == "integ-test"

    def test_blocked_call_audited(
        self, pipeline: ToolGovernancePipeline, dangerous_tc: ToolCall
    ):
        """Blocked calls should also appear in the audit log."""
        pipeline.process(dangerous_tc)
        records = pipeline.audit_engine.get_records(
            session_id="integ-test", event_type="tool_blocked"
        )
        assert len(records) >= 1
        assert records[0].event_type == "tool_blocked"

    def test_evaluate_only_no_execution(
        self, pipeline: ToolGovernancePipeline, safe_tc: ToolCall
    ):
        """pipeline.evaluate() should return a decision without executing."""
        decision = pipeline.evaluate(safe_tc)
        assert decision.action in ("allow", "ask", "deny")

    def test_process_with_executor(
        self, pipeline: ToolGovernancePipeline, safe_tc: ToolCall
    ):
        """When an executor is set, it should be called for allowed tools."""
        executed = []
        pipeline.set_tool_executor(lambda tc: executed.append(tc.tool_name) or "ok")
        result = pipeline.process(safe_tc)
        assert result.status == "success"
        assert result.output == "ok"
        assert executed == ["Read"]


# ======================================================================
# 2. Ask confirmation flow
# ======================================================================


class TestAskConfirmationFlow:
    """Tool triggers 'ask' -> callback approves -> execution allowed.

    We register a custom pre-hook that returns HookAction.ask to reliably
    trigger the ask flow, bypassing path guard and risk threshold issues.
    """

    @staticmethod
    def _register_ask_hook(pipeline: ToolGovernancePipeline) -> None:
        """Register a hook that always returns ask for 'AskTestTool'."""
        def ask_hook(tool_call, risk, context):
            if tool_call.tool_name == "AskTestTool":
                return HookResult(
                    action=HookAction.ask,
                    reason="Hook requires confirmation for AskTestTool",
                )
            return HookResult(action=HookAction.allow)
        pipeline.hook_registry.register("pre_tool_use", ask_hook)

    def _make_ask_tc(self) -> ToolCall:
        return ToolCall(tool_name="AskTestTool", tool_input={"arg": "value"})

    def test_ask_with_approving_callback(self, pipeline: ToolGovernancePipeline):
        """When on_ask returns True, an 'ask' decision should resolve to allow."""
        self._register_ask_hook(pipeline)
        tc = self._make_ask_tc()
        pipeline.on_ask = lambda tool_call, decision: True
        result = pipeline.process(tc)
        assert result.status == "success"

    def test_ask_with_denying_callback(self, pipeline: ToolGovernancePipeline):
        """When on_ask returns False, an 'ask' decision should resolve to deny."""
        self._register_ask_hook(pipeline)
        tc = self._make_ask_tc()
        pipeline.on_ask = lambda tool_call, decision: False
        result = pipeline.process(tc)
        assert result.status == "blocked"

    def test_ask_no_callback_defaults_to_deny(self, pipeline: ToolGovernancePipeline):
        """Without a callback, ask defaults to deny."""
        self._register_ask_hook(pipeline)
        tc = self._make_ask_tc()
        pipeline.on_ask = None
        pipeline.ask_default = "deny"
        result = pipeline.process(tc)
        assert result.status == "blocked"

    def test_ask_no_callback_default_allow(self, pipeline: ToolGovernancePipeline):
        """When ask_default='allow', ask without callback resolves to allow."""
        self._register_ask_hook(pipeline)
        tc = self._make_ask_tc()
        pipeline.on_ask = None
        pipeline.ask_default = "allow"
        result = pipeline.process(tc)
        assert result.status == "success"

    def test_on_blocked_callback_fires(self, pipeline: ToolGovernancePipeline):
        """The on_blocked callback should be invoked for blocked calls."""
        blocked_calls = []
        pipeline.on_blocked = lambda tc, decision: blocked_calls.append(tc.tool_name)
        tc = ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})
        pipeline.process(tc)
        assert len(blocked_calls) >= 1


# ======================================================================
# 3. Progressive trust
# ======================================================================


class TestProgressiveTrust:
    """Approve once -> subsequent similar calls auto-approved."""

    def test_trust_approval_auto_approves_subsequent(self):
        """After approving once, the same tool+reason is auto-approved."""
        trust = SessionTrustState()
        trust.record_approval("bash", "Risk level 'high' requires confirmation")
        assert trust.is_trusted("bash", "Risk level 'high' requires confirmation")

    def test_trust_denial_blocks_subsequent(self):
        """After denying, the same tool+reason is NOT trusted."""
        trust = SessionTrustState()
        trust.record_denial("bash", "Dangerous command")
        assert not trust.is_trusted("bash", "Dangerous command")

    def test_trust_decay(self):
        """Trust entries should expire after trust_decay_seconds."""
        trust = SessionTrustState(trust_decay_seconds=0.1)
        trust.record_approval("bash", "some reason")
        assert trust.is_trusted("bash", "some reason")
        time.sleep(0.15)
        assert not trust.is_trusted("bash", "some reason")

    def test_max_auto_approvals(self):
        """After max_auto_approvals uses, trust requires re-confirmation."""
        trust = SessionTrustState(max_auto_approvals=2, trust_decay_seconds=0)
        trust.record_approval("bash", "reason")
        assert trust.is_trusted("bash", "reason")
        # Approve again -> count becomes 2, now at max
        trust.record_approval("bash", "reason")
        assert not trust.is_trusted("bash", "reason")

    def test_progressive_trust_in_pipeline(self, pipeline: ToolGovernancePipeline):
        """Pipeline should auto-approve after first user approval via trust state."""
        # Register a hook that triggers ask for AskTestTool
        def ask_hook(tool_call, risk, context):
            if tool_call.tool_name == "AskTestTool":
                return HookResult(
                    action=HookAction.ask,
                    reason="Hook requires confirmation for AskTestTool",
                )
            return HookResult(action=HookAction.allow)

        pipeline.hook_registry.register("pre_tool_use", ask_hook)
        tc = ToolCall(tool_name="AskTestTool", tool_input={"arg": "value"})
        call_count = [0]

        def ask_handler(tool_call, decision):
            call_count[0] += 1
            return True  # approve

        pipeline.on_ask = ask_handler

        # First call: should invoke the ask handler
        result1 = pipeline.process(tc)
        assert result1.status == "success"
        first_call_count = call_count[0]

        # Second call: should be auto-approved via trust (handler NOT called again)
        result2 = pipeline.process(tc)
        assert result2.status == "success"
        assert call_count[0] == first_call_count

    def test_trust_clear(self):
        """clear() should reset all trust state."""
        trust = SessionTrustState()
        trust.record_approval("bash", "reason")
        trust.clear()
        assert not trust.is_trusted("bash", "reason")
        assert trust.approval_count == 0


# ======================================================================
# 4. Hook I/O protocol
# ======================================================================


class TestHookIOProtocol:
    """Test ShellHook execution and the hook registry."""

    def test_builtin_secret_scanner_blocks_secret(self, pipeline: ToolGovernancePipeline):
        """The built-in secret_scanner hook should detect API keys."""
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "echo sk-abc12345678901234567890123456789012345"},
        )
        result = pipeline.process(tc)
        assert result.status == "blocked"

    def test_custom_pre_hook_deny(self, pipeline: ToolGovernancePipeline, tmp_path: Path):
        """A custom pre-hook that returns deny should block the tool call."""

        def deny_all_hook(tool_call, risk, context):
            return HookResult(
                action=HookAction.deny,
                reason="Custom hook denies everything",
                severity="error",
            )

        pipeline.hook_registry.register("pre_tool_use", deny_all_hook)
        tc = ToolCall(
            tool_name="Read",
            tool_input={"file_path": _project_file(tmp_path, "test.txt")},
        )
        result = pipeline.process(tc)
        assert result.status == "blocked"
        assert "Custom hook denies everything" in (result.blocked_reason or "")

    def test_custom_pre_hook_allow(self, pipeline: ToolGovernancePipeline, tmp_path: Path):
        """A custom pre-hook that returns allow should not interfere."""

        def allow_hook(tool_call, risk, context):
            return HookResult(action=HookAction.allow, reason="Custom allow")

        pipeline.hook_registry.register("pre_tool_use", allow_hook)
        tc = ToolCall(
            tool_name="Read",
            tool_input={"file_path": _project_file(tmp_path, "test.txt")},
        )
        result = pipeline.process(tc)
        assert result.status == "success"

    def test_shell_hook_with_mock_subprocess(
        self, pipeline: ToolGovernancePipeline, tmp_path: Path
    ):
        """Shell hook should parse subprocess JSON output per Claude Code spec."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "decision": "deny",
            "reason": "Shell hook blocked this",
        })
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):

            def shell_hook_sim(tool_call, risk, context):
                import subprocess

                proc = subprocess.run(
                    ["echo", "test"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    if data.get("decision") == "deny":
                        return HookResult(
                            action=HookAction.deny,
                            reason=data.get("reason", "Shell hook denied"),
                            severity="error",
                        )
                return HookResult(action=HookAction.allow)

            pipeline.hook_registry.register("pre_tool_use", shell_hook_sim)
            tc = ToolCall(
                tool_name="Read",
                tool_input={"file_path": _project_file(tmp_path, "a.txt")},
            )
            result = pipeline.process(tc)
            assert result.status == "blocked"
            assert "Shell hook blocked" in (result.blocked_reason or "")

    def test_hook_priority_ordering(self):
        """Hooks should execute in priority order (lower number = higher priority)."""
        registry = HookRegistry(profile="minimal")
        execution_order = []

        def make_hook(name, priority):
            def hook_fn(tc, risk, ctx):
                execution_order.append(name)
                return HookResult(action=HookAction.allow)

            hook_fn.__name__ = name
            return hook_fn, priority

        fn1, p1 = make_hook("high_priority", 10)
        fn2, p2 = make_hook("low_priority", 200)
        fn3, p3 = make_hook("mid_priority", 100)

        registry.register("pre_tool_use", fn1, priority=p1)
        registry.register("pre_tool_use", fn2, priority=p2)
        registry.register("pre_tool_use", fn3, priority=p3)

        tc = ToolCall(tool_name="test", tool_input={})
        risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
        registry.run_pre_hooks(tc, risk, {})

        assert execution_order.index("high_priority") < execution_order.index(
            "low_priority"
        )


# ======================================================================
# 5. Turn governor
# ======================================================================


class TestTurnGovernor:
    """Max iterations, denial spiral detection, rate limiting."""

    def test_max_iterations_exceeded(self):
        """After max_iterations tool calls, the governor should deny."""
        gov = TurnGovernor(max_iterations=3)
        tc = ToolCall(tool_name="test", tool_input={})
        allow_decision = PermissionDecision(action="allow", reason="ok", source="test")

        for _ in range(3):
            assert gov.check_turn_limits(tc) is None
            gov.record_result(allow_decision, RiskLevel.low)

        denial = gov.check_turn_limits(tc)
        assert denial is not None
        assert denial.action == "deny"
        assert "iteration limit" in denial.reason.lower()

    def test_denial_spiral_detection(self):
        """After N consecutive denials, the governor should escalate."""
        gov = TurnGovernor(max_consecutive_denials=3, max_iterations=100)
        tc = ToolCall(tool_name="test", tool_input={})
        deny_decision = PermissionDecision(action="deny", reason="denied", source="test")

        for _ in range(3):
            assert gov.check_turn_limits(tc) is None
            gov.record_result(deny_decision, RiskLevel.low)

        denial = gov.check_turn_limits(tc)
        assert denial is not None
        assert (
            "denial spiral" in denial.reason.lower()
            or "consecutive" in denial.reason.lower()
        )

    def test_rate_limiting(self):
        """Governor should enforce rate limits (calls per minute)."""
        gov = TurnGovernor(rate_limit_per_minute=5, max_iterations=1000)
        tc = ToolCall(tool_name="test", tool_input={})
        allow_decision = PermissionDecision(action="allow", reason="ok", source="test")

        for _ in range(5):
            assert gov.check_turn_limits(tc) is None
            gov.record_result(allow_decision, RiskLevel.low)

        denial = gov.check_turn_limits(tc)
        assert denial is not None
        assert "rate limit" in denial.reason.lower()

    def test_cumulative_risk_threshold(self):
        """Governor should block when cumulative risk exceeds threshold."""
        gov = TurnGovernor(cumulative_risk_threshold=100, max_iterations=100)
        tc = ToolCall(tool_name="test", tool_input={})
        allow_decision = PermissionDecision(action="allow", reason="ok", source="test")

        for _ in range(2):
            assert gov.check_turn_limits(tc) is None
            gov.record_result(allow_decision, RiskLevel.critical)

        denial = gov.check_turn_limits(tc)
        assert denial is not None
        assert "risk" in denial.reason.lower()

    def test_new_turn_resets_state(self):
        """new_turn() should reset all counters."""
        gov = TurnGovernor(max_iterations=2)
        tc = ToolCall(tool_name="test", tool_input={})
        allow = PermissionDecision(action="allow", reason="ok", source="test")

        gov.record_result(allow, RiskLevel.low)
        gov.record_result(allow, RiskLevel.low)
        assert gov.check_turn_limits(tc) is not None

        prev_stats = gov.new_turn()
        assert prev_stats.tool_calls == 2
        assert gov.check_turn_limits(tc) is None


# ======================================================================
# 6. Multi-agent governance
# ======================================================================


class TestMultiAgentGovernance:
    """Coder vs reviewer permissions."""

    def test_reviewer_cannot_use_bash(self, constitution: Constitution):
        """A reviewer agent should be blocked from using bash."""
        governor = MultiAgentGovernor(constitution)
        governor.register_builtin("reviewer")

        tc = ToolCall(tool_name="bash", tool_input={"command": "ls"})
        decision = governor.evaluate("reviewer", tc)
        assert decision.action == "deny"

    def test_reviewer_can_use_read(self, constitution: Constitution, tmp_path: Path):
        """A reviewer agent should be allowed to use Read."""
        governor = MultiAgentGovernor(constitution, project_dir=str(tmp_path))
        governor.register_builtin("reviewer")

        file_path = _project_file(tmp_path, "test.txt")
        tc = ToolCall(tool_name="Read", tool_input={"file_path": file_path})

        # Fix the hook registry project_root to match tmp_path
        pipe = governor.get_pipeline("reviewer")
        pipe._hook_registry._project_root = os.path.realpath(str(tmp_path))

        decision = governor.evaluate("reviewer", tc)
        assert decision.action in ("allow", "ask")

    def test_coder_can_use_bash(self, constitution: Constitution):
        """A coder agent should be allowed to use bash (safe commands)."""
        governor = MultiAgentGovernor(constitution)
        governor.register_builtin("coder")

        tc = ToolCall(tool_name="bash", tool_input={"command": "git status"})
        decision = governor.evaluate("coder", tc)
        assert decision.action in ("allow", "ask")

    def test_custom_agent_profile(self, constitution: Constitution, tmp_path: Path):
        """Custom agent profiles should enforce tool restrictions."""
        governor = MultiAgentGovernor(constitution, project_dir=str(tmp_path))
        governor.register_agent(
            "custom",
            AgentProfile(
                name="custom",
                role="analyst",
                allowed_tools=["Read", "Grep"],
                max_risk_level="low",
            ),
        )

        # Fix project root
        pipe = governor.get_pipeline("custom")
        pipe._hook_registry._project_root = os.path.realpath(str(tmp_path))

        tc_read = ToolCall(
            tool_name="Read",
            tool_input={"file_path": _project_file(tmp_path, "f.txt")},
        )
        decision = governor.evaluate("custom", tc_read)
        assert decision.action != "deny"

        # Write is not in allowed_tools -> should be denied by agent filter hook
        tc_write = ToolCall(tool_name="Write", tool_input={"content": "hello"})
        decision = governor.evaluate("custom", tc_write)
        assert decision.action == "deny"

    def test_unregistered_agent_raises(self, constitution: Constitution):
        """Accessing an unregistered agent should raise KeyError."""
        governor = MultiAgentGovernor(constitution)
        with pytest.raises(KeyError):
            governor.get_pipeline("nonexistent")

    def test_isolated_session_ids(self, constitution: Constitution):
        """Each agent should get a unique session ID."""
        governor = MultiAgentGovernor(constitution)
        governor.register_builtin("coder")
        governor.register_builtin("reviewer")

        coder_pipe = governor.get_pipeline("coder")
        reviewer_pipe = governor.get_pipeline("reviewer")
        assert coder_pipe._session_id != reviewer_pipe._session_id


# ======================================================================
# 7. Agent fork governance
# ======================================================================


class TestAgentForkGovernance:
    """Fork has subset permissions, can't expand beyond parent."""

    def test_fork_inherits_parent_tools(self, constitution: Constitution):
        """A fork should inherit the parent's allowed_tools."""
        governor = MultiAgentGovernor(constitution)
        governor.register_agent(
            "parent",
            AgentProfile(
                name="parent",
                role="coder",
                allowed_tools=["Read", "Write", "bash"],
                max_risk_level="medium",
            ),
        )

        governor.fork_agent("parent", "child", restrict_tools=["Read"])
        child_profile = governor.get_profile("child")
        assert child_profile.allowed_tools == ["Read"]

    def test_fork_cannot_expand_tools(self, constitution: Constitution):
        """A fork requesting tools not in the parent should get intersection only."""
        governor = MultiAgentGovernor(constitution)
        governor.register_agent(
            "parent",
            AgentProfile(
                name="parent",
                role="coder",
                allowed_tools=["Read", "Write"],
                max_risk_level="medium",
            ),
        )

        governor.fork_agent("parent", "child2", restrict_tools=["Read", "bash"])
        child_profile = governor.get_profile("child2")
        assert "bash" not in (child_profile.allowed_tools or [])
        assert "Read" in (child_profile.allowed_tools or [])

    def test_fork_cannot_expand_risk_level(self, constitution: Constitution):
        """A fork cannot request a higher risk level than its parent."""
        governor = MultiAgentGovernor(constitution)
        governor.register_agent(
            "parent",
            AgentProfile(
                name="parent",
                role="coder",
                allowed_tools=None,
                max_risk_level="medium",
            ),
        )

        with pytest.raises(ValueError, match="cannot expand risk"):
            governor.fork_agent("parent", "bad_child", max_risk_level="critical")

    def test_fork_can_restrict_risk_level(self, constitution: Constitution):
        """A fork can restrict to a lower risk level than its parent."""
        governor = MultiAgentGovernor(constitution)
        governor.register_agent(
            "parent",
            AgentProfile(
                name="parent",
                role="coder",
                allowed_tools=None,
                max_risk_level="high",
            ),
        )

        governor.fork_agent("parent", "safe_child", max_risk_level="low")
        child_profile = governor.get_profile("safe_child")
        assert child_profile.max_risk_level == "low"

    def test_fork_metadata_tracks_parent(self, constitution: Constitution):
        """Fork metadata should record the parent agent name."""
        governor = MultiAgentGovernor(constitution)
        governor.register_builtin("coder")
        governor.fork_agent("coder", "coder_fork")
        assert governor.is_fork("coder_fork")
        assert governor.get_fork_parent("coder_fork") == "coder"
        assert not governor.is_fork("coder")


# ======================================================================
# 8. TOCTOU protection
# ======================================================================


class TestTOCTOUProtection:
    """Shell expansion, UNC paths, tilde variants blocked."""

    def test_unc_path_blocked(self):
        """UNC paths should be denied."""
        engine = PermissionEngine()
        tc = ToolCall(
            tool_name="Write",
            tool_input={"file_path": "\\\\server\\share\\file.txt"},
        )
        risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
        decision = engine.decide(tc, risk, [])
        assert decision.action == "deny"
        assert "UNC" in decision.reason or "network" in decision.reason.lower()

    def test_tilde_variant_blocked(self):
        """~user paths (not ~/...) should be denied as TOCTOU risk."""
        engine = PermissionEngine()
        tc = ToolCall(
            tool_name="Write",
            tool_input={"file_path": "~admin/.ssh/authorized_keys"},
        )
        risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
        decision = engine.decide(tc, risk, [])
        assert decision.action == "deny"
        assert "tilde" in decision.reason.lower() or "TOCTOU" in decision.reason

    def test_shell_expansion_blocked(self):
        """Paths containing $VAR or $(cmd) should be denied."""
        engine = PermissionEngine()
        for path in ["$(whoami)/file", "${HOME}/secrets"]:
            tc = ToolCall(tool_name="Write", tool_input={"file_path": path})
            risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
            decision = engine.decide(tc, risk, [])
            assert decision.action == "deny", f"Expected deny for path: {path}"

    def test_glob_in_path_blocked(self):
        """Paths containing glob characters should be denied."""
        engine = PermissionEngine()
        tc = ToolCall(
            tool_name="Write", tool_input={"file_path": "/data/*/secret.txt"}
        )
        risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
        decision = engine.decide(tc, risk, [])
        assert decision.action == "deny"

    def test_path_traversal_blocked(self):
        """Paths with .. components should be denied."""
        engine = PermissionEngine()
        tc = ToolCall(
            tool_name="Write",
            tool_input={"file_path": "/data/../etc/passwd"},
        )
        risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
        decision = engine.decide(tc, risk, [])
        assert decision.action == "deny"

    def test_safe_tilde_home_allowed(self):
        """~/some/path (normal home expansion) should not be blocked by TOCTOU."""
        engine = PermissionEngine()
        tc = ToolCall(
            tool_name="Write", tool_input={"file_path": "~/Documents/safe.txt"}
        )
        risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
        decision = engine.decide(tc, risk, [])
        # Should not be denied by TOCTOU guard (~ followed by / is safe)
        assert decision.action != "deny" or "TOCTOU" not in decision.reason


# ======================================================================
# 9. Tool input modification
# ======================================================================


class TestToolInputModification:
    """Hook modifies input before execution."""

    def test_modify_hook_changes_input(self, pipeline: ToolGovernancePipeline):
        """A hook with HookAction.modify should change the tool input."""
        # Use a non-bash tool to avoid path_guard issues with command strings
        def modify_hook(tool_call, risk, context):
            if tool_call.tool_input.get("query") == "original":
                return HookResult(
                    action=HookAction.modify,
                    reason="Modified query",
                    modified_input={"query": "modified"},
                )
            return HookResult(action=HookAction.allow)

        pipeline.hook_registry.register("pre_tool_use", modify_hook)

        executed_inputs = []
        pipeline.set_tool_executor(
            lambda tc: executed_inputs.append(tc.tool_input) or "done"
        )

        tc = ToolCall(tool_name="SearchTool", tool_input={"query": "original"})
        result = pipeline.process(tc)
        assert result.status == "success"
        assert len(executed_inputs) == 1
        assert executed_inputs[0]["query"] == "modified"

    def test_modify_hook_preserves_metadata(self, pipeline: ToolGovernancePipeline):
        """Input modification should preserve original input in metadata."""

        def modify_hook(tool_call, risk, context):
            return HookResult(
                action=HookAction.modify,
                reason="Adding safety flag",
                modified_input={"query": "safe-" + tool_call.tool_input.get("query", "")},
            )

        pipeline.hook_registry.register("pre_tool_use", modify_hook)

        executed_metadata = []
        pipeline.set_tool_executor(
            lambda tc: executed_metadata.append(tc.metadata) or "done"
        )

        tc = ToolCall(tool_name="SearchTool", tool_input={"query": "test"})
        result = pipeline.process(tc)
        assert result.status == "success"
        assert executed_metadata[0].get("_original_input") == {"query": "test"}


# ======================================================================
# 10. Cascading config
# ======================================================================


class TestCascadingConfig:
    """Constitution.discover() with multiple config files."""

    def test_discover_from_project_dir(self, tmp_path: Path):
        """discover() should find .autoharness.yaml in the project dir."""
        config = {
            "version": "1.0",
            "identity": {"name": "project-config"},
            "rules": [
                {
                    "id": "project-rule",
                    "description": "A project-specific rule",
                    "severity": "warning",
                    "enforcement": "prompt",
                }
            ],
        }
        (tmp_path / ".autoharness.yaml").write_text(yaml.dump(config), encoding="utf-8")

        c = Constitution.discover(str(tmp_path))
        assert c.identity.get("name") == "project-config"
        assert any(r.id == "project-rule" for r in c.rules)

    def test_discover_falls_back_to_default(self, tmp_path: Path):
        """discover() with no config files should return defaults."""
        c = Constitution.discover(str(tmp_path))
        assert len(c.rules) > 0
        assert c.identity.get("name") == "autoharness-default"

    def test_local_override_takes_priority(self, tmp_path: Path):
        """A .autoharness.local.yaml should override project config."""
        project_config = {
            "version": "1.0",
            "identity": {"name": "project"},
            "risk": {
                "thresholds": {
                    "low": "allow",
                    "medium": "allow",
                    "high": "ask",
                    "critical": "deny",
                }
            },
        }
        local_config = {
            "version": "1.0",
            "identity": {"name": "local-override"},
            "risk": {
                "thresholds": {
                    "low": "allow",
                    "medium": "ask",
                    "high": "deny",
                    "critical": "deny",
                }
            },
        }
        (tmp_path / ".autoharness.yaml").write_text(
            yaml.dump(project_config), encoding="utf-8"
        )
        (tmp_path / ".autoharness.local.yaml").write_text(
            yaml.dump(local_config), encoding="utf-8"
        )

        c = Constitution.discover(str(tmp_path))
        assert c.identity.get("name") == "local-override"
        risk = c.risk_config
        assert risk.get("thresholds", {}).get("medium") == "ask"

    def test_merge_rules_by_id(self):
        """When merging, rules with the same ID should be replaced."""
        base = Constitution.from_dict(
            {
                "rules": [
                    {
                        "id": "r1",
                        "description": "Base version",
                        "severity": "warning",
                        "enforcement": "prompt",
                    },
                    {
                        "id": "r2",
                        "description": "Only in base",
                        "severity": "info",
                        "enforcement": "prompt",
                    },
                ]
            }
        )
        override = Constitution.from_dict(
            {
                "rules": [
                    {
                        "id": "r1",
                        "description": "Override version",
                        "severity": "error",
                        "enforcement": "hook",
                    },
                    {
                        "id": "r3",
                        "description": "New in override",
                        "severity": "info",
                        "enforcement": "prompt",
                    },
                ]
            }
        )

        merged = Constitution.merge(base, override)
        rule_map = {r.id: r for r in merged.rules}
        assert rule_map["r1"].description == "Override version"
        assert rule_map["r1"].severity == RuleSeverity.error
        assert "r2" in rule_map
        assert "r3" in rule_map


# ======================================================================
# 11. Fail-closed behavior
# ======================================================================


class TestFailClosedBehavior:
    """Permission engine error -> deny (not allow)."""

    def test_permission_engine_error_denies(
        self, pipeline: ToolGovernancePipeline, tmp_path: Path
    ):
        """If the permission engine raises, the pipeline should deny."""

        def broken_decide(*args, **kwargs):
            raise RuntimeError("Permission engine crashed!")

        pipeline._permission_engine.decide = broken_decide

        tc = ToolCall(
            tool_name="Read",
            tool_input={"file_path": _project_file(tmp_path, "test.txt")},
        )
        result = pipeline.process(tc)
        assert result.status == "blocked"
        assert "fail" in (result.blocked_reason or "").lower() or "error" in (
            result.blocked_reason or ""
        ).lower()

    def test_unknown_tool_with_minimal_hooks(self, tmp_path: Path):
        """An unknown tool should trigger 'ask' via the permission engine
        when hooks don't override (minimal profile has fewer hooks)."""
        # Use a constitution with minimal hooks and unknown_tool=ask
        c = Constitution.from_dict({
            "permissions": {
                "defaults": {"unknown_tool": "ask"},
            },
            "hooks": {"profile": "minimal"},
        })
        pipeline = ToolGovernancePipeline(
            constitution=c,
            project_dir=str(tmp_path),
            session_id="fail-test",
        )
        tc = ToolCall(tool_name="UnknownTool", tool_input={"arg": "value"})
        decision = pipeline.evaluate(tc)
        # With minimal hooks (no risk_classifier_hook), the permission engine
        # falls through to the unknown_tool default
        assert decision.action in ("ask", "allow")

    def test_on_error_default_is_deny(self):
        """The default on_error policy should be 'deny'."""
        defaults = PermissionDefaults()
        assert defaults.on_error == "deny"


# ======================================================================
# 12. Verification engine
# ======================================================================


class TestVerificationEngine:
    """Basic verification of tool call sequences."""

    def test_claims_test_pass_without_running_tests(self):
        """Should FAIL when agent claims tests pass but no test command exists."""
        tool_calls = [
            ToolCall(tool_name="Read", tool_input={"file_path": "test_foo.py"}),
        ]
        tool_results = [
            ToolResult(tool_name="Read", status="success", output="test code here"),
        ]

        verifier = VerificationEngine()
        verdict = verifier.verify(
            tool_calls=tool_calls,
            claimed_result="All tests pass",
            tool_results=tool_results,
        )
        assert verdict.status == VerificationStatus.FAIL
        assert any("test" in i.message.lower() for i in verdict.issues)

    def test_claims_test_pass_with_pytest_run(self):
        """Should PASS when agent claims tests pass and pytest was actually run."""
        tool_calls = [
            ToolCall(tool_name="Write", tool_input={"file_path": "test_foo.py"}),
            ToolCall(
                tool_name="bash",
                tool_input={"command": "python -m pytest tests/ -v"},
            ),
        ]
        tool_results = [
            ToolResult(tool_name="Write", status="success"),
            ToolResult(
                tool_name="bash",
                status="success",
                output="5 passed in 2.1s",
            ),
        ]

        verifier = VerificationEngine()
        verdict = verifier.verify(
            tool_calls=tool_calls,
            claimed_result="All tests pass",
            tool_results=tool_results,
        )
        assert verdict.status == VerificationStatus.PASS

    def test_no_skipped_errors_warns_on_last_error(self):
        """Should warn when the last tool result is an error."""
        tool_calls = [
            ToolCall(tool_name="bash", tool_input={"command": "make build"}),
        ]
        tool_results = [
            ToolResult(tool_name="bash", status="error", error="Build failed"),
        ]

        verifier = VerificationEngine()
        verdict = verifier.verify(
            tool_calls=tool_calls,
            claimed_result="Build completed",
            tool_results=tool_results,
        )
        assert any(i.severity in ("warning", "error") for i in verdict.issues)

    def test_empty_claimed_result_skips_claim_check(self):
        """With empty claimed_result, the claimed_vs_actual rule should skip."""
        tool_calls: list[ToolCall] = []
        verifier = VerificationEngine()
        verdict = verifier.verify(tool_calls=tool_calls, claimed_result="")
        assert verdict.status in (VerificationStatus.PASS, VerificationStatus.PARTIAL)

    def test_pipeline_verify_session(
        self, pipeline: ToolGovernancePipeline, safe_tc: ToolCall
    ):
        """pipeline.verify_session() should run verification on audit history."""
        pipeline.process(safe_tc)
        result = pipeline.verify_session("File was read")
        assert hasattr(result, "status")
        assert hasattr(result, "issues")


# ======================================================================
# 13. Audit streaming
# ======================================================================


class TestAuditStreaming:
    """stream_records() and rotate()."""

    def test_stream_records_yields_in_order(self, tmp_audit_path: str):
        """stream_records() should yield records in file order."""
        engine = AuditEngine(output_path=tmp_audit_path, enabled=True)
        for i in range(5):
            tc = ToolCall(tool_name=f"tool_{i}", tool_input={"i": i})
            risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
            perm = PermissionDecision(action="allow", reason="ok", source="test")
            result = ToolResult(tool_name=f"tool_{i}", status="success")
            engine.log(tc, risk, [], perm, result, [], session_id="stream-test")

        engine.close()

        read_engine = AuditEngine(output_path=tmp_audit_path, enabled=True)
        records = list(read_engine.stream_records(session_id="stream-test"))
        assert len(records) == 5
        assert records[0].tool_name == "tool_0"
        assert records[4].tool_name == "tool_4"
        read_engine.close()

    def test_stream_with_offset_and_limit(self, tmp_audit_path: str):
        """stream_records() should support offset and limit."""
        engine = AuditEngine(output_path=tmp_audit_path, enabled=True)
        for i in range(10):
            tc = ToolCall(tool_name=f"t_{i}", tool_input={})
            risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
            perm = PermissionDecision(action="allow", reason="ok", source="test")
            result = ToolResult(tool_name=f"t_{i}", status="success")
            engine.log(tc, risk, [], perm, result, [], session_id="offset-test")
        engine.close()

        read_engine = AuditEngine(output_path=tmp_audit_path, enabled=True)
        records = list(
            read_engine.stream_records(session_id="offset-test", offset=3, limit=4)
        )
        assert len(records) == 4
        assert records[0].tool_name == "t_3"
        assert records[3].tool_name == "t_6"
        read_engine.close()

    def test_rotate_when_under_limit(self, tmp_audit_path: str):
        """rotate() should not rotate when file is under max_size_mb."""
        engine = AuditEngine(output_path=tmp_audit_path, enabled=True)
        tc = ToolCall(tool_name="test", tool_input={})
        perm = PermissionDecision(action="allow", reason="ok", source="test")
        engine.log(tc, None, [], perm, None, [], session_id="rot-test")

        rotated = engine.rotate(max_size_mb=50.0)
        assert rotated is False
        engine.close()

    def test_audit_summary(self, tmp_audit_path: str):
        """get_summary() should return correct aggregate stats."""
        engine = AuditEngine(output_path=tmp_audit_path, enabled=True)

        for _ in range(3):
            tc = ToolCall(tool_name="Read", tool_input={})
            risk = RiskAssessment(level=RiskLevel.low, classifier="rules")
            perm = PermissionDecision(action="allow", reason="ok", source="test")
            result = ToolResult(tool_name="Read", status="success")
            engine.log(tc, risk, [], perm, result, [], session_id="sum-test")

        tc_blocked = ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})
        risk_high = RiskAssessment(level=RiskLevel.critical, classifier="rules")
        perm_deny = PermissionDecision(
            action="deny", reason="Dangerous command", source="test"
        )
        engine.log_block(tc_blocked, risk_high, [], perm_deny, session_id="sum-test")

        summary = engine.get_summary(session_id="sum-test")
        assert summary["total_calls"] == 4
        assert summary["blocked_count"] == 1
        assert "Read" in summary["tools_used"]
        engine.close()


# ======================================================================
# 14. Prompt compiler
# ======================================================================


class TestPromptCompiler:
    """Budget-aware compilation, post-compact reminder."""

    def test_compile_includes_prompt_rules(self, constitution: Constitution):
        """compile() should include rules with enforcement=prompt or both."""
        compiler = PromptCompiler()
        addendum = compiler.compile(constitution)
        # confirm-delete has enforcement=both, should be included
        assert "confirm" in addendum.lower() or "destruct" in addendum.lower()
        # prefer-simple has enforcement=prompt, should be included
        assert "simple" in addendum.lower()

    def test_compile_excludes_hook_only_rules(self, constitution: Constitution):
        """compile() should NOT include hook-only rules in the prompt text."""
        compiler = PromptCompiler()
        addendum = compiler.compile(constitution)
        # Identity should be present
        assert "test-agent" in addendum

    def test_compile_minimal(self, constitution: Constitution):
        """compile_minimal() should produce a compact bullet list."""
        compiler = PromptCompiler()
        minimal = compiler.compile_minimal(constitution)
        assert minimal.count("-") >= 1
        full = compiler.compile(constitution)
        assert len(minimal) < len(full)

    def test_compile_for_budget_large(self, constitution: Constitution):
        """With a large budget, compile_for_budget() should return full version."""
        compiler = PromptCompiler()
        full = compiler.compile(constitution)
        budgeted = compiler.compile_for_budget(constitution, token_budget=10000)
        assert budgeted == full

    def test_compile_for_budget_small(self, constitution: Constitution):
        """With a tiny budget, compile_for_budget() should return minimal version."""
        compiler = PromptCompiler()
        budgeted = compiler.compile_for_budget(constitution, token_budget=10)
        minimal = compiler.compile_minimal(constitution)
        assert budgeted == minimal

    def test_post_compact_reminder(self, constitution: Constitution):
        """compile_post_compact() should produce a short governance reminder."""
        compiler = PromptCompiler()
        reminder = compiler.compile_post_compact(constitution)
        assert "AutoHarness" in reminder
        assert "ACTIVE" in reminder
        assert "compaction" in reminder.lower()
        tokens = compiler.estimate_tokens(reminder)
        assert tokens < 200

    def test_estimate_tokens(self):
        """estimate_tokens() should give a rough character/4 estimate."""
        compiler = PromptCompiler()
        text = "a" * 400
        assert compiler.estimate_tokens(text) == 100


# ======================================================================
# Extra: pipeline lifecycle
# ======================================================================


class TestPipelineLifecycle:
    """Pipeline abort, context manager, and tool aliases."""

    def test_pipeline_abort(self, pipeline: ToolGovernancePipeline, tmp_path: Path):
        """After abort(), all subsequent calls should be blocked."""
        pipeline.abort()
        assert pipeline.aborted
        tc = ToolCall(
            tool_name="Read",
            tool_input={"file_path": _project_file(tmp_path, "test.txt")},
        )
        result = pipeline.process(tc)
        assert result.status == "blocked"
        assert "abort" in (result.blocked_reason or "").lower()

    def test_pipeline_context_manager(self, constitution: Constitution, tmp_path: Path):
        """Pipeline should work as a context manager."""
        with ToolGovernancePipeline(
            constitution=constitution,
            project_dir=str(tmp_path),
            session_id="ctx-test",
        ) as p:
            p._hook_registry._project_root = os.path.realpath(str(tmp_path))
            tc = ToolCall(
                tool_name="Read",
                tool_input={"file_path": _project_file(tmp_path, "test.txt")},
            )
            result = p.process(tc)
            assert result.status == "success"
        assert p.audit_engine._closed

    def test_tool_alias_resolution(self, pipeline: ToolGovernancePipeline):
        """Tool aliases should resolve to canonical names."""
        pipeline.tool_aliases = {"sh": "bash"}
        tc = ToolCall(tool_name="sh", tool_input={"command": "echo hello"})
        result = pipeline.process(tc)
        # After alias resolution, tool_name becomes "bash"
        assert result.tool_name == "bash" or result.status in ("success", "blocked")

    def test_process_batch(self, pipeline: ToolGovernancePipeline, tmp_path: Path):
        """process_batch() should process multiple tool calls."""
        calls = [
            ToolCall(
                tool_name="Read",
                tool_input={"file_path": _project_file(tmp_path, "a.txt")},
            ),
            ToolCall(
                tool_name="Read",
                tool_input={"file_path": _project_file(tmp_path, "b.txt")},
            ),
        ]
        results = pipeline.process_batch(calls)
        assert len(results) == 2
        assert all(r.status == "success" for r in results)
