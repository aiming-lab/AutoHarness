"""Verification Engine — adversarial validation of agent work.

Adversarial verification agent that explicitly combats:
  - "Verification avoidance" — reading code instead of running tests
  - "Seduced by the first 80%" — declaring success too early
  - "Silent error swallowing" — catching exceptions without addressing them

This module provides a pure rule-based verification layer (no LLM required)
that audits a sequence of tool calls against a set of verification rules.
It answers: "Did the agent *actually* do what it claims?"

Architecture:
    VerificationRule  — defines what to check (e.g., "tests must have run")
    VerificationEngine — orchestrates rules, produces a VerificationResult
    VerificationResult — verdict with evidence and issues

The engine is designed to run *after* a sequence of tool calls, comparing
the claimed result against the actual tool call history.

Usage::

    from autoharness.core.verification import VerificationEngine

    verifier = VerificationEngine()

    verdict = verifier.verify(
        tool_calls=recent_tool_calls,
        claimed_result="All tests pass",
        project_dir="/path/to/project",
    )

    if verdict.status != "PASS":
        print(f"Verification failed: {verdict.issues}")
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from autoharness.core.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class VerificationStatus(str, Enum):
    """Outcome of a verification check."""

    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class Evidence:
    """A single piece of evidence collected during verification.

    Attributes
    ----------
    rule_id : str
        Which rule produced this evidence.
    description : str
        Human-readable summary.
    data : dict
        Structured data supporting the evidence (tool names, outputs, etc.).
    """

    rule_id: str
    description: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Issue:
    """A problem found during verification.

    Attributes
    ----------
    rule_id : str
        Which rule flagged this issue.
    severity : str
        "error", "warning", or "info".
    message : str
        Human-readable description of the problem.
    suggestion : str | None
        What should be done to fix this.
    """

    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str
    suggestion: str | None = None


@dataclass(frozen=True)
class RuleResult:
    """Result from a single verification rule execution.

    Attributes
    ----------
    rule_id : str
        Identifier of the rule that ran.
    status : VerificationStatus
        PASS, FAIL, PARTIAL, or SKIPPED.
    evidence : list[Evidence]
        Supporting evidence collected.
    issues : list[Issue]
        Problems found.
    """

    rule_id: str
    status: VerificationStatus
    evidence: list[Evidence] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationResult:
    """Aggregate verdict from running all applicable verification rules.

    Attributes
    ----------
    status : VerificationStatus
        Overall verdict: PASS (all rules pass), FAIL (any error-severity
        rule fails), PARTIAL (warnings but no errors).
    evidence : list[Evidence]
        All evidence from all rules.
    issues : list[Issue]
        All issues from all rules.
    rule_results : list[RuleResult]
        Per-rule results for detailed inspection.
    confidence : float
        Confidence in the verdict (0.0-1.0). Based on how many rules
        were applicable and how much evidence was collected.
    summary : str
        Human-readable one-line summary.
    """

    status: VerificationStatus
    evidence: list[Evidence] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    rule_results: list[RuleResult] = field(default_factory=list)
    confidence: float = 1.0
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASS

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


# ---------------------------------------------------------------------------
# Verification Rule
# ---------------------------------------------------------------------------


@dataclass
class VerificationRule:
    """Defines a single verification check.

    Attributes
    ----------
    id : str
        Unique identifier (e.g., "tests_actually_ran").
    description : str
        What this rule verifies.
    check : Callable
        The check function. Signature:
            (tool_calls, tool_results, claimed_result, context) -> RuleResult
    severity : str
        Default severity for issues raised by this rule.
    applicable_when : Callable | None
        Optional predicate. If provided, the rule only runs when this
        returns True. Signature: (tool_calls, claimed_result, context) -> bool
    """

    id: str
    description: str
    check: Callable[
        [list[ToolCall], list[ToolResult], str, dict[str, Any]],
        RuleResult,
    ]
    severity: Literal["error", "warning", "info"] = "error"
    applicable_when: Callable[
        [list[ToolCall], str, dict[str, Any]],
        bool,
    ] | None = None


# ---------------------------------------------------------------------------
# Built-in verification rules
# ---------------------------------------------------------------------------

# Test-related command patterns
_TEST_COMMAND_PATTERNS = [
    re.compile(r"\bpytest\b"),
    re.compile(r"\bpython\s+-m\s+pytest\b"),
    re.compile(r"\bpython\s+-m\s+unittest\b"),
    re.compile(r"\bnpm\s+test\b"),
    re.compile(r"\bnpx\s+jest\b"),
    re.compile(r"\bnpx\s+vitest\b"),
    re.compile(r"\byarn\s+test\b"),
    re.compile(r"\bcargo\s+test\b"),
    re.compile(r"\bgo\s+test\b"),
    re.compile(r"\bmake\s+test\b"),
    re.compile(r"\brspec\b"),
    re.compile(r"\bphpunit\b"),
    re.compile(r"\bdotnet\s+test\b"),
    re.compile(r"\bmvn\s+test\b"),
    re.compile(r"\bgradle\s+test\b"),
]

# Lint-related command patterns
_LINT_COMMAND_PATTERNS = [
    re.compile(r"\bruff\b"),
    re.compile(r"\bflake8\b"),
    re.compile(r"\bpylint\b"),
    re.compile(r"\bmypy\b"),
    re.compile(r"\bpyright\b"),
    re.compile(r"\beslint\b"),
    re.compile(r"\btsc\b(?!.*\brun\b)"),  # tsc but not tsc-run
    re.compile(r"\bbiome\b"),
    re.compile(r"\bprettier\b.*--check"),
    re.compile(r"\bcargo\s+clippy\b"),
    re.compile(r"\bgolangci-lint\b"),
    re.compile(r"\brubocop\b"),
]

# Patterns indicating test claims in natural language
_TEST_CLAIM_PATTERNS = [
    re.compile(r"(?i)\btests?\s+pass"),
    re.compile(r"(?i)\ball\s+tests?\s+(?:pass|succeed|green)"),
    re.compile(r"(?i)\btest\s+suite\s+(?:pass|succeed|green)"),
    re.compile(r"(?i)\bno\s+(?:test\s+)?failures?\b"),
    re.compile(r"(?i)\b\d+\s+(?:tests?\s+)?passed\b"),
]

# Patterns indicating lint claims
_LINT_CLAIM_PATTERNS = [
    re.compile(r"(?i)\blint\s+pass"),
    re.compile(r"(?i)\bno\s+lint\s+(?:errors?|warnings?|issues?)"),
    re.compile(r"(?i)\blinting\s+(?:clean|pass)"),
    re.compile(r"(?i)\btype\s*check\s+pass"),
]

# Patterns indicating error/failure in tool output
_ERROR_PATTERNS = [
    re.compile(r"(?i)\berror\b(?!.*\b0\s+errors?\b)"),
    re.compile(r"(?i)\bfailed\b"),
    re.compile(r"(?i)\bfailure\b"),
    re.compile(r"(?i)\btraceback\b"),
    re.compile(r"(?i)\bexception\b"),
    re.compile(r"(?i)\bpanic\b"),
    re.compile(r"(?i)exit\s+code\s+[1-9]"),
    re.compile(r"(?i)returned?\s+(?:non-?zero|[1-9]\d*)"),
]

# Patterns indicating success in tool output
_SUCCESS_PATTERNS = [
    re.compile(r"(?i)\b\d+\s+passed\b"),
    re.compile(r"(?i)\ball\s+\d+\s+tests?\s+passed\b"),
    re.compile(r"(?i)\bOK\b"),
    re.compile(r"(?i)\b0\s+(?:errors?|failures?)\b"),
    re.compile(r"(?i)\b(?:success(?:ful|fully|ed)?|succeeded)\b"),
    re.compile(r"(?i)exit\s+code\s+0\b"),
]


def _extract_commands(tool_calls: list[ToolCall]) -> list[str]:
    """Extract command strings from bash-type tool calls."""
    commands = []
    bash_tools = {"bash", "Bash", "shell", "terminal", "execute", "run"}
    for tc in tool_calls:
        if tc.tool_name in bash_tools:
            cmd = tc.tool_input.get("command", "")
            if isinstance(cmd, str) and cmd:
                commands.append(cmd)
    return commands


def _extract_modified_files(tool_calls: list[ToolCall]) -> set[str]:
    """Extract file paths that were modified (written/edited)."""
    write_tools = {"write", "Write", "edit", "Edit", "file_write", "file_edit"}
    files = set()
    for tc in tool_calls:
        if tc.tool_name in write_tools:
            for key in ("file_path", "path", "file", "filename"):
                val = tc.tool_input.get(key)
                if isinstance(val, str) and val:
                    files.add(val)
    return files


def _extract_outputs(tool_results: list[ToolResult]) -> list[str]:
    """Extract string outputs from tool results."""
    outputs = []
    for tr in tool_results:
        if tr.output is not None:
            outputs.append(str(tr.output))
    return outputs


# --- Rule: tests_actually_ran ---


def _check_tests_actually_ran(
    tool_calls: list[ToolCall],
    tool_results: list[ToolResult],
    claimed_result: str,
    context: dict[str, Any],
) -> RuleResult:
    """Verify that test commands were actually executed.

    Flags when the agent claims tests pass but no test command appears
    in the tool call history. This catches "verification avoidance" —
    the agent reading test files instead of running them.
    """
    commands = _extract_commands(tool_calls)

    test_commands_found = []
    for cmd in commands:
        for pattern in _TEST_COMMAND_PATTERNS:
            if pattern.search(cmd):
                test_commands_found.append(cmd)
                break

    evidence = []
    issues = []

    if test_commands_found:
        evidence.append(Evidence(
            rule_id="tests_actually_ran",
            description=f"Found {len(test_commands_found)} test command(s) in history",
            data={"commands": test_commands_found},
        ))

        # Check if any test results indicate failure
        outputs = _extract_outputs(tool_results)
        error_in_output = False
        success_in_output = False
        for output in outputs:
            for pat in _ERROR_PATTERNS:
                if pat.search(output):
                    error_in_output = True
                    break
            for pat in _SUCCESS_PATTERNS:
                if pat.search(output):
                    success_in_output = True
                    break

        if error_in_output and not success_in_output:
            issues.append(Issue(
                rule_id="tests_actually_ran",
                severity="warning",
                message="Test output contains error indicators despite test claims",
                suggestion="Review test output carefully — errors may have been overlooked",
            ))
            return RuleResult(
                rule_id="tests_actually_ran",
                status=VerificationStatus.PARTIAL,
                evidence=evidence,
                issues=issues,
            )

        return RuleResult(
            rule_id="tests_actually_ran",
            status=VerificationStatus.PASS,
            evidence=evidence,
        )
    else:
        issues.append(Issue(
            rule_id="tests_actually_ran",
            severity="error",
            message="Agent claims tests pass, but no test command was found in tool call history",
            suggestion="Run the test suite (e.g., 'pytest', 'npm test') to verify claims",
        ))
        return RuleResult(
            rule_id="tests_actually_ran",
            status=VerificationStatus.FAIL,
            evidence=[Evidence(
                rule_id="tests_actually_ran",
                description="No test commands found in tool call history",
                data={"all_commands": commands},
            )],
            issues=issues,
        )


def _tests_applicable(
    tool_calls: list[ToolCall],
    claimed_result: str,
    context: dict[str, Any],
) -> bool:
    """This rule applies when the agent claims tests passed."""
    return any(pat.search(claimed_result) for pat in _TEST_CLAIM_PATTERNS)


# --- Rule: lint_passed ---


def _check_lint_passed(
    tool_calls: list[ToolCall],
    tool_results: list[ToolResult],
    claimed_result: str,
    context: dict[str, Any],
) -> RuleResult:
    """Verify that linting was actually performed."""
    commands = _extract_commands(tool_calls)

    lint_commands_found = []
    for cmd in commands:
        for pattern in _LINT_COMMAND_PATTERNS:
            if pattern.search(cmd):
                lint_commands_found.append(cmd)
                break

    if lint_commands_found:
        return RuleResult(
            rule_id="lint_passed",
            status=VerificationStatus.PASS,
            evidence=[Evidence(
                rule_id="lint_passed",
                description=f"Found {len(lint_commands_found)} lint command(s)",
                data={"commands": lint_commands_found},
            )],
        )
    else:
        return RuleResult(
            rule_id="lint_passed",
            status=VerificationStatus.FAIL,
            evidence=[Evidence(
                rule_id="lint_passed",
                description="No lint commands found in tool call history",
                data={"all_commands": commands},
            )],
            issues=[Issue(
                rule_id="lint_passed",
                severity="error",
                message="Agent claims linting passed, but no lint command was found",
                suggestion="Run the linter (e.g., 'ruff check', 'eslint') to verify",
            )],
        )


def _lint_applicable(
    tool_calls: list[ToolCall],
    claimed_result: str,
    context: dict[str, Any],
) -> bool:
    """This rule applies when the agent claims linting passed."""
    return any(pat.search(claimed_result) for pat in _LINT_CLAIM_PATTERNS)


# --- Rule: no_skipped_errors ---


def _check_no_skipped_errors(
    tool_calls: list[ToolCall],
    tool_results: list[ToolResult],
    claimed_result: str,
    context: dict[str, Any],
) -> RuleResult:
    """Check that tool errors were not silently ignored.

    Scans tool results for error statuses and flags any that weren't
    addressed (i.e., no subsequent fix attempt visible in the tool history).
    """
    error_results = [
        tr for tr in tool_results
        if tr.status == "error" or (tr.error is not None and tr.error.strip())
    ]

    if not error_results:
        return RuleResult(
            rule_id="no_skipped_errors",
            status=VerificationStatus.PASS,
            evidence=[Evidence(
                rule_id="no_skipped_errors",
                description="No tool errors found in results",
            )],
        )

    # Check if errors were followed by retry/fix attempts
    # Simple heuristic: count tool calls after the last error
    last_error_idx = -1
    for i, tr in enumerate(tool_results):
        if tr.status == "error" or (tr.error and tr.error.strip()):
            last_error_idx = i

    calls_after_error = len(tool_results) - 1 - last_error_idx if last_error_idx >= 0 else 0

    issues = []
    evidence = [Evidence(
        rule_id="no_skipped_errors",
        description=f"Found {len(error_results)} error(s) in tool results",
        data={
            "error_count": len(error_results),
            "error_tools": [tr.tool_name for tr in error_results],
            "calls_after_last_error": calls_after_error,
        },
    )]

    if calls_after_error == 0 and len(error_results) > 0:
        # Last result was an error — suspicious
        issues.append(Issue(
            rule_id="no_skipped_errors",
            severity="warning",
            message=(
                f"The last tool result was an error ({error_results[-1].tool_name}). "
                "No subsequent fix attempt was observed."
            ),
            suggestion="Investigate the error and retry or explain why it's acceptable",
        ))
        return RuleResult(
            rule_id="no_skipped_errors",
            status=VerificationStatus.PARTIAL,
            evidence=evidence,
            issues=issues,
        )

    if calls_after_error < len(error_results):
        issues.append(Issue(
            rule_id="no_skipped_errors",
            severity="warning",
            message=(
                f"{len(error_results)} error(s) occurred, but only "
                f"{calls_after_error} tool call(s) followed the last error"
            ),
            suggestion="Ensure each error was addressed before claiming success",
        ))
        return RuleResult(
            rule_id="no_skipped_errors",
            status=VerificationStatus.PARTIAL,
            evidence=evidence,
            issues=issues,
        )

    return RuleResult(
        rule_id="no_skipped_errors",
        status=VerificationStatus.PASS,
        evidence=evidence,
    )


# --- Rule: claimed_vs_actual ---


def _check_claimed_vs_actual(
    tool_calls: list[ToolCall],
    tool_results: list[ToolResult],
    claimed_result: str,
    context: dict[str, Any],
) -> RuleResult:
    """Compare the agent's claimed result against actual tool outputs.

    Looks for contradictions: agent claims success but outputs contain
    errors, or agent claims a specific count but output shows different.
    """
    if not claimed_result.strip():
        return RuleResult(
            rule_id="claimed_vs_actual",
            status=VerificationStatus.SKIPPED,
            evidence=[Evidence(
                rule_id="claimed_vs_actual",
                description="No claimed result provided",
            )],
        )

    outputs = _extract_outputs(tool_results)
    all_output = "\n".join(outputs)

    issues = []
    evidence = []

    # Check: does the agent claim success while outputs contain errors?
    claims_success = any(pat.search(claimed_result) for pat in _SUCCESS_PATTERNS)
    claims_test_pass = any(pat.search(claimed_result) for pat in _TEST_CLAIM_PATTERNS)
    output_has_errors = any(pat.search(all_output) for pat in _ERROR_PATTERNS)
    output_has_success = any(pat.search(all_output) for pat in _SUCCESS_PATTERNS)

    if (claims_success or claims_test_pass) and output_has_errors and not output_has_success:
        issues.append(Issue(
            rule_id="claimed_vs_actual",
            severity="error",
            message="Agent claims success, but tool outputs contain error indicators",
            suggestion="Review the actual tool outputs — the claimed result may be inaccurate",
        ))

    # Check: any tool results with status "error" or "blocked"?
    failed_tools = [
        tr.tool_name for tr in tool_results
        if tr.status in ("error", "blocked")
    ]
    if failed_tools and (claims_success or claims_test_pass):
        issues.append(Issue(
            rule_id="claimed_vs_actual",
            severity="warning",
            message=(
                f"Agent claims success, but {len(failed_tools)} tool(s) "
                f"had error/blocked status: {', '.join(set(failed_tools))}"
            ),
            suggestion="Verify that the failed tools are not relevant to the claim",
        ))

    evidence.append(Evidence(
        rule_id="claimed_vs_actual",
        description="Compared claimed result against tool outputs",
        data={
            "claims_success": claims_success or claims_test_pass,
            "output_has_errors": output_has_errors,
            "output_has_success": output_has_success,
            "failed_tools": failed_tools,
        },
    ))

    if any(i.severity == "error" for i in issues):
        status = VerificationStatus.FAIL
    elif issues:
        status = VerificationStatus.PARTIAL
    else:
        status = VerificationStatus.PASS

    return RuleResult(
        rule_id="claimed_vs_actual",
        status=status,
        evidence=evidence,
        issues=issues,
    )


# --- Rule: files_actually_tested ---


def _check_files_actually_tested(
    tool_calls: list[ToolCall],
    tool_results: list[ToolResult],
    claimed_result: str,
    context: dict[str, Any],
) -> RuleResult:
    """Cross-reference modified files with test execution.

    If files were modified, check whether tests were run afterward.
    This catches the "edit and forget to test" anti-pattern.
    """
    modified_files = _extract_modified_files(tool_calls)
    if not modified_files:
        return RuleResult(
            rule_id="files_actually_tested",
            status=VerificationStatus.SKIPPED,
            evidence=[Evidence(
                rule_id="files_actually_tested",
                description="No files were modified",
            )],
        )

    commands = _extract_commands(tool_calls)

    # Find the index of the last file modification
    write_tools = {"write", "Write", "edit", "Edit", "file_write", "file_edit"}
    last_write_idx = -1
    for i, tc in enumerate(tool_calls):
        if tc.tool_name in write_tools:
            last_write_idx = i

    # Find if any test command appears after the last write
    bash_tools = {"bash", "Bash", "shell", "terminal", "execute", "run"}
    test_after_write = False
    for i, tc in enumerate(tool_calls):
        if i > last_write_idx and tc.tool_name in bash_tools:
            cmd = tc.tool_input.get("command", "")
            if isinstance(cmd, str):
                for pattern in _TEST_COMMAND_PATTERNS:
                    if pattern.search(cmd):
                        test_after_write = True
                        break

    evidence = [Evidence(
        rule_id="files_actually_tested",
        description=f"Modified {len(modified_files)} file(s)",
        data={
            "modified_files": sorted(modified_files),
            "test_after_write": test_after_write,
        },
    )]

    if test_after_write:
        return RuleResult(
            rule_id="files_actually_tested",
            status=VerificationStatus.PASS,
            evidence=evidence,
        )
    else:
        # Check if any test was run at all
        any_tests = any(
            any(pat.search(cmd) for pat in _TEST_COMMAND_PATTERNS)
            for cmd in commands
        )

        if any_tests:
            return RuleResult(
                rule_id="files_actually_tested",
                status=VerificationStatus.PARTIAL,
                evidence=evidence,
                issues=[Issue(
                    rule_id="files_actually_tested",
                    severity="warning",
                    message=(
                        "Tests were run, but before the last file modification. "
                        "Changes made after testing may not have been verified."
                    ),
                    suggestion="Re-run tests after the final set of edits",
                )],
            )
        else:
            return RuleResult(
                rule_id="files_actually_tested",
                status=VerificationStatus.FAIL,
                evidence=evidence,
                issues=[Issue(
                    rule_id="files_actually_tested",
                    severity="warning",
                    message=(
                        f"{len(modified_files)} file(s) were modified but "
                        "no test command was found in the tool call history"
                    ),
                    suggestion="Run tests to verify that modified files work correctly",
                )],
            )


def _files_tested_applicable(
    tool_calls: list[ToolCall],
    claimed_result: str,
    context: dict[str, Any],
) -> bool:
    """This rule applies when files were modified."""
    write_tools = {"write", "Write", "edit", "Edit", "file_write", "file_edit"}
    return any(tc.tool_name in write_tools for tc in tool_calls)


# ---------------------------------------------------------------------------
# Built-in rule registry
# ---------------------------------------------------------------------------


BUILTIN_RULES: list[VerificationRule] = [
    VerificationRule(
        id="tests_actually_ran",
        description=(
            "Verify that test commands were actually executed"
            " when tests are claimed to pass"
        ),
        check=_check_tests_actually_ran,
        severity="error",
        applicable_when=_tests_applicable,
    ),
    VerificationRule(
        id="lint_passed",
        description=(
            "Verify that lint commands were actually executed"
            " when linting is claimed to pass"
        ),
        check=_check_lint_passed,
        severity="error",
        applicable_when=_lint_applicable,
    ),
    VerificationRule(
        id="no_skipped_errors",
        description="Check that tool errors were not silently ignored",
        check=_check_no_skipped_errors,
        severity="warning",
        applicable_when=None,  # Always applicable
    ),
    VerificationRule(
        id="claimed_vs_actual",
        description="Compare the agent's claimed result against actual tool outputs",
        check=_check_claimed_vs_actual,
        severity="error",
        applicable_when=None,  # Always applicable
    ),
    VerificationRule(
        id="files_actually_tested",
        description="Cross-reference modified files with test execution",
        check=_check_files_actually_tested,
        severity="warning",
        applicable_when=_files_tested_applicable,
    ),
]


# ---------------------------------------------------------------------------
# Verification Engine
# ---------------------------------------------------------------------------


class VerificationEngine:
    """Adversarial verification of agent actions.

    Runs a set of verification rules against a sequence of tool calls and
    their results, producing a ``VerificationResult`` that indicates whether
    the agent's claimed work was actually performed.

    This is a pure rule-based engine (no LLM calls). It examines tool call
    history, tool outputs, and the claimed result to detect discrepancies.

    Parameters
    ----------
    rules : list[VerificationRule] | None
        Custom verification rules. If None, uses built-in rules.
    strict : bool
        If True, treat all issues as errors (even warnings). Default False.
    require_all_rules : bool
        If True, non-applicable rules count as FAIL instead of SKIPPED.
        Default False.

    Usage::

        verifier = VerificationEngine()

        verdict = verifier.verify(
            tool_calls=[...],
            tool_results=[...],
            claimed_result="All tests pass and linting is clean",
        )

        if not verdict.passed:
            for issue in verdict.issues:
                print(f"[{issue.severity}] {issue.message}")
    """

    def __init__(
        self,
        rules: list[VerificationRule] | None = None,
        *,
        strict: bool = False,
        require_all_rules: bool = False,
    ) -> None:
        # Accept Constitution as first arg (common pattern) — just use defaults
        if rules is not None and not isinstance(rules, list):
            rules = None
        self._rules = list(rules) if rules is not None else list(BUILTIN_RULES)
        self._strict = strict
        self._require_all = require_all_rules

    def verify(
        self,
        tool_calls: list[ToolCall],
        claimed_result: str = "",
        tool_results: list[ToolResult] | None = None,
        context: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Run all applicable verification rules and produce a verdict.

        Parameters
        ----------
        tool_calls : list[ToolCall]
            The sequence of tool calls to verify.
        claimed_result : str
            What the agent claims it accomplished.
        tool_results : list[ToolResult] | None
            Corresponding tool results. If None, an empty list is used.
        context : dict | None
            Additional context (project_dir, session_id, etc.).

        Returns
        -------
        VerificationResult
            The aggregate verification verdict.
        """
        results_list = tool_results or []
        ctx = context or {}

        rule_results: list[RuleResult] = []
        all_evidence: list[Evidence] = []
        all_issues: list[Issue] = []

        for rule in self._rules:
            try:
                # Check applicability
                if (
                    rule.applicable_when is not None
                    and not rule.applicable_when(tool_calls, claimed_result, ctx)
                ):
                        if self._require_all:
                            rr = RuleResult(
                                rule_id=rule.id,
                                status=VerificationStatus.FAIL,
                                issues=[Issue(
                                    rule_id=rule.id,
                                    severity="error",
                                    message=f"Required rule '{rule.id}' was not applicable",
                                )],
                            )
                        else:
                            rr = RuleResult(
                                rule_id=rule.id,
                                status=VerificationStatus.SKIPPED,
                            )
                        rule_results.append(rr)
                        all_issues.extend(rr.issues)
                        continue

                # Run the check
                rr = rule.check(tool_calls, results_list, claimed_result, ctx)
                rule_results.append(rr)
                all_evidence.extend(rr.evidence)
                all_issues.extend(rr.issues)

                logger.debug(
                    "Rule '%s': %s (%d evidence, %d issues)",
                    rule.id,
                    rr.status.value,
                    len(rr.evidence),
                    len(rr.issues),
                )

            except Exception as e:
                logger.exception("Verification rule '%s' raised an exception", rule.id)
                rr = RuleResult(
                    rule_id=rule.id,
                    status=VerificationStatus.FAIL,
                    issues=[Issue(
                        rule_id=rule.id,
                        severity="error",
                        message=f"Rule '{rule.id}' raised an exception: {e}",
                    )],
                )
                rule_results.append(rr)
                all_issues.extend(rr.issues)

        # Compute aggregate status
        status = self._compute_aggregate_status(rule_results, all_issues)
        confidence = self._compute_confidence(rule_results)
        summary = self._build_summary(status, rule_results, all_issues)

        return VerificationResult(
            status=status,
            evidence=all_evidence,
            issues=all_issues,
            rule_results=rule_results,
            confidence=confidence,
            summary=summary,
        )

    def add_rule(self, rule: VerificationRule) -> None:
        """Add a custom verification rule.

        Parameters
        ----------
        rule : VerificationRule
            The rule to add. Its ``id`` should be unique.
        """
        # Check for duplicate IDs
        existing_ids = {r.id for r in self._rules}
        if rule.id in existing_ids:
            logger.warning(
                "Replacing existing verification rule '%s'", rule.id
            )
            self._rules = [r for r in self._rules if r.id != rule.id]
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a verification rule by ID.

        Returns True if the rule was found and removed, False otherwise.
        """
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        return len(self._rules) < before

    @property
    def rules(self) -> list[VerificationRule]:
        """Return the current list of verification rules (copy)."""
        return list(self._rules)

    def _compute_aggregate_status(
        self,
        rule_results: list[RuleResult],
        issues: list[Issue],
    ) -> VerificationStatus:
        """Determine overall status from individual rule results."""
        if not rule_results:
            return VerificationStatus.PASS

        statuses = [rr.status for rr in rule_results]

        # Any FAIL -> overall FAIL
        if VerificationStatus.FAIL in statuses:
            return VerificationStatus.FAIL

        # In strict mode, any warning-severity issue is treated as failure
        if self._strict and any(i.severity == "warning" for i in issues):
            return VerificationStatus.FAIL

        # Any PARTIAL -> overall PARTIAL
        if VerificationStatus.PARTIAL in statuses:
            return VerificationStatus.PARTIAL

        # All PASS or SKIPPED
        if all(s in (VerificationStatus.PASS, VerificationStatus.SKIPPED) for s in statuses):
            # If everything was skipped, that's suspicious
            if all(s == VerificationStatus.SKIPPED for s in statuses):
                return VerificationStatus.PARTIAL
            return VerificationStatus.PASS

        return VerificationStatus.PARTIAL

    def _compute_confidence(self, rule_results: list[RuleResult]) -> float:
        """Compute confidence score based on rule coverage.

        Higher confidence when more rules are applicable and produce evidence.
        """
        if not rule_results:
            return 0.5  # No rules ran — uncertain

        total = len(rule_results)
        ran = sum(1 for rr in rule_results if rr.status != VerificationStatus.SKIPPED)
        with_evidence = sum(1 for rr in rule_results if rr.evidence)

        if total == 0:
            return 0.5

        # Blend of coverage (how many rules ran) and evidence depth
        coverage = ran / total
        evidence_depth = with_evidence / total

        return round(0.6 * coverage + 0.4 * evidence_depth, 2)

    def _build_summary(
        self,
        status: VerificationStatus,
        rule_results: list[RuleResult],
        issues: list[Issue],
    ) -> str:
        """Build a one-line summary of the verification result."""
        total = len(rule_results)
        passed = sum(1 for rr in rule_results if rr.status == VerificationStatus.PASS)
        failed = sum(1 for rr in rule_results if rr.status == VerificationStatus.FAIL)
        partial = sum(1 for rr in rule_results if rr.status == VerificationStatus.PARTIAL)
        skipped = sum(1 for rr in rule_results if rr.status == VerificationStatus.SKIPPED)

        error_count = sum(1 for i in issues if i.severity == "error")
        warning_count = sum(1 for i in issues if i.severity == "warning")

        parts = [f"Verification {status.value}:"]
        parts.append(f"{passed}/{total} rules passed")

        if failed:
            parts.append(f"{failed} failed")
        if partial:
            parts.append(f"{partial} partial")
        if skipped:
            parts.append(f"{skipped} skipped")
        if error_count:
            parts.append(f"{error_count} error(s)")
        if warning_count:
            parts.append(f"{warning_count} warning(s)")

        return ", ".join(parts)

    def __repr__(self) -> str:
        return f"<VerificationEngine rules={len(self._rules)} strict={self._strict}>"
