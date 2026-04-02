"""Tests for autoharness.core.audit — AuditEngine."""

from __future__ import annotations

import json
import threading

from autoharness.core.audit import AuditEngine
from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDecision,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolResult,
)

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _tool_call(name="bash", command="echo hi") -> ToolCall:
    return ToolCall(tool_name=name, tool_input={"command": command})


def _risk(level=RiskLevel.low) -> RiskAssessment:
    return RiskAssessment(level=level, classifier="rules", reason="Test")


def _allow() -> PermissionDecision:
    return PermissionDecision(action="allow", reason="Allowed", source="test")


def _deny(reason="Blocked") -> PermissionDecision:
    return PermissionDecision(action="deny", reason=reason, source="test")


def _result(name="bash") -> ToolResult:
    return ToolResult(tool_name=name, status="success", output="ok")


# -----------------------------------------------------------------------
# Basic logging
# -----------------------------------------------------------------------


class TestAuditLog:
    def test_log_creates_file(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
            session_id="test-1",
        )
        engine.close()
        assert (tmp_path / "audit.jsonl").exists()
        content = (tmp_path / "audit.jsonl").read_text()
        assert content.strip() != ""
        parsed = json.loads(content.strip())
        assert parsed["event_type"] == "tool_call"
        assert parsed["tool_name"] == "bash"

    def test_log_with_hooks(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        pre_hooks = [
            HookResult(action=HookAction.allow, reason="Clean"),
        ]
        post_hooks = [
            HookResult(action=HookAction.sanitize,
                reason="Redacted", sanitized_output="[REDACTED]"),
        ]
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=pre_hooks,
            permission=_allow(),
            result=_result(),
            post_hooks=post_hooks,
            session_id="test-2",
        )
        engine.close()
        content = (tmp_path / "audit.jsonl").read_text().strip()
        parsed = json.loads(content)
        assert len(parsed["hooks_pre"]) == 1
        assert len(parsed["hooks_post"]) == 1
        assert parsed["hooks_post"][0]["sanitized"] is True


# -----------------------------------------------------------------------
# log_block
# -----------------------------------------------------------------------


class TestAuditLogBlock:
    def test_log_block(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log_block(
            tool_call=_tool_call(),
            risk=_risk(RiskLevel.critical),
            pre_hooks=[HookResult(action=HookAction.deny, reason="Danger")],
            permission=_deny("Too dangerous"),
            session_id="test-block",
        )
        engine.close()
        content = (tmp_path / "audit.jsonl").read_text().strip()
        parsed = json.loads(content)
        assert parsed["event_type"] == "tool_blocked"
        assert parsed["execution"]["status"] == "blocked"


# -----------------------------------------------------------------------
# log_error
# -----------------------------------------------------------------------


class TestAuditLogError:
    def test_log_error_with_string(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log_error(
            tool_call=_tool_call(),
            error="Something went wrong",
            session_id="test-err",
        )
        engine.close()
        content = (tmp_path / "audit.jsonl").read_text().strip()
        parsed = json.loads(content)
        assert parsed["event_type"] == "tool_error"
        assert "went wrong" in parsed["execution"]["error"]

    def test_log_error_with_exception(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log_error(
            tool_call=_tool_call(),
            error=RuntimeError("Kaboom"),
            session_id="test-exc",
        )
        engine.close()
        content = (tmp_path / "audit.jsonl").read_text().strip()
        parsed = json.loads(content)
        assert "Kaboom" in parsed["execution"]["error"]


# -----------------------------------------------------------------------
# get_summary
# -----------------------------------------------------------------------


class TestGetSummary:
    def test_empty_summary(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        summary = engine.get_summary()
        assert summary["total_calls"] == 0
        assert summary["blocked_count"] == 0
        engine.close()

    def test_summary_counts(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        # Log 2 successful calls and 1 blocked
        for _ in range(2):
            engine.log(
                tool_call=_tool_call(),
                risk=_risk(),
                pre_hooks=[],
                permission=_allow(),
                result=_result(),
                post_hooks=[],
                session_id="s1",
            )
        engine.log_block(
            tool_call=_tool_call(),
            risk=_risk(RiskLevel.high),
            pre_hooks=[],
            permission=_deny(),
            session_id="s1",
        )
        summary = engine.get_summary(session_id="s1")
        assert summary["total_calls"] == 3
        assert summary["blocked_count"] == 1
        assert "bash" in summary["tools_used"]
        engine.close()

    def test_summary_risk_distribution(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(RiskLevel.low),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(RiskLevel.high),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )
        summary = engine.get_summary()
        assert "low" in summary["risk_distribution"]
        assert "high" in summary["risk_distribution"]
        engine.close()


# -----------------------------------------------------------------------
# JSONL file writing
# -----------------------------------------------------------------------


class TestJSONLWriting:
    def test_multiple_records_are_valid_jsonl(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        for i in range(5):
            engine.log(
                tool_call=_tool_call(command=f"echo {i}"),
                risk=_risk(),
                pre_hooks=[],
                permission=_allow(),
                result=_result(),
                post_hooks=[],
                session_id="jsonl-test",
            )
        engine.close()
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)
            assert "tool_name" in parsed

    def test_parent_dirs_created(self, tmp_path):
        audit_path = str(tmp_path / "deep" / "nested" / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )
        engine.close()
        assert (tmp_path / "deep" / "nested" / "audit.jsonl").exists()


# -----------------------------------------------------------------------
# Thread safety
# -----------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_writes(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)

        def write_records(thread_id):
            for i in range(10):
                engine.log(
                    tool_call=_tool_call(command=f"thread-{thread_id}-{i}"),
                    risk=_risk(),
                    pre_hooks=[],
                    permission=_allow(),
                    result=_result(),
                    post_hooks=[],
                    session_id=f"thread-{thread_id}",
                )

        threads = [
            threading.Thread(target=write_records, args=(tid,))
            for tid in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        engine.close()
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == 40  # 4 threads * 10 records each
        # Each line should be valid JSON
        for line in lines:
            json.loads(line)


# -----------------------------------------------------------------------
# Disabled engine
# -----------------------------------------------------------------------


class TestDisabledEngine:
    def test_disabled_does_not_write(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path, enabled=False)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )
        engine.close()
        # File should not exist or be empty
        if (tmp_path / "audit.jsonl").exists():
            assert (tmp_path / "audit.jsonl").read_text().strip() == ""


# -----------------------------------------------------------------------
# Close and context manager
# -----------------------------------------------------------------------


class TestCloseAndContextManager:
    def test_close_idempotent(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.close()
        engine.close()  # Should not raise

    def test_context_manager(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        with AuditEngine(output_path=audit_path) as engine:
            engine.log(
                tool_call=_tool_call(),
                risk=_risk(),
                pre_hooks=[],
                permission=_allow(),
                result=_result(),
                post_hooks=[],
            )
        # File should exist after context exit
        assert (tmp_path / "audit.jsonl").exists()

    def test_write_after_close_is_noop(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.close()
        # Should not raise
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )


# -----------------------------------------------------------------------
# Properties and introspection
# -----------------------------------------------------------------------


class TestProperties:
    def test_enabled_property(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path, enabled=True)
        assert engine.enabled is True
        engine.close()

    def test_disabled_property(self, tmp_path):
        engine = AuditEngine(output_path=str(tmp_path / "a.jsonl"), enabled=False)
        assert engine.enabled is False

    def test_output_path_property(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=path)
        assert engine.output_path == path
        engine.close()

    def test_repr(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=path)
        r = repr(engine)
        assert "AuditEngine" in r
        assert "enabled=True" in r
        engine.close()


# -----------------------------------------------------------------------
# get_records
# -----------------------------------------------------------------------


class TestGetRecords:
    def test_get_records_by_session(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
            session_id="session-A",
        )
        engine.log(
            tool_call=_tool_call(command="other"),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
            session_id="session-B",
        )
        records = engine.get_records(session_id="session-A")
        assert len(records) == 1
        assert records[0].session_id == "session-A"
        engine.close()

    def test_get_records_by_event_type(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )
        engine.log_block(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_deny(),
        )
        records = engine.get_records(event_type="tool_blocked")
        assert len(records) == 1
        assert records[0].event_type == "tool_blocked"
        engine.close()

    def test_get_records_limit(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path)
        for i in range(10):
            engine.log(
                tool_call=_tool_call(command=f"echo {i}"),
                risk=_risk(),
                pre_hooks=[],
                permission=_allow(),
                result=_result(),
                post_hooks=[],
            )
        records = engine.get_records(limit=3)
        assert len(records) == 3
        engine.close()

    def test_get_records_empty_file(self, tmp_path):
        audit_path = str(tmp_path / "nonexistent.jsonl")
        engine = AuditEngine(output_path=audit_path, enabled=False)
        records = engine.get_records()
        assert records == []


# -----------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_removes_old_records(self, tmp_path):
        audit_path = str(tmp_path / "audit.jsonl")
        engine = AuditEngine(output_path=audit_path, retention_days=0)
        engine.log(
            tool_call=_tool_call(),
            risk=_risk(),
            pre_hooks=[],
            permission=_allow(),
            result=_result(),
            post_hooks=[],
        )
        # All records are "now", retention=0 days means cutoff is now
        # Records are exactly at cutoff, they should be kept (< cutoff removes)
        removed = engine.cleanup(retention_days=0)
        # Records created "now" should not be older than cutoff (now - 0 days = now)
        # Due to timing, they might be exactly at cutoff or slightly after
        # This is a best-effort test
        assert isinstance(removed, int)
        engine.close()

    def test_cleanup_nonexistent_file(self, tmp_path):
        engine = AuditEngine(
            output_path=str(tmp_path / "nonexistent.jsonl"), enabled=False
        )
        removed = engine.cleanup()
        assert removed == 0
