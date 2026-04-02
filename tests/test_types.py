"""Tests for autoharness.core.types — Pydantic models and enumerations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from autoharness.core.types import (
    AuditRecord,
    ConstitutionConfig,
    Enforcement,
    HookAction,
    HookProfile,
    HookResult,
    PermissionDecision,
    PermissionDefaults,
    RiskAssessment,
    RiskLevel,
    RiskPattern,
    Rule,
    RuleSeverity,
    ToolCall,
    ToolPermission,
    ToolResult,
)

# -----------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------


class TestRiskLevel:
    def test_lowercase_values(self):
        assert RiskLevel.low == "low"
        assert RiskLevel.high == "high"
        assert RiskLevel.critical == "critical"

    def test_string_enum(self):
        assert isinstance(RiskLevel.low, str)
        assert RiskLevel("low") == RiskLevel.low


class TestHookAction:
    def test_values(self):
        assert HookAction.allow == "allow"
        assert HookAction.deny == "deny"
        assert HookAction.ask == "ask"
        assert HookAction.sanitize == "sanitize"
        assert HookAction.modify == "modify"



class TestEnforcement:
    def test_values(self):
        assert Enforcement.prompt == "prompt"
        assert Enforcement.hook == "hook"
        assert Enforcement.both == "both"


class TestRuleSeverity:
    def test_values(self):
        assert RuleSeverity.info == "info"
        assert RuleSeverity.warning == "warning"
        assert RuleSeverity.error == "error"


class TestHookProfile:
    def test_values(self):
        assert HookProfile.minimal == "minimal"
        assert HookProfile.standard == "standard"
        assert HookProfile.strict == "strict"


# -----------------------------------------------------------------------
# ToolCall
# -----------------------------------------------------------------------


class TestToolCall:
    def test_creation(self):
        tc = ToolCall(tool_name="bash", tool_input={"command": "ls"})
        assert tc.tool_name == "bash"
        assert tc.tool_input == {"command": "ls"}
        assert tc.metadata == {}
        assert tc.session_id is None
        assert isinstance(tc.timestamp, datetime)

    def test_timestamp_defaults_to_utc(self):
        tc = ToolCall(tool_name="bash", tool_input={})
        assert tc.timestamp.tzinfo is not None

    def test_frozen(self):
        tc = ToolCall(tool_name="bash", tool_input={"command": "ls"})
        with pytest.raises(ValidationError):
            tc.tool_name = "other"

    def test_empty_tool_name_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            ToolCall(tool_name="", tool_input={})

    def test_whitespace_tool_name_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            ToolCall(tool_name="   ", tool_input={})

    def test_with_metadata(self):
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "ls"},
            metadata={"caller": "test"},
            session_id="sess-123",
        )
        assert tc.metadata == {"caller": "test"}
        assert tc.session_id == "sess-123"

    def test_serialization(self):
        tc = ToolCall(tool_name="bash", tool_input={"command": "ls"})
        data = tc.model_dump()
        assert data["tool_name"] == "bash"
        assert "timestamp" in data


# -----------------------------------------------------------------------
# ToolResult
# -----------------------------------------------------------------------


class TestToolResult:
    def test_success(self):
        tr = ToolResult(tool_name="bash", status="success", output="hello")
        assert tr.status == "success"
        assert tr.output == "hello"
        assert tr.sanitized is False

    def test_blocked(self):
        tr = ToolResult(
            tool_name="bash", status="blocked", blocked_reason="Too dangerous"
        )
        assert tr.status == "blocked"
        assert tr.blocked_reason == "Too dangerous"

    def test_error(self):
        tr = ToolResult(tool_name="bash", status="error", error="Failed")
        assert tr.status == "error"
        assert tr.error == "Failed"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ToolResult(tool_name="bash", status="invalid")

    def test_duration_non_negative(self):
        with pytest.raises(ValidationError):
            ToolResult(tool_name="bash", status="success", duration_ms=-1)

    def test_defaults(self):
        tr = ToolResult(tool_name="bash", status="success")
        assert tr.output is None
        assert tr.error is None
        assert tr.duration_ms == 0
        assert tr.sanitized is False
        assert tr.blocked_reason is None


# -----------------------------------------------------------------------
# RiskAssessment
# -----------------------------------------------------------------------


class TestRiskAssessment:
    def test_creation(self):
        ra = RiskAssessment(level=RiskLevel.high, classifier="rules")
        assert ra.level == RiskLevel.high
        assert ra.classifier == "rules"
        assert ra.confidence == 1.0

    def test_with_reason(self):
        ra = RiskAssessment(
            level=RiskLevel.critical,
            classifier="rules",
            matched_rule="fork-bomb",
            reason="Fork bomb detected",
            confidence=0.95,
        )
        assert ra.reason == "Fork bomb detected"
        assert ra.matched_rule == "fork-bomb"
        assert ra.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            RiskAssessment(level=RiskLevel.low, classifier="rules", confidence=1.5)
        with pytest.raises(ValidationError):
            RiskAssessment(level=RiskLevel.low, classifier="rules", confidence=-0.1)

    def test_invalid_classifier(self):
        with pytest.raises(ValidationError):
            RiskAssessment(level=RiskLevel.low, classifier="magic")


# -----------------------------------------------------------------------
# HookResult
# -----------------------------------------------------------------------


class TestHookResult:
    def test_defaults(self):
        hr = HookResult()
        assert hr.action == HookAction.allow
        assert hr.reason is None
        assert hr.severity == "info"
        assert hr.modified_input is None
        assert hr.sanitized_output is None

    def test_deny(self):
        hr = HookResult(
            action=HookAction.deny,
            reason="Secret found",
            severity="error",
        )
        assert hr.action == HookAction.deny
        assert hr.severity == "error"

    def test_sanitize_with_output(self):
        hr = HookResult(
            action=HookAction.sanitize,
            sanitized_output="[REDACTED]",
        )
        assert hr.sanitized_output == "[REDACTED]"


# -----------------------------------------------------------------------
# PermissionDecision
# -----------------------------------------------------------------------


class TestPermissionDecision:
    def test_allow(self):
        pd = PermissionDecision(action="allow", reason="Safe", source="test")
        assert pd.action == "allow"

    def test_deny(self):
        pd = PermissionDecision(action="deny", reason="Blocked", source="hook")
        assert pd.action == "deny"

    def test_ask(self):
        pd = PermissionDecision(action="ask", reason="Confirm?", source="rule")
        assert pd.action == "ask"

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            PermissionDecision(action="block", reason="x", source="y")

    def test_risk_level_optional(self):
        pd = PermissionDecision(action="allow", reason="Ok", source="test")
        assert pd.risk_level is None

    def test_with_risk_level(self):
        pd = PermissionDecision(
            action="deny",
            reason="High risk",
            source="risk",
            risk_level=RiskLevel.high,
        )
        assert pd.risk_level == RiskLevel.high


# -----------------------------------------------------------------------
# AuditRecord
# -----------------------------------------------------------------------


class TestAuditRecord:
    def _make_hash(self, tool_input: dict) -> str:
        canonical = json.dumps(tool_input, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def test_creation(self):
        h = self._make_hash({"command": "ls"})
        perm = PermissionDecision(action="allow", reason="ok", source="test")
        ar = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            session_id="sess-1",
            event_type="tool_call",
            tool_name="bash",
            tool_input_hash=h,
            permission=perm,
        )
        assert ar.tool_name == "bash"
        assert ar.event_type == "tool_call"

    def test_invalid_hash_rejected(self):
        perm = PermissionDecision(action="allow", reason="ok", source="test")
        with pytest.raises(ValidationError, match="SHA-256"):
            AuditRecord(
                timestamp=datetime.now(timezone.utc),
                session_id="sess-1",
                event_type="tool_call",
                tool_name="bash",
                tool_input_hash="not-a-valid-hash",
                permission=perm,
            )

    def test_to_jsonl(self):
        h = self._make_hash({})
        perm = PermissionDecision(action="allow", reason="ok", source="test")
        ar = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            session_id="sess-1",
            event_type="tool_call",
            tool_name="bash",
            tool_input_hash=h,
            permission=perm,
        )
        line = ar.to_jsonl()
        parsed = json.loads(line)
        assert parsed["tool_name"] == "bash"

    def test_hash_input_static(self):
        h1 = AuditRecord.hash_input({"a": 1, "b": 2})
        h2 = AuditRecord.hash_input({"b": 2, "a": 1})
        assert h1 == h2  # deterministic regardless of key order
        assert len(h1) == 64


# -----------------------------------------------------------------------
# Rule
# -----------------------------------------------------------------------


class TestRule:
    def test_creation(self):
        r = Rule(id="no-secrets", description="Never expose secrets")
        assert r.id == "no-secrets"
        assert r.description == "Never expose secrets"
        assert r.severity == RuleSeverity.error  # default
        assert r.enforcement == Enforcement.both  # default

    def test_empty_id_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            Rule(id="", description="test")

    def test_with_patterns(self):
        r = Rule(
            id="test",
            description="test",
            patterns=[{"glob": "*.py"}],
            triggers=[{"tool": "bash", "pattern": "rm"}],
            checks=["check_no_secrets"],
        )
        assert len(r.patterns) == 1
        assert len(r.triggers) == 1
        assert len(r.checks) == 1


# -----------------------------------------------------------------------
# ToolPermission
# -----------------------------------------------------------------------


class TestToolPermission:
    def test_creation(self):
        tp = ToolPermission(policy="allow")
        assert tp.policy == "allow"
        assert tp.deny_patterns == []
        assert tp.allow_paths == []

    def test_restricted(self):
        tp = ToolPermission(
            policy="restricted",
            deny_patterns=[r"rm\s+-rf"],
            ask_patterns=[r"git\s+push"],
        )
        assert tp.policy == "restricted"
        assert len(tp.deny_patterns) == 1

    def test_invalid_policy_rejected(self):
        with pytest.raises(ValidationError):
            ToolPermission(policy="maybe")


# -----------------------------------------------------------------------
# PermissionDefaults
# -----------------------------------------------------------------------


class TestPermissionDefaults:
    def test_defaults(self):
        pd = PermissionDefaults()
        assert pd.unknown_tool == "ask"
        assert pd.unknown_path == "deny"
        assert pd.on_error == "deny"

    def test_custom(self):
        pd = PermissionDefaults(unknown_tool="deny", unknown_path="allow", on_error="ask")
        assert pd.unknown_tool == "deny"


# -----------------------------------------------------------------------
# ConstitutionConfig
# -----------------------------------------------------------------------


class TestConstitutionConfig:
    def test_defaults(self):
        cc = ConstitutionConfig()
        assert cc.version == "1.0"
        assert isinstance(cc.rules, list)
        assert cc.permissions is not None

    def test_with_rules(self):
        rules = [Rule(id="test", description="Test rule")]
        cc = ConstitutionConfig(rules=rules)
        assert len(cc.rules) == 1

    def test_get_tool_permission_exists(self):
        cc = ConstitutionConfig(
            permissions={
                "defaults": PermissionDefaults().model_dump(),
                "tools": {
                    "bash": {"policy": "restricted", "deny_patterns": [r"rm"]},
                },
            }
        )
        tp = cc.get_tool_permission("bash")
        assert tp is not None
        assert tp.policy == "restricted"

    def test_get_tool_permission_missing(self):
        cc = ConstitutionConfig()
        tp = cc.get_tool_permission("nonexistent")
        assert tp is None

    def test_get_defaults(self):
        cc = ConstitutionConfig()
        defaults = cc.get_defaults()
        assert isinstance(defaults, PermissionDefaults)
        assert defaults.unknown_tool == "ask"

    def test_invalid_risk_threshold_action(self):
        with pytest.raises(ValidationError):
            ConstitutionConfig(
                risk={
                    "classifier": "rules",
                    "thresholds": {"low": "explode"},
                    "custom_rules": [],
                }
            )

    def test_hook_profile_accepts_string(self):
        cc = ConstitutionConfig(
            hooks={"profile": "strict", "pre": [], "post": []}
        )
        assert cc.hooks is not None

    def test_extra_fields_ignored(self):
        cc = ConstitutionConfig(version="2.0", unknown_field="ignored")
        assert cc.version == "2.0"


# -----------------------------------------------------------------------
# RiskPattern
# -----------------------------------------------------------------------


class TestRiskPattern:
    def test_creation(self):
        rp = RiskPattern(
            pattern=r"\brm\b",
            description="rm command",
            category="bash",
        )
        assert rp.pattern == r"\brm\b"
        assert rp.category == "bash"
