"""Tests for CLI wrap and report commands."""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from autoharness.cli.main import cli

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def audit_dir(tmp_path):
    """Create a temporary audit directory."""
    d = tmp_path / ".autoharness"
    d.mkdir()
    return d


@pytest.fixture
def sample_audit_log(audit_dir):
    """Write sample audit records to a JSONL file."""
    import hashlib
    from datetime import datetime, timezone

    log_path = audit_dir / "audit.jsonl"

    def _hash(d):
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()

    records = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": "test-session",
            "event_type": "tool_call",
            "tool_name": "bash",
            "tool_input_hash": _hash({"command": "echo hi"}),
            "risk": {
                "level": "low", "classifier": "rules",
                "matched_rule": None, "reason": "Safe",
                "confidence": 1.0,
            },
            "hooks_pre": [],
            "hooks_post": [],
            "permission": {
                "action": "allow", "reason": "All checks passed",
                "source": "pipeline", "risk_level": "low",
            },
            "execution": {
                "status": "success", "duration_ms": 10,
                "output_size": 5, "sanitized": False,
            },
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": "test-session",
            "event_type": "tool_blocked",
            "tool_name": "bash",
            "tool_input_hash": _hash({"command": "rm -rf /"}),
            "risk": {
                "level": "high", "classifier": "rules",
                "matched_rule": "destructive_rm",
                "reason": "rm -rf", "confidence": 1.0,
            },
            "hooks_pre": [
                {"action": "deny", "reason": "Dangerous", "severity": "error"},
            ],
            "hooks_post": [],
            "permission": {
                "action": "deny", "reason": "Blocked by risk",
                "source": "risk_threshold", "risk_level": "high",
            },
            "execution": {
                "status": "blocked", "duration_ms": 0,
                "output_size": 0, "sanitized": False,
            },
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": "test-session",
            "event_type": "tool_call",
            "tool_name": "read",
            "tool_input_hash": _hash({"file_path": "/tmp/test.txt"}),
            "risk": {
                "level": "low", "classifier": "rules",
                "matched_rule": None, "reason": "Safe",
                "confidence": 1.0,
            },
            "hooks_pre": [],
            "hooks_post": [],
            "permission": {
                "action": "allow",
                "reason": "All checks passed",
                "source": "pipeline", "risk_level": "low",
            },
            "execution": {
                "status": "success", "duration_ms": 5,
                "output_size": 100, "sanitized": False,
            },
        },
    ]

    with open(log_path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    return str(log_path)


# -----------------------------------------------------------------------
# autoharness wrap
# -----------------------------------------------------------------------


class TestWrapCommand:
    def test_wrap_echo(self, runner, tmp_path):
        """Wrap a simple echo command."""
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "--audit-log", audit_path,
            "--", "echo", "hello from wrapped process",
        ])
        # The echo should succeed
        assert result.exit_code == 0
        assert "hello from wrapped process" in result.output

    def test_wrap_shows_banner(self, runner, tmp_path):
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "--audit-log", audit_path,
            "--", "echo", "test",
        ])
        assert "AutoHarness Wrapper Mode" in result.stderr

    def test_wrap_sets_env_vars(self, runner, tmp_path):
        """The wrapped subprocess should see AUTOHARNESS_ACTIVE=1."""
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "--audit-log", audit_path,
            "--", "env",
        ])
        assert "AUTOHARNESS_ACTIVE=1" in result.output
        assert "AUTOHARNESS_SESSION_ID=" in result.output
        assert "AUTOHARNESS_AUDIT_LOG=" in result.output

    def test_wrap_custom_session_id(self, runner, tmp_path):
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "--audit-log", audit_path,
            "--session-id", "my-session-123",
            "--", "env",
        ])
        assert "AUTOHARNESS_SESSION_ID=my-session-123" in result.output

    def test_wrap_nonexistent_command(self, runner, tmp_path):
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "--audit-log", audit_path,
            "--", "this_command_does_not_exist_autoharness_test",
        ])
        assert result.exit_code == 127

    def test_wrap_failing_command(self, runner, tmp_path):
        """Wrap a command that exits with non-zero."""
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "--audit-log", audit_path,
            "--", "python", "-c", "import sys; sys.exit(42)",
        ])
        assert result.exit_code == 42

    def test_wrap_no_command_errors(self, runner):
        result = runner.invoke(cli, ["wrap"])
        assert result.exit_code != 0

    def test_wrap_with_constitution(self, runner, tmp_path):
        """Wrap with an explicit constitution file."""
        # Create a minimal constitution
        const_path = tmp_path / "constitution.yaml"
        const_path.write_text(
            'version: "1.0"\nidentity:\n  name: test\n',
            encoding="utf-8",
        )
        audit_path = str(tmp_path / ".autoharness" / "audit.jsonl")
        result = runner.invoke(cli, [
            "wrap",
            "-c", str(const_path),
            "--audit-log", audit_path,
            "--", "echo", "governed",
        ])
        assert result.exit_code == 0
        assert "governed" in result.output


# -----------------------------------------------------------------------
# autoharness report
# -----------------------------------------------------------------------


class TestReportCommand:
    def test_report_html(self, runner, sample_audit_log, tmp_path):
        output_path = str(tmp_path / "report.html")
        result = runner.invoke(cli, [
            "report",
            "--path", sample_audit_log,
            "--format", "html",
            "--output", output_path,
        ])
        assert result.exit_code == 0
        assert os.path.exists(output_path)
        with open(output_path) as f:
            content = f.read()
        assert "AutoHarness Audit Report" in content
        assert "<!DOCTYPE html>" in content

    def test_report_text(self, runner, sample_audit_log):
        result = runner.invoke(cli, [
            "report",
            "--path", sample_audit_log,
            "--format", "text",
        ])
        assert result.exit_code == 0
        assert "Audit Report" in result.output

    def test_report_json(self, runner, sample_audit_log):
        result = runner.invoke(cli, [
            "report",
            "--path", sample_audit_log,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total_calls" in data
        assert data["total_calls"] == 3

    def test_report_no_audit_log(self, runner, tmp_path):
        result = runner.invoke(cli, [
            "report",
            "--path", str(tmp_path / "nonexistent.jsonl"),
        ])
        assert result.exit_code == 1

    def test_report_session_filter(self, runner, sample_audit_log):
        result = runner.invoke(cli, [
            "report",
            "--path", sample_audit_log,
            "--format", "json",
            "--session", "test-session",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_calls"] == 3

    def test_report_session_filter_empty(self, runner, sample_audit_log):
        result = runner.invoke(cli, [
            "report",
            "--path", sample_audit_log,
            "--format", "text",
            "--session", "nonexistent-session",
        ])
        assert result.exit_code == 0
        assert "No audit records" in result.stderr


# -----------------------------------------------------------------------
# autoharness agents
# -----------------------------------------------------------------------


class TestAgentsCommand:
    def test_agents_list(self, runner):
        result = runner.invoke(cli, ["agents"])
        assert result.exit_code == 0
        assert "coder" in result.stderr
        assert "reviewer" in result.stderr
        assert "planner" in result.stderr
        assert "executor" in result.stderr
        assert "Built-in Agent Profiles" in result.stderr
