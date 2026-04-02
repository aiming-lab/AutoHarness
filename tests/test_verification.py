"""Tests for the Verification Engine.

Covers all built-in verification rules, the engine's aggregate logic,
custom rules, strict mode, and edge cases.
"""

from __future__ import annotations

import pytest

from autoharness.core.types import (
    PermissionDecision,
    RiskAssessment,
    RiskLevel,
    ToolCall,
    ToolResult,
)
from autoharness.core.verification import (
    BUILTIN_RULES,
    Evidence,
    Issue,
    RuleResult,
    VerificationEngine,
    VerificationResult,
    VerificationRule,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> VerificationEngine:
    """Default verification engine with all built-in rules."""
    return VerificationEngine()


@pytest.fixture
def strict_engine() -> VerificationEngine:
    """Strict verification engine (warnings become errors)."""
    return VerificationEngine(strict=True)


def _bash_call(command: str) -> ToolCall:
    """Helper to create a bash tool call."""
    return ToolCall(tool_name="bash", tool_input={"command": command})


def _write_call(file_path: str, content: str = "...") -> ToolCall:
    """Helper to create a write tool call."""
    return ToolCall(tool_name="Write", tool_input={"file_path": file_path, "content": content})


def _edit_call(file_path: str) -> ToolCall:
    """Helper to create an edit tool call."""
    return ToolCall(
        tool_name="Edit",
        tool_input={"file_path": file_path, "old_string": "a", "new_string": "b"},
    )


def _read_call(file_path: str) -> ToolCall:
    """Helper to create a read tool call."""
    return ToolCall(tool_name="Read", tool_input={"file_path": file_path})


def _success_result(tool_name: str = "bash", output: str = "") -> ToolResult:
    """Helper to create a successful tool result."""
    return ToolResult(tool_name=tool_name, status="success", output=output)


def _error_result(tool_name: str = "bash", error: str = "Command failed") -> ToolResult:
    """Helper to create an error tool result."""
    return ToolResult(tool_name=tool_name, status="error", error=error)


# ---------------------------------------------------------------------------
# Tests: tests_actually_ran rule
# ---------------------------------------------------------------------------


class TestTestsActuallyRan:
    """Tests for the tests_actually_ran verification rule."""

    def test_pass_when_pytest_ran(self, engine: VerificationEngine):
        tool_calls = [
            _write_call("/src/app.py"),
            _bash_call("pytest tests/"),
        ]
        tool_results = [
            _success_result("Write"),
            _success_result("bash", "5 passed in 1.23s"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="All tests pass",
        )
        # tests_actually_ran should PASS
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert len(ran_rule) == 1
        assert ran_rule[0].status == VerificationStatus.PASS

    def test_fail_when_no_test_command(self, engine: VerificationEngine):
        tool_calls = [
            _write_call("/src/app.py"),
            _read_call("/tests/test_app.py"),  # Just reading, not running
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="All tests pass",
        )
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert len(ran_rule) == 1
        assert ran_rule[0].status == VerificationStatus.FAIL

    def test_skipped_when_no_test_claim(self, engine: VerificationEngine):
        tool_calls = [_write_call("/src/app.py")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Refactored the module",
        )
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert len(ran_rule) == 1
        assert ran_rule[0].status == VerificationStatus.SKIPPED

    def test_detects_npm_test(self, engine: VerificationEngine):
        tool_calls = [_bash_call("npm test")]
        tool_results = [_success_result("bash", "Tests: 12 passed")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="All tests pass",
        )
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert ran_rule[0].status == VerificationStatus.PASS

    def test_detects_cargo_test(self, engine: VerificationEngine):
        tool_calls = [_bash_call("cargo test --release")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Tests pass",
        )
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert ran_rule[0].status == VerificationStatus.PASS

    def test_partial_when_test_output_has_errors(self, engine: VerificationEngine):
        tool_calls = [_bash_call("pytest tests/")]
        tool_results = [
            _success_result("bash", "FAILED tests/test_foo.py::test_bar - AssertionError"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="All tests pass",
        )
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert ran_rule[0].status == VerificationStatus.PARTIAL

    def test_python_m_pytest(self, engine: VerificationEngine):
        tool_calls = [_bash_call("python -m pytest -xvs")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Tests pass",
        )
        ran_rule = [rr for rr in verdict.rule_results if rr.rule_id == "tests_actually_ran"]
        assert ran_rule[0].status == VerificationStatus.PASS


# ---------------------------------------------------------------------------
# Tests: lint_passed rule
# ---------------------------------------------------------------------------


class TestLintPassed:
    """Tests for the lint_passed verification rule."""

    def test_pass_when_ruff_ran(self, engine: VerificationEngine):
        tool_calls = [_bash_call("ruff check src/")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="No lint errors",
        )
        lint_rule = [rr for rr in verdict.rule_results if rr.rule_id == "lint_passed"]
        assert len(lint_rule) == 1
        assert lint_rule[0].status == VerificationStatus.PASS

    def test_fail_when_no_lint_command(self, engine: VerificationEngine):
        tool_calls = [_write_call("/src/app.py")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Linting clean",
        )
        lint_rule = [rr for rr in verdict.rule_results if rr.rule_id == "lint_passed"]
        assert lint_rule[0].status == VerificationStatus.FAIL

    def test_skipped_when_no_lint_claim(self, engine: VerificationEngine):
        tool_calls = [_write_call("/src/app.py")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Fixed the bug",
        )
        lint_rule = [rr for rr in verdict.rule_results if rr.rule_id == "lint_passed"]
        assert lint_rule[0].status == VerificationStatus.SKIPPED

    def test_detects_eslint(self, engine: VerificationEngine):
        tool_calls = [_bash_call("eslint src/ --fix")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Lint passed",
        )
        lint_rule = [rr for rr in verdict.rule_results if rr.rule_id == "lint_passed"]
        assert lint_rule[0].status == VerificationStatus.PASS

    def test_detects_mypy(self, engine: VerificationEngine):
        tool_calls = [_bash_call("mypy src/")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Type check passed",
        )
        lint_rule = [rr for rr in verdict.rule_results if rr.rule_id == "lint_passed"]
        assert lint_rule[0].status == VerificationStatus.PASS


# ---------------------------------------------------------------------------
# Tests: no_skipped_errors rule
# ---------------------------------------------------------------------------


class TestNoSkippedErrors:
    """Tests for the no_skipped_errors verification rule."""

    def test_pass_when_no_errors(self, engine: VerificationEngine):
        tool_calls = [_bash_call("echo hello")]
        tool_results = [_success_result()]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="Done",
        )
        err_rule = [rr for rr in verdict.rule_results if rr.rule_id == "no_skipped_errors"]
        assert err_rule[0].status == VerificationStatus.PASS

    def test_partial_when_last_result_is_error(self, engine: VerificationEngine):
        tool_calls = [_bash_call("failing_command")]
        tool_results = [_error_result()]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="Done",
        )
        err_rule = [rr for rr in verdict.rule_results if rr.rule_id == "no_skipped_errors"]
        assert err_rule[0].status == VerificationStatus.PARTIAL

    def test_pass_when_error_followed_by_fix(self, engine: VerificationEngine):
        tool_calls = [
            _bash_call("failing_command"),
            _write_call("/src/fix.py"),
            _bash_call("working_command"),
        ]
        tool_results = [
            _error_result(),
            _success_result("Write"),
            _success_result(),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="Fixed and working",
        )
        err_rule = [rr for rr in verdict.rule_results if rr.rule_id == "no_skipped_errors"]
        assert err_rule[0].status == VerificationStatus.PASS


# ---------------------------------------------------------------------------
# Tests: claimed_vs_actual rule
# ---------------------------------------------------------------------------


class TestClaimedVsActual:
    """Tests for the claimed_vs_actual verification rule."""

    def test_pass_when_output_matches_claim(self, engine: VerificationEngine):
        tool_calls = [_bash_call("pytest")]
        tool_results = [_success_result("bash", "10 passed, 0 errors")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="All tests pass",
        )
        claim_rule = [rr for rr in verdict.rule_results if rr.rule_id == "claimed_vs_actual"]
        assert claim_rule[0].status == VerificationStatus.PASS

    def test_fail_when_claim_contradicts_output(self, engine: VerificationEngine):
        tool_calls = [_bash_call("pytest")]
        tool_results = [_success_result("bash", "FAILED test_foo.py - AssertionError\n2 failed")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="All tests pass",
        )
        claim_rule = [rr for rr in verdict.rule_results if rr.rule_id == "claimed_vs_actual"]
        assert claim_rule[0].status == VerificationStatus.FAIL

    def test_skipped_when_no_claimed_result(self, engine: VerificationEngine):
        tool_calls = [_bash_call("echo hello")]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="",
        )
        claim_rule = [rr for rr in verdict.rule_results if rr.rule_id == "claimed_vs_actual"]
        assert claim_rule[0].status == VerificationStatus.SKIPPED

    def test_warning_when_blocked_tools_exist(self, engine: VerificationEngine):
        tool_calls = [_bash_call("deploy.sh")]
        tool_results = [
            ToolResult(tool_name="bash", status="blocked", blocked_reason="Denied by policy"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="Deployment succeeded",
        )
        claim_rule = [rr for rr in verdict.rule_results if rr.rule_id == "claimed_vs_actual"]
        # Should have at least a warning about blocked tools
        warnings = [i for i in claim_rule[0].issues if i.severity == "warning"]
        assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# Tests: files_actually_tested rule
# ---------------------------------------------------------------------------


class TestFilesActuallyTested:
    """Tests for the files_actually_tested verification rule."""

    def test_pass_when_tests_after_write(self, engine: VerificationEngine):
        tool_calls = [
            _write_call("/src/app.py"),
            _bash_call("pytest tests/"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Done",
        )
        files_rule = [rr for rr in verdict.rule_results if rr.rule_id == "files_actually_tested"]
        assert files_rule[0].status == VerificationStatus.PASS

    def test_partial_when_tests_before_write(self, engine: VerificationEngine):
        tool_calls = [
            _bash_call("pytest tests/"),
            _write_call("/src/app.py"),  # Wrote AFTER testing
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Done",
        )
        files_rule = [rr for rr in verdict.rule_results if rr.rule_id == "files_actually_tested"]
        assert files_rule[0].status == VerificationStatus.PARTIAL

    def test_fail_when_no_tests_after_write(self, engine: VerificationEngine):
        tool_calls = [
            _write_call("/src/app.py"),
            _write_call("/src/utils.py"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Refactored modules",
        )
        files_rule = [rr for rr in verdict.rule_results if rr.rule_id == "files_actually_tested"]
        assert files_rule[0].status == VerificationStatus.FAIL

    def test_skipped_when_no_writes(self, engine: VerificationEngine):
        tool_calls = [
            _read_call("/src/app.py"),
            _bash_call("echo hello"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Reviewed code",
        )
        files_rule = [rr for rr in verdict.rule_results if rr.rule_id == "files_actually_tested"]
        assert files_rule[0].status == VerificationStatus.SKIPPED

    def test_edit_counts_as_modification(self, engine: VerificationEngine):
        tool_calls = [
            _edit_call("/src/app.py"),
            _bash_call("pytest -x"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="Done",
        )
        files_rule = [rr for rr in verdict.rule_results if rr.rule_id == "files_actually_tested"]
        assert files_rule[0].status == VerificationStatus.PASS


# ---------------------------------------------------------------------------
# Tests: VerificationEngine aggregate behavior
# ---------------------------------------------------------------------------


class TestVerificationEngine:
    """Tests for the engine's aggregate logic."""

    def test_overall_pass(self, engine: VerificationEngine):
        """All rules pass -> overall PASS."""
        tool_calls = [
            _write_call("/src/app.py"),
            _bash_call("pytest tests/"),
            _bash_call("ruff check src/"),
        ]
        tool_results = [
            _success_result("Write"),
            _success_result("bash", "5 passed"),
            _success_result("bash", "All checks passed!"),
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="All tests pass, lint clean",
        )
        assert verdict.status == VerificationStatus.PASS
        assert verdict.passed is True
        assert verdict.error_count == 0

    def test_overall_fail_when_any_error(self, engine: VerificationEngine):
        """Any error-severity rule fails -> overall FAIL."""
        tool_calls = [
            _read_call("/tests/test_app.py"),  # Just read, didn't run
        ]
        verdict = engine.verify(
            tool_calls=tool_calls,
            claimed_result="All tests pass",
        )
        assert verdict.status == VerificationStatus.FAIL
        assert verdict.passed is False
        assert verdict.error_count >= 1

    def test_strict_mode_promotes_warnings(self, strict_engine: VerificationEngine):
        """In strict mode, warnings become errors."""
        tool_calls = [
            _bash_call("failing_command"),
        ]
        tool_results = [_error_result()]
        verdict = strict_engine.verify(
            tool_calls=tool_calls,
            tool_results=tool_results,
            claimed_result="Done",
        )
        # no_skipped_errors returns PARTIAL with warning, strict treats as FAIL
        assert verdict.status == VerificationStatus.FAIL

    def test_empty_tool_calls(self, engine: VerificationEngine):
        verdict = engine.verify(
            tool_calls=[],
            claimed_result="Everything works",
        )
        # With no tool calls, most rules are skipped
        assert verdict.status in (VerificationStatus.PASS, VerificationStatus.PARTIAL)

    def test_confidence_scales_with_coverage(self, engine: VerificationEngine):
        # When most rules are skipped, confidence should be lower
        verdict_low = engine.verify(
            tool_calls=[],
            claimed_result="Nothing specific",
        )
        verdict_high = engine.verify(
            tool_calls=[
                _write_call("/src/app.py"),
                _bash_call("pytest tests/"),
                _bash_call("ruff check src/"),
            ],
            tool_results=[
                _success_result("Write"),
                _success_result("bash", "5 passed"),
                _success_result("bash"),
            ],
            claimed_result="All tests pass, lint clean",
        )
        assert verdict_high.confidence >= verdict_low.confidence

    def test_summary_is_populated(self, engine: VerificationEngine):
        verdict = engine.verify(
            tool_calls=[_bash_call("echo hello")],
            claimed_result="Done",
        )
        assert verdict.summary != ""
        assert "Verification" in verdict.summary

    def test_custom_rule(self):
        """Users can add custom verification rules."""
        def custom_check(tool_calls, tool_results, claimed_result, context):
            if "magic" in claimed_result:
                return RuleResult(
                    rule_id="no_magic",
                    status=VerificationStatus.FAIL,
                    issues=[Issue(
                        rule_id="no_magic",
                        severity="error",
                        message="No magic claims allowed",
                    )],
                )
            return RuleResult(rule_id="no_magic", status=VerificationStatus.PASS)

        custom_rule = VerificationRule(
            id="no_magic",
            description="Reject claims of magic",
            check=custom_check,
        )
        engine = VerificationEngine(rules=[custom_rule])

        verdict_fail = engine.verify(
            tool_calls=[],
            claimed_result="It works like magic",
        )
        assert verdict_fail.status == VerificationStatus.FAIL

        verdict_pass = engine.verify(
            tool_calls=[],
            claimed_result="It works correctly",
        )
        assert verdict_pass.status == VerificationStatus.PASS

    def test_add_and_remove_rule(self, engine: VerificationEngine):
        initial_count = len(engine.rules)

        custom_rule = VerificationRule(
            id="custom_test",
            description="Test rule",
            check=lambda tc, tr, cr, ctx: RuleResult(
                rule_id="custom_test",
                status=VerificationStatus.PASS,
            ),
        )
        engine.add_rule(custom_rule)
        assert len(engine.rules) == initial_count + 1

        removed = engine.remove_rule("custom_test")
        assert removed is True
        assert len(engine.rules) == initial_count

        removed_again = engine.remove_rule("nonexistent")
        assert removed_again is False

    def test_require_all_rules(self):
        """When require_all_rules=True, non-applicable rules FAIL."""
        engine = VerificationEngine(require_all_rules=True)
        # No test claims, so tests_actually_ran is "not applicable" -> FAIL
        verdict = engine.verify(
            tool_calls=[_bash_call("echo hello")],
            claimed_result="Just echoed",
        )
        # Should have failures from non-applicable rules
        failed = [rr for rr in verdict.rule_results if rr.status == VerificationStatus.FAIL]
        assert len(failed) >= 1

    def test_rule_exception_handling(self):
        """Rules that raise exceptions are caught and recorded as FAIL."""
        def broken_check(tc, tr, cr, ctx):
            raise RuntimeError("This rule is broken")

        engine = VerificationEngine(rules=[
            VerificationRule(
                id="broken",
                description="A broken rule",
                check=broken_check,
            ),
        ])
        verdict = engine.verify(
            tool_calls=[_bash_call("echo hello")],
            claimed_result="Done",
        )
        assert verdict.status == VerificationStatus.FAIL
        broken_results = [rr for rr in verdict.rule_results if rr.rule_id == "broken"]
        assert broken_results[0].status == VerificationStatus.FAIL
        assert "exception" in broken_results[0].issues[0].message.lower()


# ---------------------------------------------------------------------------
# Tests: Data types
# ---------------------------------------------------------------------------


class TestDataTypes:
    """Tests for verification data types."""

    def test_evidence_creation(self):
        e = Evidence(rule_id="test", description="A test", data={"key": "val"})
        assert e.rule_id == "test"
        assert e.data == {"key": "val"}

    def test_issue_creation(self):
        i = Issue(
            rule_id="test",
            severity="error",
            message="Something bad",
            suggestion="Fix it",
        )
        assert i.severity == "error"
        assert i.suggestion == "Fix it"

    def test_verification_result_properties(self):
        vr = VerificationResult(
            status=VerificationStatus.PARTIAL,
            issues=[
                Issue(rule_id="a", severity="error", message="err"),
                Issue(rule_id="b", severity="warning", message="warn"),
                Issue(rule_id="c", severity="warning", message="warn2"),
            ],
        )
        assert vr.error_count == 1
        assert vr.warning_count == 2
        assert vr.passed is False

    def test_verification_status_values(self):
        assert VerificationStatus.PASS.value == "PASS"
        assert VerificationStatus.FAIL.value == "FAIL"
        assert VerificationStatus.PARTIAL.value == "PARTIAL"
        assert VerificationStatus.SKIPPED.value == "SKIPPED"

    def test_builtin_rules_exist(self):
        assert len(BUILTIN_RULES) >= 5
        rule_ids = {r.id for r in BUILTIN_RULES}
        assert "tests_actually_ran" in rule_ids
        assert "lint_passed" in rule_ids
        assert "no_skipped_errors" in rule_ids
        assert "claimed_vs_actual" in rule_ids
        assert "files_actually_tested" in rule_ids

    def test_engine_repr(self, engine: VerificationEngine):
        r = repr(engine)
        assert "VerificationEngine" in r
        assert "rules=" in r


# ---------------------------------------------------------------------------
# Tests: Policy engine adapter (unit tests, no network)
# ---------------------------------------------------------------------------


class TestPolicyEngineAdapter:
    """Unit tests for policy engine adapters (no real network calls)."""

    def test_opa_parse_boolean_true(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        decision = opa._parse_opa_response({"result": True})
        assert decision.action == "allow"
        assert decision.source == "opa"

    def test_opa_parse_boolean_false(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        decision = opa._parse_opa_response({"result": False})
        assert decision.action == "deny"

    def test_opa_parse_structured_response(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        decision = opa._parse_opa_response({
            "result": {"decision": "ask", "reason": "Needs confirmation"},
        })
        assert decision.action == "ask"
        assert "confirmation" in decision.reason.lower()

    def test_opa_parse_missing_result(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        decision = opa._parse_opa_response({})
        assert decision.source == "policy_engine_fallback"
        assert decision.action == "deny"  # default fallback

    def test_opa_parse_unknown_decision(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        decision = opa._parse_opa_response({
            "result": {"decision": "maybe", "reason": "Unsure"},
        })
        assert decision.source == "policy_engine_fallback"

    def test_opa_fallback_on_connection_error(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(
            url="http://localhost:99999",  # Unreachable
            fallback_action="ask",
            timeout_seconds=0.1,
        )
        tc = ToolCall(tool_name="bash", tool_input={"command": "echo hi"})
        risk = _make_risk()
        decision = opa.evaluate(tc, risk, {})
        assert decision.action == "ask"
        assert decision.source == "policy_engine_fallback"

    def test_opa_endpoint_property(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://opa.example.com:8181/", policy_path="/custom/path/")
        assert opa.endpoint == "http://opa.example.com:8181/v1/data/custom/path"

    def test_opa_repr(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        r = repr(opa)
        assert "OPAIntegration" in r
        assert "endpoint=" in r

    def test_cedar_repr(self):
        from autoharness.integrations.policy_engines import CedarIntegration

        cedar = CedarIntegration(policy_store_id="ps-test", region="eu-west-1")
        r = repr(cedar)
        assert "CedarIntegration" in r
        assert "ps-test" in r

    def test_cedar_context_building(self):
        from autoharness.integrations.policy_engines import CedarIntegration

        cedar = CedarIntegration(policy_store_id="ps-test")
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "echo hi", "count": 5, "verbose": True},
        )
        risk = _make_risk()
        ctx = cedar._build_cedar_context(tc, risk, {"project_dir": "/tmp"})

        assert ctx["risk_level"] == {"string": "low"}
        assert ctx["tool_name"] == {"string": "bash"}
        assert ctx["project_dir"] == {"string": "/tmp"}
        assert ctx["input_command"] == {"string": "echo hi"}
        # Integer and boolean inputs
        assert ctx["input_count"] == {"long": 5}
        assert ctx["input_verbose"] == {"boolean": True}

    def test_cedar_fallback_on_missing_boto3(self):
        """Cedar should fall back gracefully when boto3 is not installed."""
        from autoharness.integrations.policy_engines import CedarIntegration

        cedar = CedarIntegration(
            policy_store_id="ps-test",
            fallback_action="deny",
        )
        # Force _client to None and mock _get_client to raise ImportError
        cedar._client = None

        def mock_get_client():
            raise ImportError("No module named 'boto3'")

        cedar._get_client = mock_get_client

        tc = ToolCall(tool_name="read", tool_input={"file_path": "/tmp/test"})
        risk = _make_risk()
        decision = cedar.evaluate(tc, risk, {})
        assert decision.action == "deny"
        assert decision.source == "policy_engine_fallback"

    def test_cedar_parse_allow_response(self):
        from autoharness.integrations.policy_engines import CedarIntegration

        cedar = CedarIntegration(policy_store_id="ps-test")
        decision = cedar._parse_cedar_response({
            "decision": "ALLOW",
            "determiningPolicies": [{"policyId": "policy-001"}],
            "errors": [],
        })
        assert decision.action == "allow"
        assert decision.source == "cedar"
        assert "policy-001" in decision.reason

    def test_cedar_parse_deny_response(self):
        from autoharness.integrations.policy_engines import CedarIntegration

        cedar = CedarIntegration(policy_store_id="ps-test")
        decision = cedar._parse_cedar_response({
            "decision": "DENY",
            "determiningPolicies": [],
            "errors": [],
        })
        assert decision.action == "deny"
        assert decision.source == "cedar"

    def test_policy_chain_first_engine_wins(self):
        from autoharness.integrations.policy_engines import OPAIntegration, PolicyEngineChain

        # Create two OPA engines; mock their evaluate methods
        engine1 = OPAIntegration(url="http://engine1:8181")
        engine2 = OPAIntegration(url="http://engine2:8181")

        tc = ToolCall(tool_name="read", tool_input={"file_path": "/tmp/test"})
        risk = _make_risk()

        # Mock engine1 to return allow
        engine1.evaluate = lambda t, r, c: PermissionDecision(
            action="allow", reason="Engine 1 allows", source="opa"
        )
        engine2.evaluate = lambda t, r, c: PermissionDecision(
            action="deny", reason="Engine 2 denies", source="opa"
        )

        chain = PolicyEngineChain([engine1, engine2])
        decision = chain.evaluate(tc, risk, {})
        assert decision.action == "allow"
        assert "Engine 1" in decision.reason

    def test_policy_chain_falls_through_on_fallback(self):
        from autoharness.integrations.policy_engines import OPAIntegration, PolicyEngineChain

        engine1 = OPAIntegration(url="http://engine1:8181")
        engine2 = OPAIntegration(url="http://engine2:8181")

        tc = ToolCall(tool_name="read", tool_input={"file_path": "/tmp/test"})
        risk = _make_risk()

        # Engine1 returns fallback, engine2 returns real decision
        engine1.evaluate = lambda t, r, c: PermissionDecision(
            action="deny", reason="fallback", source="policy_engine_fallback"
        )
        engine2.evaluate = lambda t, r, c: PermissionDecision(
            action="allow", reason="Engine 2 allows", source="opa"
        )

        chain = PolicyEngineChain([engine1, engine2])
        decision = chain.evaluate(tc, risk, {})
        assert decision.action == "allow"

    def test_policy_chain_requires_at_least_one_engine(self):
        from autoharness.integrations.policy_engines import PolicyEngineChain

        with pytest.raises(ValueError, match="at least one"):
            PolicyEngineChain([])

    def test_build_input_payload(self):
        from autoharness.integrations.policy_engines import OPAIntegration

        opa = OPAIntegration(url="http://localhost:8181")
        tc = ToolCall(
            tool_name="bash",
            tool_input={"command": "ls"},
            session_id="sess-1",
        )
        risk = _make_risk()
        payload = opa._build_input_payload(tc, risk, {
            "session_id": "sess-1",
            "agent_role": "coder",
            "project_dir": "/home/project",
        })
        assert payload["tool_name"] == "bash"
        assert payload["risk_level"] == "low"
        assert payload["session_id"] == "sess-1"
        assert payload["agent_role"] == "coder"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_risk(
    level: str = "low",
    reason: str = "Test risk",
) -> RiskAssessment:
    return RiskAssessment(
        level=RiskLevel(level),
        classifier="rules",
        reason=reason,
    )
