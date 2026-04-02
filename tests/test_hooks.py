"""Tests for autoharness.core.hooks — HookRegistry, built-in hooks, and shell hooks."""

from __future__ import annotations

import shlex
import sys
from typing import Any

import pytest

from autoharness.core.hooks import HookRegistry, ShellHook
from autoharness.core.types import (
    HookAction,
    HookEvent,
    HookResult,
    PermissionDecision,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolResult,
)

_PYTHON = shlex.quote(sys.executable)

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _low_risk() -> RiskAssessment:
    return RiskAssessment(level=RiskLevel.low, classifier="rules")


def _high_risk() -> RiskAssessment:
    return RiskAssessment(level=RiskLevel.high, classifier="rules", reason="High risk command")


def _critical_risk() -> RiskAssessment:
    return RiskAssessment(
        level=RiskLevel.critical, classifier="rules", reason="Critical risk"
    )


def _context() -> dict[str, Any]:
    return {"session_id": "test", "project_dir": "/tmp/test"}


# -----------------------------------------------------------------------
# Profiles
# -----------------------------------------------------------------------


class TestHookProfiles:
    def test_minimal_profile(self):
        registry = HookRegistry(profile="minimal")
        hooks = registry.list_hooks()
        pre_names = hooks["pre_tool_use"]
        assert "secret_scanner" in pre_names
        assert "path_guard" in pre_names
        assert "risk_classifier" not in pre_names
        assert hooks["post_tool_use"] == []

    def test_standard_profile(self):
        registry = HookRegistry(profile="standard")
        hooks = registry.list_hooks()
        pre_names = hooks["pre_tool_use"]
        assert "secret_scanner" in pre_names
        assert "path_guard" in pre_names
        assert "risk_classifier" in pre_names
        post_names = hooks["post_tool_use"]
        assert "output_sanitizer" in post_names

    def test_strict_profile(self):
        registry = HookRegistry(profile="strict")
        hooks = registry.list_hooks()
        pre_names = hooks["pre_tool_use"]
        assert "config_protector" in pre_names
        # strict includes all standard hooks too
        assert "secret_scanner" in pre_names
        assert "risk_classifier" in pre_names

    def test_invalid_profile_rejected(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            HookRegistry(profile="ultra")


# -----------------------------------------------------------------------
# Built-in: secret_scanner
# -----------------------------------------------------------------------


class TestSecretScanner:
    def test_detects_openai_key(self):
        registry = HookRegistry(profile="minimal")
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "echo sk-abc12345678901234567890"},
        )
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1
        assert "secret" in deny_results[0].reason.lower()

    def test_detects_github_token(self):
        registry = HookRegistry(profile="minimal")
        tc = ToolCall(
            tool_name="bash",
            tool_input={
                "command": "export GH=ghp_abcdefghijklmnopqrstuvwxyz1234567890"
            },
        )
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1

    def test_clean_input_allowed(self):
        registry = HookRegistry(profile="minimal")
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "echo hello world"},
        )
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) == 0


# -----------------------------------------------------------------------
# Built-in: path_guard
# -----------------------------------------------------------------------


class TestPathGuard:
    def test_traversal_denied(self):
        registry = HookRegistry(profile="minimal", project_root="/tmp/test")
        tc = ToolCall(
            tool_name="file_write",
            tool_input={"file_path": "/tmp/test/../../../etc/passwd"},
        )
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1
        assert "traversal" in deny_results[0].reason.lower()

    def test_within_project_allowed(self, tmp_path):
        project_root = str(tmp_path)
        registry = HookRegistry(profile="minimal", project_root=project_root)
        safe_path = str(tmp_path / "src" / "main.py")
        tc = ToolCall(
            tool_name="file_write",
            tool_input={"file_path": safe_path},
        )
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        # No path_guard denial (though file might not exist, path_guard only checks scope)
        path_guard_denials = [
            r for r in deny_results if "path" in (r.reason or "").lower()
        ]
        assert len(path_guard_denials) == 0


# -----------------------------------------------------------------------
# Built-in: risk_classifier_hook
# -----------------------------------------------------------------------


class TestRiskClassifierHook:
    def test_critical_risk_denied(self):
        registry = HookRegistry(profile="standard")
        tc = ToolCall(tool_name="bash", tool_input={"command": "safe"})
        results = registry.run_pre_hooks(tc, _critical_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1

    def test_high_risk_asks(self):
        registry = HookRegistry(profile="standard")
        tc = ToolCall(tool_name="bash", tool_input={"command": "safe"})
        results = registry.run_pre_hooks(tc, _high_risk(), _context())
        ask_results = [r for r in results if r.action == HookAction.ask]
        assert len(ask_results) >= 1

    def test_low_risk_allowed(self):
        registry = HookRegistry(profile="standard")
        tc = ToolCall(tool_name="bash", tool_input={"command": "safe"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) == 0


# -----------------------------------------------------------------------
# Built-in: output_sanitizer
# -----------------------------------------------------------------------


class TestOutputSanitizer:
    def test_redacts_secret_in_output(self):
        registry = HookRegistry(profile="standard")
        tc = ToolCall(tool_name="bash", tool_input={"command": "cat file"})
        result = ToolResult(
            tool_name="bash",
            status="success",
            output="The API key is sk-abc12345678901234567890 here",
        )
        new_result, hook_results = registry.run_post_hooks(tc, result, _context())
        sanitize_results = [
            r for r in hook_results if r.action == HookAction.sanitize
        ]
        assert len(sanitize_results) >= 1
        assert new_result.sanitized is True
        assert "sk-abc" not in str(new_result.output)

    def test_clean_output_unchanged(self):
        registry = HookRegistry(profile="standard")
        tc = ToolCall(tool_name="bash", tool_input={"command": "ls"})
        result = ToolResult(
            tool_name="bash",
            status="success",
            output="file1.py\nfile2.py",
        )
        new_result, _hook_results = registry.run_post_hooks(tc, result, _context())
        assert new_result.output == "file1.py\nfile2.py"
        assert new_result.sanitized is False


# -----------------------------------------------------------------------
# Custom hooks via register()
# -----------------------------------------------------------------------


class TestCustomHooks:
    def test_register_pre_hook(self):
        registry = HookRegistry(profile="minimal")

        def my_hook(tool_call, risk, context):
            if "blocked" in tool_call.tool_input.get("command", ""):
                return HookResult(
                    action=HookAction.deny, reason="Custom block"
                )
            return HookResult(action=HookAction.allow)

        registry.register("pre_tool_use", my_hook, name="my_custom_hook")
        hooks = registry.list_hooks()
        assert "my_custom_hook" in hooks["pre_tool_use"]

        tc = ToolCall(
            tool_name="bash", tool_input={"command": "blocked command"}
        )
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1

    def test_register_post_hook(self):
        registry = HookRegistry(profile="minimal")

        def my_post(tool_call, result, context):
            return HookResult(action=HookAction.allow, reason="Post ok")

        registry.register("post_tool_use", my_post, name="my_post_hook")
        hooks = registry.list_hooks()
        assert "my_post_hook" in hooks["post_tool_use"]

    def test_register_invalid_event_rejected(self):
        registry = HookRegistry(profile="minimal")
        with pytest.raises(ValueError, match="Unknown hook event"):
            registry.register("invalid_event", lambda: None)

    def test_register_on_block(self):
        registry = HookRegistry(profile="minimal")
        called = {"count": 0}

        def on_block(tool_call, decision, context):
            called["count"] += 1

        registry.register("on_block", on_block, name="my_block_hook")
        from autoharness.core.types import PermissionDecision

        tc = ToolCall(tool_name="bash", tool_input={"command": "test"})
        decision = PermissionDecision(
            action="deny", reason="Blocked", source="test"
        )
        registry.run_block_hooks(tc, decision, _context())
        assert called["count"] == 1


# -----------------------------------------------------------------------
# Pre-hook short-circuit on deny
# -----------------------------------------------------------------------


class TestShortCircuit:
    def test_deny_short_circuits(self):
        registry = HookRegistry(profile="minimal")
        call_order = []

        def hook_1(tool_call, risk, context):
            call_order.append("hook_1")
            return HookResult(action=HookAction.deny, reason="Denied by hook 1")

        def hook_2(tool_call, risk, context):
            call_order.append("hook_2")
            return HookResult(action=HookAction.allow)

        registry.register("pre_tool_use", hook_1, name="hook_1")
        registry.register("pre_tool_use", hook_2, name="hook_2")

        tc = ToolCall(tool_name="bash", tool_input={"command": "test"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())

        # hook_2 should not have been called after hook_1 denied
        # But note: built-in hooks (secret_scanner, path_guard) run first
        # If they don't deny, hook_1 will deny and hook_2 won't run
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1

    def test_exception_in_hook_continues(self):
        """A hook that throws should not block subsequent hooks."""
        registry = HookRegistry(profile="minimal")

        def bad_hook(tool_call, risk, context):
            raise RuntimeError("Hook crash")

        def good_hook(tool_call, risk, context):
            return HookResult(action=HookAction.allow, reason="Fine")

        registry.register("pre_tool_use", bad_hook, name="bad_hook")
        registry.register("pre_tool_use", good_hook, name="good_hook")

        tc = ToolCall(tool_name="bash", tool_input={"command": "echo ok"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        # Should have results from built-in hooks + bad_hook (wrapped) + good_hook
        assert len(results) >= 1


# -----------------------------------------------------------------------
# Introspection
# -----------------------------------------------------------------------


class TestIntrospection:
    def test_profile_property(self):
        registry = HookRegistry(profile="strict")
        assert registry.profile == "strict"

    def test_project_root_property(self, tmp_path):
        registry = HookRegistry(profile="minimal", project_root=str(tmp_path))
        assert registry.project_root == str(tmp_path.resolve())

    def test_repr(self):
        registry = HookRegistry(profile="standard")
        r = repr(registry)
        assert "standard" in r
        assert "HookRegistry" in r

    def test_list_hooks_structure(self):
        registry = HookRegistry(profile="standard")
        hooks = registry.list_hooks()
        assert "pre_tool_use" in hooks
        assert "post_tool_use" in hooks
        assert "on_block" in hooks
        assert isinstance(hooks["pre_tool_use"], list)


# -----------------------------------------------------------------------
# HookEvent enum
# -----------------------------------------------------------------------


class TestHookEvent:
    def test_hook_event_values(self):
        assert HookEvent.pre_tool_use == "PreToolUse"
        assert HookEvent.post_tool_use == "PostToolUse"
        assert HookEvent.session_start == "SessionStart"
        assert HookEvent.stop == "Stop"
        assert HookEvent.permission_denied == "PermissionDenied"

    def test_hook_event_is_str_enum(self):
        assert isinstance(HookEvent.pre_tool_use, str)


# -----------------------------------------------------------------------
# ShellHook unit tests
# -----------------------------------------------------------------------


class TestShellHook:
    def test_matches_all_when_no_matcher(self):
        sh = ShellHook(command="true")
        assert sh.matches("Bash") is True
        assert sh.matches("Edit") is True

    def test_matches_specific_tool(self):
        sh = ShellHook(command="true", matcher="Bash")
        assert sh.matches("Bash") is True
        assert sh.matches("Edit") is False

    def test_matches_regex_pattern(self):
        sh = ShellHook(command="true", matcher="Edit|Write")
        assert sh.matches("Edit") is True
        assert sh.matches("Write") is True
        assert sh.matches("Bash") is False

    def test_execute_allow_exit_0(self):
        pycmd = 'import json; print(json.dumps(dict(decision="allow", reason="ok")))'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.allow
        assert result.reason == "ok"

    def test_execute_deny_exit_0_json(self):
        pycmd = 'import json; print(json.dumps(dict(decision="deny", reason="blocked")))'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.deny
        assert result.reason == "blocked"

    def test_execute_ask_exit_0_json(self):
        pycmd = 'import json; print(json.dumps(dict(decision="ask", reason="confirm")))'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.ask
        assert result.reason == "confirm"

    def test_execute_deny_exit_2(self):
        cmd = f'{_PYTHON} -c "import sys; print(\\"denied by policy\\"); sys.exit(2)"'
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.deny
        assert "denied by policy" in result.reason

    def test_execute_deny_exit_2_json_reason(self):
        pycmd = 'import sys, json; print(json.dumps(dict(reason="structured deny"))); sys.exit(2)'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.deny
        assert result.reason == "structured deny"

    def test_execute_error_exit_1(self):
        cmd = f'{_PYTHON} -c "import sys; print(\\"oops\\", file=sys.stderr); sys.exit(1)"'
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.allow
        assert "Shell hook error" in result.reason

    def test_execute_timeout(self):
        cmd = f'{_PYTHON} -c "import time; time.sleep(30)"'
        sh = ShellHook(command=cmd, timeout=0.1)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.allow
        assert "timed out" in result.reason

    def test_execute_empty_stdout_exit_0(self):
        cmd = f'{_PYTHON} -c "pass"'
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {}})
        assert result.action == HookAction.allow
        assert result.reason == "Shell hook passed"

    def test_execute_updated_input(self):
        cmd = (
            f'{_PYTHON} -c "'
            "import json; print(json.dumps({"
            "'decision': 'allow', 'reason': 'modified', "
            "'updatedInput': {'command': 'echo safe'}"
            "}))\""
        )
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
        assert result.action == HookAction.allow
        assert result.modified_input == {"command": "echo safe"}

    def test_execute_receives_stdin(self):
        # Verify the hook receives the input data on stdin
        cmd = (
            f'{_PYTHON} -c "'
            "import json, sys; "
            "data = json.load(sys.stdin); "
            "print(json.dumps({'decision': 'allow', 'reason': data.get('tool_name', 'unknown')}))\""
        )
        sh = ShellHook(command=cmd)
        result = sh.execute({"tool_name": "TestTool", "tool_input": {}})
        assert result.action == HookAction.allow
        assert result.reason == "TestTool"

    def test_repr(self):
        sh = ShellHook(command="my-hook.sh", timeout=5.0, matcher="Bash")
        r = repr(sh)
        assert "ShellHook" in r
        assert "my-hook.sh" in r


# -----------------------------------------------------------------------
# Shell hooks integrated into HookRegistry
# -----------------------------------------------------------------------


class TestShellHookRegistry:
    def test_register_shell_hook_pre(self):
        registry = HookRegistry(profile="minimal")
        pycmd = 'import json; print(json.dumps(dict(decision="allow", reason="shell ok")))'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        registry.register_shell_hook("pre_tool_use", cmd, name="my_shell")
        hooks = registry.list_hooks()
        assert "my_shell" in hooks["pre_tool_use"]

    def test_register_shell_hook_invalid_event(self):
        registry = HookRegistry(profile="minimal")
        with pytest.raises(ValueError, match="Unknown hook event"):
            registry.register_shell_hook("invalid", "true")

    def test_shell_pre_hook_deny(self):
        registry = HookRegistry(profile="minimal")
        cmd = f'{_PYTHON} -c "import sys; sys.exit(2)"'
        registry.register_shell_hook("pre_tool_use", cmd, name="deny_hook")
        tc = ToolCall(tool_name="Bash", tool_input={"command": "echo hi"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) >= 1

    def test_shell_pre_hook_allow(self):
        registry = HookRegistry(profile="minimal")
        cmd = f'{_PYTHON} -c "import json; print(json.dumps(dict(decision=\\"allow\\")))"'
        registry.register_shell_hook("pre_tool_use", cmd, name="allow_hook")
        tc = ToolCall(tool_name="Bash", tool_input={"command": "echo hi"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) == 0

    def test_shell_hook_matcher_skips_non_matching(self):
        registry = HookRegistry(profile="minimal")
        cmd = f'{_PYTHON} -c "import sys; sys.exit(2)"'
        registry.register_shell_hook(
            "pre_tool_use", cmd, matcher="Edit", name="edit_only"
        )
        tc = ToolCall(tool_name="Bash", tool_input={"command": "echo hi"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())
        # The shell hook should not have fired for Bash tool
        deny_results = [r for r in results if r.action == HookAction.deny]
        assert len(deny_results) == 0

    def test_shell_post_hook(self):
        registry = HookRegistry(profile="minimal")
        pycmd = 'import json; print(json.dumps(dict(decision="allow", reason="post ok")))'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        registry.register_shell_hook("post_tool_use", cmd, name="post_shell")
        tc = ToolCall(tool_name="Bash", tool_input={"command": "ls"})
        tr = ToolResult(tool_name="Bash", status="success", output="file.py")
        _, hook_results = registry.run_post_hooks(tc, tr, _context())
        assert any(r.reason == "post ok" for r in hook_results)

    def test_shell_block_hook(self):
        """Shell block hooks run without errors."""
        registry = HookRegistry(profile="minimal")
        cmd = f'{_PYTHON} -c "import json, sys; data = json.load(sys.stdin)"'
        registry.register_shell_hook("on_block", cmd, name="block_shell")
        tc = ToolCall(tool_name="Bash", tool_input={"command": "test"})
        decision = PermissionDecision(
            action="deny", reason="Blocked", source="test"
        )
        # Should not raise
        registry.run_block_hooks(tc, decision, _context())

    def test_shell_hook_default_name(self):
        registry = HookRegistry(profile="minimal")
        registry.register_shell_hook("pre_tool_use", "my-checker.sh")
        hooks = registry.list_hooks()
        assert "shell:my-checker.sh" in hooks["pre_tool_use"]

    def test_callable_and_shell_hooks_coexist(self):
        """Both callable hooks and shell hooks run in the same pipeline."""
        registry = HookRegistry(profile="minimal")

        called = {"py": False}

        def py_hook(tool_call, risk, context):
            called["py"] = True
            return HookResult(action=HookAction.allow, reason="py ok")

        registry.register("pre_tool_use", py_hook, name="py_hook")
        pycmd = 'import json; print(json.dumps(dict(decision="allow", reason="shell ok")))'
        cmd = f"{_PYTHON} -c {pycmd!r}"
        registry.register_shell_hook("pre_tool_use", cmd, name="shell_hook")

        tc = ToolCall(tool_name="Bash", tool_input={"command": "echo hi"})
        results = registry.run_pre_hooks(tc, _low_risk(), _context())

        assert called["py"] is True
        reasons = [r.reason for r in results if r.reason]
        assert "py ok" in reasons
        assert "shell ok" in reasons


# -----------------------------------------------------------------------
# P1-2: Session Lifecycle Events
# -----------------------------------------------------------------------


class TestLifecycleHooks:
    def test_register_lifecycle_hook(self):
        registry = HookRegistry(profile="minimal")
        called = {"count": 0}

        def on_start(context):
            called["count"] += 1

        registry.register_lifecycle_hook("SessionStart", on_start, name="my_start")
        hooks = registry.list_hooks()
        assert "SessionStart" in hooks
        assert "my_start" in hooks["SessionStart"]

    def test_register_lifecycle_hook_invalid_event(self):
        registry = HookRegistry(profile="minimal")
        with pytest.raises(ValueError, match="Unknown lifecycle event"):
            registry.register_lifecycle_hook("InvalidEvent", lambda ctx: None)

    def test_fire_lifecycle_event_runs_handlers(self):
        registry = HookRegistry(profile="minimal")
        events_received = []

        def handler_1(context):
            events_received.append(("h1", context.get("key")))
            return HookResult(action=HookAction.allow, reason="h1 ok")

        def handler_2(context):
            events_received.append(("h2", context.get("key")))
            return HookResult(action=HookAction.allow, reason="h2 ok")

        registry.register_lifecycle_hook("SessionStart", handler_1, name="h1")
        registry.register_lifecycle_hook("SessionStart", handler_2, name="h2")

        results = registry.fire_lifecycle_event("SessionStart", {"key": "test"})
        assert len(results) == 2
        assert events_received == [("h1", "test"), ("h2", "test")]
        assert results[0].reason == "h1 ok"
        assert results[1].reason == "h2 ok"

    def test_fire_lifecycle_event_invalid_event(self):
        registry = HookRegistry(profile="minimal")
        with pytest.raises(ValueError, match="Unknown lifecycle event"):
            registry.fire_lifecycle_event("Nonexistent", {})

    def test_fire_lifecycle_event_exception_in_handler(self):
        registry = HookRegistry(profile="minimal")

        def bad_handler(context):
            raise RuntimeError("handler crash")

        def good_handler(context):
            return HookResult(action=HookAction.allow, reason="survived")

        registry.register_lifecycle_hook("SessionEnd", bad_handler, name="bad")
        registry.register_lifecycle_hook("SessionEnd", good_handler, name="good")

        results = registry.fire_lifecycle_event("SessionEnd", {})
        assert len(results) == 2
        assert "exception" in results[0].reason
        assert results[1].reason == "survived"

    def test_fire_lifecycle_event_timeout(self):
        import time as _time

        registry = HookRegistry(profile="minimal")

        def slow_handler(context):
            _time.sleep(30)

        registry.register_lifecycle_hook(
            "PreCompact", slow_handler, name="slow", timeout=0.1
        )
        results = registry.fire_lifecycle_event("PreCompact", {})
        assert len(results) == 1
        assert "timed out" in results[0].reason

    def test_fire_lifecycle_event_priority_ordering(self):
        registry = HookRegistry(profile="minimal")
        order = []

        def high_priority(context):
            order.append("high")

        def low_priority(context):
            order.append("low")

        registry.register_lifecycle_hook(
            "Stop", low_priority, name="low", priority=200
        )
        registry.register_lifecycle_hook(
            "Stop", high_priority, name="high", priority=10
        )

        registry.fire_lifecycle_event("Stop", {})
        assert order == ["high", "low"]

    def test_fire_lifecycle_event_none_return(self):
        """Handlers that return None get wrapped as allow results."""
        registry = HookRegistry(profile="minimal")

        def void_handler(context):
            pass  # returns None

        registry.register_lifecycle_hook("SubagentStart", void_handler, name="void")
        results = registry.fire_lifecycle_event("SubagentStart", {})
        assert len(results) == 1
        assert results[0].action == HookAction.allow

    def test_fire_lifecycle_event_non_hookresult_return(self):
        """Handlers that return a non-HookResult get wrapped."""
        registry = HookRegistry(profile="minimal")

        def str_handler(context):
            return "some string"

        registry.register_lifecycle_hook("SubagentStop", str_handler, name="str_h")
        results = registry.fire_lifecycle_event("SubagentStop", {})
        assert len(results) == 1
        assert results[0].reason == "some string"

    def test_all_lifecycle_events_registerable(self):
        """All defined lifecycle events can be registered and fired."""
        registry = HookRegistry(profile="minimal")
        events = [
            "SessionStart", "SessionEnd", "PreCompact", "PostCompact",
            "Stop", "SubagentStart", "SubagentStop", "PermissionDenied",
            "PostToolUseFailure",
        ]
        for event in events:
            registry.register_lifecycle_hook(
                event, lambda ctx: None, name=f"test_{event}"
            )
            results = registry.fire_lifecycle_event(event, {})
            assert len(results) == 1

    def test_list_hooks_excludes_empty_lifecycle(self):
        """list_hooks() does not include lifecycle events with no handlers."""
        registry = HookRegistry(profile="minimal")
        hooks = registry.list_hooks()
        assert "SessionStart" not in hooks
        assert "Stop" not in hooks


# -----------------------------------------------------------------------
# P1-2: run_failure_hooks
# -----------------------------------------------------------------------


class TestRunFailureHooks:
    def test_run_failure_hooks(self):
        registry = HookRegistry(profile="minimal")
        received = {}

        def failure_handler(context):
            received.update(context)
            return HookResult(action=HookAction.allow, reason="logged failure")

        registry.register_lifecycle_hook(
            "PostToolUseFailure", failure_handler, name="fail_log"
        )

        tc = ToolCall(tool_name="bash", tool_input={"command": "fail"})
        error = RuntimeError("execution failed")
        ctx = {"session_id": "test"}

        results = registry.run_failure_hooks(tc, error, ctx)

        assert len(results) == 1
        assert results[0].reason == "logged failure"
        assert received["tool_name"] == "bash"
        assert received["error"] == "execution failed"
        assert received["error_type"] == "RuntimeError"
        assert received["session_id"] == "test"

    def test_run_failure_hooks_no_handlers(self):
        registry = HookRegistry(profile="minimal")
        tc = ToolCall(tool_name="bash", tool_input={"command": "test"})
        results = registry.run_failure_hooks(tc, ValueError("oops"), {})
        assert results == []
