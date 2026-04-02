"""Tests for Phases 6-9: Session, Hook Profiles, Risk Multi, Tasks, Recovery."""
from __future__ import annotations

import asyncio
import os
import time

import pytest

# ---------------------------------------------------------------------------
# Phase 6: Session Management
# ---------------------------------------------------------------------------

class TestSessionState:
    def test_defaults(self):
        from autoharness.session.persistence import SessionState
        s = SessionState()
        assert len(s.session_id) == 8
        assert s.status == "in-progress"
        assert s.working == []
        assert s.in_progress == []
        assert s.not_started == []
        assert s.failed == []
        assert s.open_questions == []
        assert s.next_step == ""
        assert s.project == ""
        assert s.branch == ""

    def test_custom_fields(self):
        from autoharness.session.persistence import SessionState
        s = SessionState(session_id="abc", project="myproj", branch="main",
                         working=["task1"], next_step="do something")
        assert s.session_id == "abc"
        assert s.project == "myproj"
        assert s.working == ["task1"]
        assert s.next_step == "do something"


class TestSaveLoadSession:
    def test_roundtrip(self, tmp_path):
        from autoharness.session.persistence import SessionState, load_session, save_session
        state = SessionState(
            session_id="test01",
            project="AgentLint",
            branch="feature/x",
            status="in-progress",
            working=["setup env"],
            in_progress=["write tests"],
            not_started=["deploy"],
            failed=["flaky CI"],
            open_questions=["which DB?"],
            next_step="Fix CI",
        )
        path = save_session(state, base_dir=tmp_path)
        assert path.exists()
        assert path.name == "test01-session.md"

        loaded = load_session(path)
        assert loaded.session_id == "test01"
        assert loaded.project == "AgentLint"
        assert loaded.branch == "feature/x"
        assert loaded.status == "in-progress"
        assert loaded.working == ["setup env"]
        assert loaded.in_progress == ["write tests"]
        assert loaded.not_started == ["deploy"]
        assert loaded.failed == ["flaky CI"]
        assert loaded.open_questions == ["which DB?"]
        assert loaded.next_step == "Fix CI"

    def test_empty_sections_roundtrip(self, tmp_path):
        from autoharness.session.persistence import SessionState, load_session, save_session
        state = SessionState(session_id="empty1", project="P")
        path = save_session(state, base_dir=tmp_path)
        loaded = load_session(path)
        assert loaded.working == []
        assert loaded.next_step == ""

    def test_invalid_file_raises(self, tmp_path):
        from autoharness.session.persistence import load_session
        bad = tmp_path / "bad.md"
        bad.write_text("no frontmatter here", encoding="utf-8")
        with pytest.raises(ValueError):
            load_session(bad)

    def test_save_creates_directory(self, tmp_path):
        from autoharness.session.persistence import SessionState, save_session
        deep = tmp_path / "a" / "b" / "c"
        save_session(SessionState(session_id="deep1"), base_dir=deep)
        assert (deep / "deep1-session.md").exists()


class TestListRecentSessions:
    def test_empty_dir(self, tmp_path):
        from autoharness.session.persistence import list_recent_sessions
        assert list_recent_sessions(base_dir=tmp_path) == []

    def test_nonexistent_dir(self, tmp_path):
        from autoharness.session.persistence import list_recent_sessions
        assert list_recent_sessions(base_dir=tmp_path / "nope") == []

    def test_lists_recent(self, tmp_path):
        from autoharness.session.persistence import (
            SessionState,
            list_recent_sessions,
            save_session,
        )
        save_session(SessionState(session_id="s1"), base_dir=tmp_path)
        save_session(SessionState(session_id="s2"), base_dir=tmp_path)
        result = list_recent_sessions(base_dir=tmp_path)
        assert len(result) == 2

    def test_excludes_old(self, tmp_path):
        from autoharness.session.persistence import (
            SessionState,
            list_recent_sessions,
            save_session,
        )
        path = save_session(SessionState(session_id="old1"), base_dir=tmp_path)
        # Set mtime to 30 days ago
        old_time = time.time() - 30 * 86400
        os.utime(path, (old_time, old_time))
        result = list_recent_sessions(base_dir=tmp_path, days=7)
        assert len(result) == 0


class TestCleanupOldSessions:
    def test_cleanup(self, tmp_path):
        from autoharness.session.persistence import (
            SessionState,
            cleanup_old_sessions,
            save_session,
        )
        p1 = save_session(SessionState(session_id="keep"), base_dir=tmp_path)
        p2 = save_session(SessionState(session_id="remove"), base_dir=tmp_path)
        old_time = time.time() - 30 * 86400
        os.utime(p2, (old_time, old_time))
        removed = cleanup_old_sessions(base_dir=tmp_path, days=7)
        assert removed == 1
        assert p1.exists()
        assert not p2.exists()

    def test_cleanup_nonexistent_dir(self, tmp_path):
        from autoharness.session.persistence import cleanup_old_sessions
        assert cleanup_old_sessions(base_dir=tmp_path / "nope") == 0


class TestFormatBriefing:
    def test_full_briefing(self):
        from autoharness.session.persistence import SessionState
        from autoharness.session.resume import format_briefing
        state = SessionState(
            project="TestProj", branch="dev", status="in-progress",
            date="2026-03-31",
            working=["done1"], in_progress=["wip1"],
            not_started=["todo1"], failed=["bad1"],
            open_questions=["q1"], next_step="Next thing",
        )
        text = format_briefing(state)
        assert "**PROJECT**: TestProj" in text
        assert "## COMPLETED" in text
        assert "done1" in text
        assert "## IN PROGRESS" in text
        assert "## NOT STARTED" in text
        assert "## WHAT NOT TO RETRY" in text
        assert "## OPEN QUESTIONS" in text
        assert "## NEXT STEP" in text
        assert "Next thing" in text

    def test_minimal_briefing(self):
        from autoharness.session.persistence import SessionState
        from autoharness.session.resume import format_briefing
        state = SessionState(project="", branch="")
        text = format_briefing(state)
        assert "Unknown" in text


class TestResumeSession:
    def test_no_sessions(self, tmp_path):
        from autoharness.session.resume import resume_session
        result = resume_session(base_dir=tmp_path)
        assert "No recent sessions found" in result

    def test_resume_specific_path(self, tmp_path):
        from autoharness.session.persistence import SessionState, save_session
        from autoharness.session.resume import resume_session
        path = save_session(SessionState(session_id="r1", project="Proj"), base_dir=tmp_path)
        text = resume_session(path=path)
        assert "Proj" in text


# ---------------------------------------------------------------------------
# Phase 6: Session Cost
# ---------------------------------------------------------------------------

class TestSessionCost:
    def test_defaults(self):
        from autoharness.session.cost import SessionCost
        c = SessionCost()
        assert c.turns == 0
        assert c.total_tokens == 0
        assert c.estimated_cost_usd == 0.0

    def test_record_turn(self):
        from autoharness.session.cost import SessionCost
        c = SessionCost(model="claude-sonnet-4-6")
        c.record_turn(input_tokens=1000, output_tokens=500)
        assert c.turns == 1
        assert c.total_input_tokens == 1000
        assert c.total_output_tokens == 500
        c.record_turn(input_tokens=200, output_tokens=100)
        assert c.turns == 2
        assert c.total_input_tokens == 1200

    def test_estimated_cost(self):
        from autoharness.session.cost import SessionCost
        c = SessionCost(model="claude-sonnet-4-6")
        c.record_turn(input_tokens=1_000_000, output_tokens=1_000_000)
        # input: 3.0, output: 15.0 => 18.0
        assert c.estimated_cost_usd == 18.0

    def test_total_tokens(self):
        from autoharness.session.cost import SessionCost
        c = SessionCost()
        c.record_turn(input_tokens=10, output_tokens=20, cache_read=5, cache_write=3)
        assert c.total_tokens == 38

    def test_save_load_roundtrip(self, tmp_path):
        from autoharness.session.cost import SessionCost
        c = SessionCost(session_id="s1", model="claude-haiku-4-5")
        c.record_turn(input_tokens=100, output_tokens=50)
        path = tmp_path / "cost.json"
        c.save(path)
        loaded = SessionCost.load(path)
        assert loaded.session_id == "s1"
        assert loaded.model == "claude-haiku-4-5"
        assert loaded.total_input_tokens == 100
        assert loaded.turns == 1

    def test_unknown_model_uses_sonnet_pricing(self):
        from autoharness.session.cost import SessionCost
        c = SessionCost(model="unknown-model-xyz")
        c.record_turn(input_tokens=1_000_000)
        # Falls back to sonnet pricing: 3.0
        assert c.estimated_cost_usd == 3.0


# ---------------------------------------------------------------------------
# Phase 7: Hook Profiles
# ---------------------------------------------------------------------------

class TestHookProfiles:
    def test_default_profile(self, monkeypatch):
        monkeypatch.delenv("AUTOHARNESS_HOOK_PROFILE", raising=False)
        from autoharness.core.hook_profiles import get_hook_profile
        assert get_hook_profile() == "standard"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("AUTOHARNESS_HOOK_PROFILE", "strict")
        from autoharness.core.hook_profiles import get_hook_profile
        assert get_hook_profile() == "strict"

    def test_invalid_profile_defaults(self, monkeypatch):
        monkeypatch.setenv("AUTOHARNESS_HOOK_PROFILE", "bogus")
        from autoharness.core.hook_profiles import get_hook_profile
        assert get_hook_profile() == "standard"

    def test_disabled_hooks_empty(self, monkeypatch):
        monkeypatch.delenv("AUTOHARNESS_DISABLED_HOOKS", raising=False)
        from autoharness.core.hook_profiles import get_disabled_hooks
        assert get_disabled_hooks() == set()

    def test_disabled_hooks_parsing(self, monkeypatch):
        monkeypatch.setenv("AUTOHARNESS_DISABLED_HOOKS", "hook1, hook2 , hook3")
        from autoharness.core.hook_profiles import get_disabled_hooks
        assert get_disabled_hooks() == {"hook1", "hook2", "hook3"}

    def test_is_hook_enabled_standard(self):
        from autoharness.core.hook_profiles import is_hook_enabled
        assert is_hook_enabled(
            "h1", required_profile="standard",
            profile="standard", disabled=set(),
        )
        assert is_hook_enabled(
            "h1", required_profile="standard",
            profile="strict", disabled=set(),
        )
        assert not is_hook_enabled(
            "h1", required_profile="standard",
            profile="minimal", disabled=set(),
        )

    def test_is_hook_enabled_disabled(self):
        from autoharness.core.hook_profiles import is_hook_enabled
        assert not is_hook_enabled("h1", profile="strict", disabled={"h1"})

    def test_is_hook_enabled_minimal_always_runs(self):
        from autoharness.core.hook_profiles import is_hook_enabled
        assert is_hook_enabled("h1", required_profile="minimal", profile="minimal", disabled=set())

    def test_is_config_protected(self):
        from autoharness.core.hook_profiles import is_config_protected
        assert is_config_protected("tsconfig.json")
        assert is_config_protected("/path/to/.eslintrc.js")
        assert is_config_protected("setup.cfg")
        assert not is_config_protected("main.py")
        assert not is_config_protected("random.json")


# ---------------------------------------------------------------------------
# Phase 8: Advanced Patterns
# ---------------------------------------------------------------------------

class TestMultiAxisRisk:
    def test_composite_calculation(self):
        from autoharness.core.risk_multi import MultiAxisRisk
        r = MultiAxisRisk(
            base_risk=0.4, file_sensitivity=0.2,
            blast_radius=0.6, irreversibility=0.8,
        )
        assert r.composite == pytest.approx(0.5)

    def test_action_allow(self):
        from autoharness.core.risk_multi import MultiAxisRisk
        r = MultiAxisRisk(
            base_risk=0.1, file_sensitivity=0.0,
            blast_radius=0.0, irreversibility=0.0,
        )
        assert r.action == "allow"

    def test_action_review(self):
        from autoharness.core.risk_multi import MultiAxisRisk
        r = MultiAxisRisk(
            base_risk=0.5, file_sensitivity=0.5,
            blast_radius=0.0, irreversibility=0.0,
        )
        assert r.action == "review"

    def test_action_require_confirmation(self):
        from autoharness.core.risk_multi import MultiAxisRisk
        r = MultiAxisRisk(
            base_risk=0.9, file_sensitivity=0.7,
            blast_radius=0.4, irreversibility=0.2,
        )
        assert r.action == "require_confirmation"

    def test_action_block(self):
        from autoharness.core.risk_multi import MultiAxisRisk
        r = MultiAxisRisk(
            base_risk=1.0, file_sensitivity=1.0,
            blast_radius=0.5, irreversibility=0.5,
        )
        assert r.action == "block"

    def test_assess_read_tool(self):
        from autoharness.core.risk_multi import assess_risk
        r = assess_risk("read")
        assert r.base_risk == 0.1
        assert r.action == "allow"

    def test_assess_bash_tool(self):
        from autoharness.core.risk_multi import assess_risk
        r = assess_risk("bash")
        assert r.base_risk == 0.7

    def test_assess_sensitive_file(self):
        from autoharness.core.risk_multi import assess_risk
        r = assess_risk("read", file_path="/home/user/.env")
        assert r.file_sensitivity >= 0.9

    def test_assess_destructive_command(self):
        from autoharness.core.risk_multi import assess_risk
        r = assess_risk("bash", command="rm -rf /tmp/stuff")
        assert r.irreversibility == 1.0

    def test_assess_deploy_command(self):
        from autoharness.core.risk_multi import assess_risk
        r = assess_risk("bash", command="git push origin main")
        assert r.blast_radius == 0.8

    def test_assess_unknown_tool(self):
        from autoharness.core.risk_multi import assess_risk
        r = assess_risk("unknown_tool_xyz")
        assert r.base_risk == 0.3


class TestTaskSystem:
    def test_create_and_get(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        t = ts.create("Build feature")
        assert t.id == 1
        assert t.subject == "Build feature"
        assert t.status == "pending"
        loaded = ts.get(1)
        assert loaded is not None
        assert loaded.subject == "Build feature"

    def test_get_nonexistent(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        assert ts.get(999) is None

    def test_list_all(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        ts.create("A")
        ts.create("B")
        ts.create("C")
        assert len(ts.list_all()) == 3

    def test_update_status(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        ts.create("X")
        updated = ts.update_status(1, "completed")
        assert updated is not None
        assert updated.status == "completed"

    def test_update_status_nonexistent(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        assert ts.update_status(42, "completed") is None

    def test_unblocking_on_complete(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        t1 = ts.create("First")
        t2 = ts.create("Second", blocked_by=[t1.id])
        assert ts.get(t2.id).blocked_by == [t1.id]
        ts.update_status(t1.id, "completed")
        assert ts.get(t2.id).blocked_by == []

    def test_list_ready(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        t1 = ts.create("First")
        ts.create("Second", blocked_by=[t1.id])
        ready = ts.list_ready()
        assert len(ready) == 1
        assert ready[0].id == t1.id

    def test_assign(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        ts.create("Task")
        assigned = ts.assign(1, "agent-1")
        assert assigned is not None
        assert assigned.owner == "agent-1"
        # Assigned tasks are not "ready"
        assert ts.list_ready() == []

    def test_assign_nonexistent(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        ts = TaskSystem(base_dir=tmp_path / "tasks")
        assert ts.assign(99, "agent") is None

    def test_persistence_across_instances(self, tmp_path):
        from autoharness.tasks.task_system import TaskSystem
        d = tmp_path / "tasks"
        ts1 = TaskSystem(base_dir=d)
        ts1.create("Persisted")
        ts2 = TaskSystem(base_dir=d)
        assert len(ts2.list_all()) == 1
        assert ts2._next_id == 2

    def test_task_defaults(self):
        from autoharness.tasks.task_system import Task
        t = Task()
        assert t.id == 0
        assert t.status == "pending"
        assert t.owner is None
        assert t.blocked_by == []


# ---------------------------------------------------------------------------
# Phase 9: Error Recovery
# ---------------------------------------------------------------------------

class TestOutputRecovery:
    def test_is_max_output_truncated_true(self):
        from autoharness.context.recovery import is_max_output_truncated
        assert is_max_output_truncated({"stop_reason": "max_tokens"})

    def test_is_max_output_truncated_false(self):
        from autoharness.context.recovery import is_max_output_truncated
        assert not is_max_output_truncated({"stop_reason": "end_turn"})
        assert not is_max_output_truncated({})

    def test_get_continuation_message(self):
        from autoharness.context.recovery import get_continuation_message
        msg = get_continuation_message()
        assert msg["role"] == "user"
        assert "continue" in msg["content"].lower()

    def test_recovery_loop_retries(self):
        from autoharness.context.recovery import OutputRecoveryLoop
        loop = OutputRecoveryLoop(max_retries=2)
        assert loop.should_retry({"stop_reason": "max_tokens"})
        assert loop.should_retry({"stop_reason": "max_tokens"})
        assert not loop.should_retry({"stop_reason": "max_tokens"})

    def test_recovery_loop_resets_on_success(self):
        from autoharness.context.recovery import OutputRecoveryLoop
        loop = OutputRecoveryLoop(max_retries=2)
        loop.should_retry({"stop_reason": "max_tokens"})
        loop.should_retry({"stop_reason": "end_turn"})  # resets
        assert loop.should_retry({"stop_reason": "max_tokens"})  # count reset

    def test_recovery_loop_reset_method(self):
        from autoharness.context.recovery import OutputRecoveryLoop
        loop = OutputRecoveryLoop(max_retries=1)
        loop.should_retry({"stop_reason": "max_tokens"})
        loop.reset()
        assert loop.should_retry({"stop_reason": "max_tokens"})


class TestThinkingPreservation:
    def test_should_preserve_thinking_true(self):
        from autoharness.context.recovery import should_preserve_thinking
        msg = {"role": "assistant", "content": [{"type": "thinking", "thinking": "..."}]}
        assert should_preserve_thinking(msg)

    def test_should_preserve_thinking_false(self):
        from autoharness.context.recovery import should_preserve_thinking
        msg = {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}
        assert not should_preserve_thinking(msg)

    def test_should_preserve_thinking_string_content(self):
        from autoharness.context.recovery import should_preserve_thinking
        msg = {"role": "assistant", "content": "just a string"}
        assert not should_preserve_thinking(msg)

    def test_validate_thinking_blocks_valid(self):
        from autoharness.context.recovery import validate_thinking_blocks
        messages = [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "hi"},
            ]},
        ]
        assert validate_thinking_blocks(messages) == []

    def test_validate_thinking_blocks_wrong_role(self):
        from autoharness.context.recovery import validate_thinking_blocks
        messages = [
            {"role": "user", "content": [{"type": "thinking", "thinking": "..."}]},
        ]
        issues = validate_thinking_blocks(messages)
        assert len(issues) >= 1
        assert "non-assistant" in issues[0]

    def test_validate_thinking_blocks_last_in_content(self):
        from autoharness.context.recovery import validate_thinking_blocks
        messages = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "hi"},
                {"type": "thinking", "thinking": "..."},
            ]},
        ]
        issues = validate_thinking_blocks(messages)
        assert any("last in content" in i for i in issues)


class TestRetry:
    def test_is_retryable_status(self):
        from autoharness.context.recovery import is_retryable_status
        assert is_retryable_status(429)
        assert is_retryable_status(500)
        assert is_retryable_status(503)
        assert not is_retryable_status(200)
        assert not is_retryable_status(400)
        assert not is_retryable_status(404)

    def test_compute_backoff_ms_default(self):
        from autoharness.context.recovery import compute_backoff_ms
        assert compute_backoff_ms(0) == 200
        assert compute_backoff_ms(1) == 400
        assert compute_backoff_ms(2) == 800

    def test_compute_backoff_ms_capped(self):
        from autoharness.context.recovery import RetryConfig, compute_backoff_ms
        cfg = RetryConfig(initial_backoff_ms=100, max_backoff_ms=500)
        assert compute_backoff_ms(0, cfg) == 100
        assert compute_backoff_ms(10, cfg) == 500  # capped

    def test_retry_config_defaults(self):
        from autoharness.context.recovery import RetryConfig
        c = RetryConfig()
        assert c.max_retries == 2
        assert c.initial_backoff_ms == 200
        assert c.max_backoff_ms == 2000

    def test_retry_with_backoff_success(self):
        from autoharness.context.recovery import RetryConfig, retry_with_backoff

        async def ok():
            return 42

        result = asyncio.run(
            retry_with_backoff(ok, config=RetryConfig(max_retries=1))
        )
        assert result == 42

    def test_retry_with_backoff_eventual_success(self):
        from autoharness.context.recovery import RetryConfig, retry_with_backoff

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("fail")
            return "ok"

        result = asyncio.run(
            retry_with_backoff(
                flaky,
                config=RetryConfig(
                    max_retries=3,
                    initial_backoff_ms=1,
                    max_backoff_ms=10,
                ),
            )
        )
        assert result == "ok"
        assert call_count == 3

    def test_retry_with_backoff_exhausted(self):
        from autoharness.context.recovery import RetryConfig, retry_with_backoff

        async def always_fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            asyncio.run(
                retry_with_backoff(
                    always_fail,
                    config=RetryConfig(
                        max_retries=1,
                        initial_backoff_ms=1,
                        max_backoff_ms=5,
                    ),
                )
            )
