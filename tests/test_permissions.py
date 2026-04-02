"""Tests for autoharness.core.permissions — PermissionEngine."""

from __future__ import annotations

from autoharness.core.permissions import PermissionEngine
from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDefaults,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolPermission,
)

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _low_risk() -> RiskAssessment:
    return RiskAssessment(level=RiskLevel.low, classifier="rules")


def _make_engine(**kwargs) -> PermissionEngine:
    return PermissionEngine(**kwargs)


# -----------------------------------------------------------------------
# Deny patterns (operation-level)
# -----------------------------------------------------------------------


class TestDenyPatterns:
    def test_deny_rm_rf(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(
                    policy="restricted",
                    deny_patterns=[r"rm\s+-rf\s+/"],
                ),
            }
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"

    def test_deny_pattern_no_match_falls_through(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(
                    policy="restricted",
                    deny_patterns=[r"rm\s+-rf\s+/"],
                ),
            }
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "ls -la"})
        decision = engine.decide(tc, _low_risk(), [])
        # Should not be denied, falls through to tool policy (restricted -> ask)
        assert decision.action != "deny"


# -----------------------------------------------------------------------
# Ask patterns
# -----------------------------------------------------------------------


class TestAskPatterns:
    def test_ask_pattern_match(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(
                    policy="restricted",
                    ask_patterns=[r"git\s+push"],
                ),
            }
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "git push origin main"})
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "ask"


# -----------------------------------------------------------------------
# Allow patterns
# -----------------------------------------------------------------------


class TestAllowPatterns:
    def test_allow_pattern_match(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(
                    policy="restricted",
                    allow_patterns=[r"^git\s+status$"],
                ),
            }
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "git status"})
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "allow"


# -----------------------------------------------------------------------
# Path-level checks
# -----------------------------------------------------------------------


class TestPathLevel:
    def test_deny_path(self):
        engine = _make_engine(
            tools={
                "file_write": ToolPermission(
                    policy="restricted",
                    deny_paths=["/etc/*"],
                ),
            }
        )
        tc = ToolCall(
            tool_name="file_write",
            tool_input={"file_path": "/etc/passwd"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"

    def test_ask_path(self):
        engine = _make_engine(
            tools={
                "file_write": ToolPermission(
                    policy="restricted",
                    ask_paths=["/home/user/important/*"],
                ),
            }
        )
        tc = ToolCall(
            tool_name="file_write",
            tool_input={"file_path": "/home/user/important/data.json"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "ask"

    def test_allow_path(self):
        engine = _make_engine(
            tools={
                "file_write": ToolPermission(
                    policy="restricted",
                    allow_paths=["/tmp/*"],
                ),
            }
        )
        tc = ToolCall(
            tool_name="file_write",
            tool_input={"file_path": "/tmp/safe.txt"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "allow"

    def test_path_traversal_denied(self):
        engine = _make_engine(
            tools={
                "file_write": ToolPermission(policy="restricted"),
            }
        )
        tc = ToolCall(
            tool_name="file_write",
            tool_input={"file_path": "/project/../../../etc/passwd"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"
        assert "traversal" in decision.reason.lower()


# -----------------------------------------------------------------------
# Operation-level checks
# -----------------------------------------------------------------------


class TestOperationLevel:
    def test_deny_operation(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(
                    policy="restricted",
                    deny_patterns=[r"DROP\s+TABLE"],
                ),
            }
        )
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "psql -c 'DROP TABLE users;'"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"

    def test_non_bash_tool_no_command_extraction(self):
        """Non-bash tools should not extract command strings."""
        engine = _make_engine(
            tools={
                "read": ToolPermission(policy="allow"),
            }
        )
        tc = ToolCall(
            tool_name="read",
            tool_input={"file_path": "/tmp/test.txt"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "allow"


# -----------------------------------------------------------------------
# Hook integration
# -----------------------------------------------------------------------


class TestHookIntegration:
    def test_hook_deny_wins(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(policy="allow"),
            }
        )
        hook_deny = HookResult(
            action=HookAction.deny,
            reason="Hook says no",
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "ls"})
        decision = engine.decide(tc, _low_risk(), [hook_deny])
        assert decision.action == "deny"
        assert "hook" in decision.source.lower()

    def test_hook_allow_does_not_override_constitution_deny(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(
                    policy="restricted",
                    deny_patterns=[r"rm\s+-rf"],
                ),
            }
        )
        hook_allow = HookResult(action=HookAction.allow, reason="Hook allows")
        tc = ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})
        decision = engine.decide(tc, _low_risk(), [hook_allow])
        # Constitution deny_patterns should still block
        assert decision.action == "deny"

    def test_hook_ask(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(policy="allow"),
            }
        )
        hook_ask = HookResult(
            action=HookAction.ask,
            reason="Hook wants confirmation",
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        decision = engine.decide(tc, _low_risk(), [hook_ask])
        assert decision.action == "ask"

    def test_multiple_hooks_deny_wins_over_allow(self):
        engine = _make_engine(
            tools={
                "bash": ToolPermission(policy="allow"),
            }
        )
        hooks = [
            HookResult(action=HookAction.allow, reason="Hook 1 allows"),
            HookResult(action=HookAction.deny, reason="Hook 2 denies"),
        ]
        tc = ToolCall(tool_name="bash", tool_input={"command": "echo"})
        decision = engine.decide(tc, _low_risk(), hooks)
        assert decision.action == "deny"


# -----------------------------------------------------------------------
# Defaults for unknown tools
# -----------------------------------------------------------------------


class TestDefaults:
    def test_unknown_tool_default_ask(self):
        engine = _make_engine()
        tc = ToolCall(
            tool_name="unknown_tool",
            tool_input={"arg": "value"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "ask"

    def test_unknown_tool_default_deny(self):
        engine = _make_engine(
            defaults=PermissionDefaults(unknown_tool="deny"),
        )
        tc = ToolCall(
            tool_name="unknown_tool",
            tool_input={"arg": "value"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"

    def test_unknown_tool_default_allow(self):
        engine = _make_engine(
            defaults=PermissionDefaults(unknown_tool="allow"),
        )
        tc = ToolCall(
            tool_name="unknown_tool",
            tool_input={"arg": "value"},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "allow"

    def test_defaults_from_dict(self):
        engine = _make_engine(
            defaults={"unknown_tool": "deny", "unknown_path": "deny", "on_error": "deny"},
        )
        tc = ToolCall(
            tool_name="unknown",
            tool_input={},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"


# -----------------------------------------------------------------------
# Tool policy levels
# -----------------------------------------------------------------------


class TestToolPolicy:
    def test_deny_policy_blocks(self):
        engine = _make_engine(
            tools={
                "dangerous_tool": ToolPermission(policy="deny"),
            }
        )
        tc = ToolCall(
            tool_name="dangerous_tool",
            tool_input={},
        )
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "deny"

    def test_allow_policy_allows(self):
        engine = _make_engine(
            tools={
                "safe_tool": ToolPermission(policy="allow"),
            }
        )
        tc = ToolCall(tool_name="safe_tool", tool_input={})
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "allow"

    def test_restricted_policy_asks(self):
        engine = _make_engine(
            tools={
                "restricted_tool": ToolPermission(policy="restricted"),
            }
        )
        tc = ToolCall(tool_name="restricted_tool", tool_input={})
        decision = engine.decide(tc, _low_risk(), [])
        assert decision.action == "ask"


# -----------------------------------------------------------------------
# Check methods directly
# -----------------------------------------------------------------------


class TestCheckMethods:
    def test_check_tool_level_deny(self):
        engine = _make_engine(
            tools={"blocked": ToolPermission(policy="deny")}
        )
        result = engine.check_tool_level("blocked")
        assert result is not None
        assert result.action == "deny"

    def test_check_tool_level_unknown(self):
        engine = _make_engine()
        result = engine.check_tool_level("unknown_tool")
        assert result is None

    def test_check_tool_level_allowed(self):
        engine = _make_engine(
            tools={"allowed": ToolPermission(policy="allow")}
        )
        result = engine.check_tool_level("allowed")
        assert result is None  # No decision at tool level (not denied)

    def test_check_path_level_none_path(self):
        engine = _make_engine()
        result = engine.check_path_level("bash", None)
        assert result is None

    def test_check_operation_level_none_op(self):
        engine = _make_engine()
        result = engine.check_operation_level("bash", None)
        assert result is None
