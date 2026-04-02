"""Tool Governance Pipeline — the process every tool call passes through.

This is the central orchestration layer. It wires together:
  TurnGovernor -> RiskClassifier -> HookRegistry -> PermissionEngine
  -> SessionTrustState -> AuditEngine

Supports three operating modes:

  Core (6-step):
    1. Parse/Validate  2. Risk Classify  3. Permission Check
    4. Execute         5. Output Sanitize 6. Audit

  Standard (8-step):
    1. Parse/Validate  2. Interface Check  3. Risk Classify
    4. Pre-hooks       5. Permission Check  6. Execute
    7. Post-hooks/Sanitize  8. Audit + Trace

  Enhanced (14-step, default):
    1.  Turn governor check    2.  Parse/validate
    3.  Tool alias resolution  4.  Abort check
    5.  Risk classification    6.  PreToolUse hooks
    7.  Hook denial            8.  Apply hook modifications
    9.  Permission decision    10. Handle ask (progressive trust)
    11. Execute tool           12. PostToolUse hooks
    13. PostToolUseFailure     14. Audit
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from autoharness.core.audit import AuditEngine
from autoharness.core.hooks import HookRegistry
from autoharness.core.permissions import PermissionEngine
from autoharness.core.risk import RiskClassifier
from autoharness.core.trust import SessionTrustState
from autoharness.core.turn_governor import TurnGovernor
from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDecision,
    PermissionDefaults,
    PipelineMode,
    RiskAssessment,
    ToolCall,
    ToolResult,
)

# ---------------------------------------------------------------------------
# Ask confirmation callback protocol
# ---------------------------------------------------------------------------

class AskConfirmationHandler(Protocol):
    """Protocol for handling 'ask' permission decisions.

    Implementations receive the tool call and the ask decision,
    and return True to approve or False to deny.
    """

    def __call__(
        self, tool_call: ToolCall, decision: PermissionDecision
    ) -> bool: ...

logger = logging.getLogger(__name__)


class ToolGovernancePipeline:
    """Governance pipeline for AI agent tool calls.

    Supports three operating modes controlled by the constitution's ``mode`` field:

    - **core** (6-step): Parse/Validate, Risk Classify, Permission Check,
      Execute, Output Sanitize, Audit.
    - **standard** (8-step): Adds interface validation, pre/post hooks, and
      trace-based auditing on top of core.
    - **enhanced** (14-step, default): Full pipeline with turn governor,
      alias resolution, abort check, hook modifications, progressive trust,
      failure hooks, and all advanced features.

    Usage::

        from autoharness.core.constitution import Constitution
        from autoharness.core.pipeline import ToolGovernancePipeline

        constitution = Constitution.default()
        pipeline = ToolGovernancePipeline(constitution)

        result = pipeline.process(tool_call)
    """

    def __init__(
        self,
        constitution: Any = None,
        *,
        project_dir: str | None = None,
        session_id: str | None = None,
        mode: PipelineMode | str | None = None,
        hook_registry: Any | None = None,
    ) -> None:
        self._session_id = session_id or str(uuid.uuid4())[:12]
        self._project_dir = project_dir or str(Path.cwd())
        self._tool_executor: Callable[[ToolCall], Any] | None = None
        self._async_tool_executor: Callable[..., Any] | None = None
        self._on_blocked: Callable[[ToolCall, PermissionDecision], None] | None = None
        self._on_ask: AskConfirmationHandler | None = None
        self._ask_default: str = "deny"  # "deny" | "allow" — fallback when no handler
        self._trust_state = SessionTrustState()
        self._turn_governor = TurnGovernor()
        self._aborted: bool = False
        self._tool_aliases: dict[str, str] = {}  # alias -> canonical name

        # Extract configuration from constitution
        config = self._extract_config(constitution)

        # Determine pipeline mode: explicit arg > constitution config > enhanced
        if mode is not None:
            self._mode = PipelineMode(mode)
        else:
            raw_mode = config.get("mode", "enhanced")
            self._mode = PipelineMode(raw_mode) if isinstance(raw_mode, str) else raw_mode

        # Initialize sub-engines
        self._risk_classifier = RiskClassifier(
            custom_rules=self._get_custom_rules(config),
            mode=self._get_risk_mode(config),
        )

        tools_permissions = self._get_tool_permissions(config)
        defaults = self._get_permission_defaults(config)
        self._permission_engine = PermissionEngine(defaults=defaults, tools=tools_permissions)

        # Hooks: use externally provided registry, or build one based on mode
        if hook_registry is not None:
            self._hook_registry = hook_registry
        elif self._mode in (PipelineMode.standard, PipelineMode.enhanced):
            hook_profile = self._get_hook_profile(config)
            self._hook_registry = HookRegistry(profile=hook_profile)
        else:
            # Core mode: minimal hook registry (no hooks active)
            self._hook_registry = HookRegistry(profile="minimal")

        self._risk_thresholds = self._get_risk_thresholds(config)

        audit_config = self._get_audit_config(config)
        self._audit_engine = AuditEngine(
            output_path=audit_config.get("output", ".autoharness/audit.jsonl"),
            enabled=audit_config.get("enabled", True),
            retention_days=audit_config.get("retention_days", 30),
        )

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    @property
    def mode(self) -> PipelineMode:
        """The current pipeline operating mode."""
        return self._mode

    def process(self, tool_call: ToolCall) -> ToolResult:
        """Run the governance pipeline.

        The number of steps depends on the pipeline mode:
        - core: 6 steps
        - standard: 8 steps
        - enhanced: 14 steps

        Parameters
        ----------
        tool_call : ToolCall
            The tool call to govern.

        Returns
        -------
        ToolResult
            Result with status = "success", "blocked", or "error".
        """
        if self._mode == PipelineMode.core:
            return self._process_core(tool_call)
        if self._mode == PipelineMode.standard:
            return self._process_standard(tool_call)
        return self._process_enhanced(tool_call)

    def _process_core(self, tool_call: ToolCall) -> ToolResult:
        """Core mode: 6-step pipeline.

        1. Parse/Validate  2. Risk Classify  3. Permission Check
        4. Execute         5. Output Sanitize 6. Audit
        """
        start_time = time.monotonic()

        try:
            # Step 1: Parse/validate
            self._validate_tool_call(tool_call)

            # Step 2: Risk classification
            risk = self._risk_classifier.classify(tool_call)
            logger.debug("Risk: %s for %s", risk.level.value, tool_call.tool_name)

            # Step 3: Permission check
            decision = self._make_permission_decision(tool_call, risk, [])

            if decision.action == "deny":
                return self._handle_block(tool_call, risk, [], decision, start_time)

            if decision.action == "ask":
                resolved = self._handle_ask(tool_call, decision)
                if resolved.action == "deny":
                    return self._handle_block(tool_call, risk, [], resolved, start_time)
                decision = resolved

            # Step 4: Execute
            exec_result = self._execute(tool_call, start_time)

            # Step 5: Output sanitize (basic — run post hooks for sanitization only)
            final_result, post_hook_results = self._hook_registry.run_post_hooks(
                tool_call, exec_result,
                {"session_id": self._session_id, "project_dir": self._project_dir},
            )

            # Step 6: Audit
            self._audit_engine.log(
                tool_call=tool_call,
                risk=risk,
                pre_hooks=[],
                permission=decision,
                result=final_result,
                post_hooks=post_hook_results,
                session_id=self._session_id,
            )

            return final_result

        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            logger.exception("Pipeline error for %s", tool_call.tool_name)
            error_result = ToolResult(
                tool_name=tool_call.tool_name,
                status="error",
                error=str(e),
                duration_ms=duration,
            )
            with contextlib.suppress(Exception):
                self._audit_engine.log_error(tool_call, e, self._session_id)
            return error_result

    def _process_standard(self, tool_call: ToolCall) -> ToolResult:
        """Standard mode: 8-step pipeline.

        1. Parse/Validate  2. Interface Check  3. Risk Classify
        4. Pre-hooks       5. Permission Check  6. Execute
        7. Post-hooks/Sanitize  8. Audit + Trace
        """
        start_time = time.monotonic()
        context = {
            "session_id": self._session_id,
            "project_dir": self._project_dir,
        }

        try:
            # Step 1: Parse/validate
            self._validate_tool_call(tool_call)

            # Step 2: Interface check (validate tool call structure is well-formed)
            # This is a Meta-Harness-inspired validation gate
            self._interface_check(tool_call)

            # Step 3: Risk classification
            risk = self._risk_classifier.classify(tool_call)
            logger.debug("Risk: %s for %s", risk.level.value, tool_call.tool_name)

            # Step 4: Pre-hooks
            pre_hook_results = self._hook_registry.run_pre_hooks(tool_call, risk, context)

            hook_denial = self._find_hook_denial(pre_hook_results)
            if hook_denial:
                decision = PermissionDecision(
                    action="deny",
                    reason=hook_denial.reason or "Blocked by pre-hook",
                    source="hook",
                    risk_level=risk.level,
                )
                return self._handle_block(
                    tool_call, risk, pre_hook_results, decision, start_time,
                )

            # Step 5: Permission check
            decision = self._make_permission_decision(tool_call, risk, pre_hook_results)

            if decision.action == "deny":
                return self._handle_block(tool_call, risk, pre_hook_results, decision, start_time)

            if decision.action == "ask":
                resolved = self._handle_ask(tool_call, decision)
                if resolved.action == "deny":
                    return self._handle_block(
                        tool_call, risk, pre_hook_results, resolved, start_time,
                    )
                decision = resolved

            # Step 6: Execute
            exec_result = self._execute(tool_call, start_time)

            # Step 7: Post-hooks + sanitize
            final_result, post_hook_results = self._hook_registry.run_post_hooks(
                tool_call, exec_result, context
            )

            # Step 8: Audit + trace
            self._audit_engine.log(
                tool_call=tool_call,
                risk=risk,
                pre_hooks=pre_hook_results,
                permission=decision,
                result=final_result,
                post_hooks=post_hook_results,
                session_id=self._session_id,
            )

            return final_result

        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            logger.exception("Pipeline error for %s", tool_call.tool_name)
            error_result = ToolResult(
                tool_name=tool_call.tool_name,
                status="error",
                error=str(e),
                duration_ms=duration,
            )
            with contextlib.suppress(Exception):
                self._audit_engine.log_error(tool_call, e, self._session_id)
            return error_result

    def _process_enhanced(self, tool_call: ToolCall) -> ToolResult:
        """Enhanced mode: full 14-step governance pipeline."""
        start_time = time.monotonic()
        context = {
            "session_id": self._session_id,
            "project_dir": self._project_dir,
        }

        try:
            # Step 1: Turn governor check
            turn_denial = self._turn_governor.check_turn_limits(tool_call)
            if turn_denial:
                risk = self._risk_classifier.classify(tool_call)
                self._turn_governor.record_result(turn_denial, risk.level)
                return self._handle_block(
                    tool_call, risk, [], turn_denial, start_time
                )

            # Step 2: Parse/validate tool call structure
            self._validate_tool_call(tool_call)

            # Step 3: Tool alias resolution
            tool_call = self._resolve_tool_alias(tool_call)

            # Step 4: Abort check
            if self._aborted:
                duration = (time.monotonic() - start_time) * 1000
                return ToolResult(
                    tool_name=tool_call.tool_name,
                    status="blocked",
                    blocked_reason="Pipeline aborted",
                    duration_ms=duration,
                )

            # Step 5: Risk classification
            risk = self._risk_classifier.classify(tool_call)
            logger.debug("Risk: %s for %s", risk.level.value, tool_call.tool_name)

            # Step 6: PreToolUse Hooks
            pre_hook_results = self._hook_registry.run_pre_hooks(tool_call, risk, context)

            # Step 7: Hook denial short-circuit
            hook_denial = self._find_hook_denial(pre_hook_results)
            if hook_denial:
                decision = PermissionDecision(
                    action="deny",
                    reason=hook_denial.reason or "Blocked by pre-hook",
                    source="hook",
                    risk_level=risk.level,
                )
                self._turn_governor.record_result(decision, risk.level)
                return self._handle_block(
                    tool_call, risk, pre_hook_results, decision, start_time,
                )

            # Step 8: Apply hook modifications
            modified_tc = self._apply_hook_modifications(tool_call, pre_hook_results)
            if modified_tc is not tool_call:
                logger.info("Tool input modified by hook: %s", tool_call.tool_name)
                tool_call = modified_tc

            # Step 9: Permission Decision (merge risk thresholds + hooks + constitution rules)
            decision = self._make_permission_decision(tool_call, risk, pre_hook_results)

            if decision.action == "deny":
                self._turn_governor.record_result(decision, risk.level)
                return self._handle_block(tool_call, risk, pre_hook_results, decision, start_time)

            # Step 10: Handle ask (with progressive trust)
            if decision.action == "ask":
                resolved = self._handle_ask(tool_call, decision)
                if resolved.action == "deny":
                    self._turn_governor.record_result(resolved, risk.level)
                    return self._handle_block(
                        tool_call, risk, pre_hook_results,
                        resolved, start_time,
                    )
                # User approved — fall through to execution
                decision = resolved

            # Step 11: Execute tool
            exec_result = self._execute(tool_call, start_time)

            # Step 12: PostToolUse Hooks
            final_result, post_hook_results = self._hook_registry.run_post_hooks(
                tool_call, exec_result, context
            )

            # Step 13: PostToolUseFailure Hooks (if execution errored)
            failure_hook_results: list[HookResult] = []
            if final_result.status == "error":
                failure_hook_results = self._run_failure_hooks(
                    tool_call, final_result, context
                )

            # Record turn-level result
            self._turn_governor.record_result(decision, risk.level)

            # Step 14: Audit
            self._audit_engine.log(
                tool_call=tool_call,
                risk=risk,
                pre_hooks=pre_hook_results,
                permission=decision,
                result=final_result,
                post_hooks=post_hook_results + failure_hook_results,
                session_id=self._session_id,
            )

            return final_result

        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            logger.exception("Pipeline error for %s", tool_call.tool_name)
            error_result = ToolResult(
                tool_name=tool_call.tool_name,
                status="error",
                error=str(e),
                duration_ms=duration,
            )
            with contextlib.suppress(Exception):
                self._audit_engine.log_error(tool_call, e, self._session_id)
            return error_result

    def evaluate(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        """Pre-execution governance check only (no execution, no post-hooks).

        Useful for checking if a tool call would be allowed without actually running it.
        """
        ctx = context or {"session_id": self._session_id, "project_dir": self._project_dir}

        risk = self._risk_classifier.classify(tool_call)
        pre_hook_results = self._hook_registry.run_pre_hooks(tool_call, risk, ctx)

        hook_denial = self._find_hook_denial(pre_hook_results)
        if hook_denial:
            return PermissionDecision(
                action="deny",
                reason=hook_denial.reason or "Blocked by pre-hook",
                source="hook",
                risk_level=risk.level,
            )

        # Check for input modifications from hooks
        modified_tc = self._apply_hook_modifications(tool_call, pre_hook_results)
        if modified_tc is not tool_call:
            logger.info("Tool input modified by hook (evaluate): %s", tool_call.tool_name)
            tool_call = modified_tc

        return self._make_permission_decision(tool_call, risk, pre_hook_results)

    def process_batch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Process multiple tool calls sequentially."""
        return [self.process(tc) for tc in tool_calls]

    async def aprocess(self, tool_call: ToolCall) -> ToolResult:
        """Async version of :meth:`process`.

        The governance checks themselves are synchronous (fast <5ms),
        but this allows the tool executor to be async. Falls back to
        the sync ``_execute`` path when no async executor is configured.

        Respects the same pipeline mode as :meth:`process`.
        """
        # For core/standard modes, governance is sync; only execution is async
        if self._mode == PipelineMode.core:
            return await self._aprocess_core(tool_call)
        if self._mode == PipelineMode.standard:
            return await self._aprocess_standard(tool_call)
        return await self._aprocess_enhanced(tool_call)

    async def _aprocess_core(self, tool_call: ToolCall) -> ToolResult:
        """Async core mode: 6-step pipeline with async execution."""
        start_time = time.monotonic()
        try:
            self._validate_tool_call(tool_call)
            risk = self._risk_classifier.classify(tool_call)
            decision = self._make_permission_decision(tool_call, risk, [])

            if decision.action == "deny":
                return self._handle_block(tool_call, risk, [], decision, start_time)
            if decision.action == "ask":
                resolved = self._handle_ask(tool_call, decision)
                if resolved.action == "deny":
                    return self._handle_block(tool_call, risk, [], resolved, start_time)
                decision = resolved

            exec_result = await self._aexecute(tool_call, start_time)
            final_result, post_hook_results = self._hook_registry.run_post_hooks(
                tool_call, exec_result,
                {"session_id": self._session_id, "project_dir": self._project_dir},
            )
            self._audit_engine.log(
                tool_call=tool_call, risk=risk, pre_hooks=[], permission=decision,
                result=final_result, post_hooks=post_hook_results,
                session_id=self._session_id,
            )
            return final_result
        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            logger.exception("Pipeline error for %s", tool_call.tool_name)
            error_result = ToolResult(
                tool_name=tool_call.tool_name, status="error",
                error=str(e), duration_ms=duration,
            )
            with contextlib.suppress(Exception):
                self._audit_engine.log_error(tool_call, e, self._session_id)
            return error_result

    async def _aprocess_standard(self, tool_call: ToolCall) -> ToolResult:
        """Async standard mode: 8-step pipeline with async execution."""
        start_time = time.monotonic()
        context = {"session_id": self._session_id, "project_dir": self._project_dir}
        try:
            self._validate_tool_call(tool_call)
            self._interface_check(tool_call)
            risk = self._risk_classifier.classify(tool_call)
            pre_hook_results = self._hook_registry.run_pre_hooks(tool_call, risk, context)

            hook_denial = self._find_hook_denial(pre_hook_results)
            if hook_denial:
                decision = PermissionDecision(
                    action="deny", reason=hook_denial.reason or "Blocked by pre-hook",
                    source="hook", risk_level=risk.level,
                )
                return self._handle_block(
                    tool_call, risk, pre_hook_results, decision, start_time,
                )

            decision = self._make_permission_decision(tool_call, risk, pre_hook_results)
            if decision.action == "deny":
                return self._handle_block(tool_call, risk, pre_hook_results, decision, start_time)
            if decision.action == "ask":
                resolved = self._handle_ask(tool_call, decision)
                if resolved.action == "deny":
                    return self._handle_block(
                        tool_call, risk, pre_hook_results, resolved, start_time,
                    )
                decision = resolved

            exec_result = await self._aexecute(tool_call, start_time)
            final_result, post_hook_results = self._hook_registry.run_post_hooks(
                tool_call, exec_result, context
            )
            self._audit_engine.log(
                tool_call=tool_call, risk=risk, pre_hooks=pre_hook_results,
                permission=decision, result=final_result, post_hooks=post_hook_results,
                session_id=self._session_id,
            )
            return final_result
        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            logger.exception("Pipeline error for %s", tool_call.tool_name)
            error_result = ToolResult(
                tool_name=tool_call.tool_name, status="error",
                error=str(e), duration_ms=duration,
            )
            with contextlib.suppress(Exception):
                self._audit_engine.log_error(tool_call, e, self._session_id)
            return error_result

    async def _aprocess_enhanced(self, tool_call: ToolCall) -> ToolResult:
        """Async enhanced mode: full 14-step pipeline with async execution."""
        start_time = time.monotonic()
        context = {
            "session_id": self._session_id,
            "project_dir": self._project_dir,
        }

        try:
            # Step 1: Parse/validate
            self._validate_tool_call(tool_call)

            # Step 1.5: Turn-level governance check
            turn_denial = self._turn_governor.check_turn_limits(tool_call)
            if turn_denial:
                risk = self._risk_classifier.classify(tool_call)
                self._turn_governor.record_result(turn_denial, risk.level)
                return self._handle_block(
                    tool_call, risk, [], turn_denial, start_time
                )

            # Step 2: Classify Risk
            risk = self._risk_classifier.classify(tool_call)
            logger.debug("Risk: %s for %s", risk.level.value, tool_call.tool_name)

            # Step 3: PreToolUse Hooks (sync)
            pre_hook_results = self._hook_registry.run_pre_hooks(tool_call, risk, context)

            # Step 4: Check for hook denials
            hook_denial = self._find_hook_denial(pre_hook_results)
            if hook_denial:
                decision = PermissionDecision(
                    action="deny",
                    reason=hook_denial.reason or "Blocked by pre-hook",
                    source="hook",
                    risk_level=risk.level,
                )
                self._turn_governor.record_result(decision, risk.level)
                return self._handle_block(
                    tool_call, risk, pre_hook_results, decision, start_time,
                )

            # Check for input modifications
            modified_tc = self._apply_hook_modifications(tool_call, pre_hook_results)
            if modified_tc is not tool_call:
                logger.info("Tool input modified by hook: %s", tool_call.tool_name)
                tool_call = modified_tc

            # Step 5: Permission Decision
            decision = self._make_permission_decision(tool_call, risk, pre_hook_results)

            if decision.action == "deny":
                self._turn_governor.record_result(decision, risk.level)
                return self._handle_block(tool_call, risk, pre_hook_results, decision, start_time)

            if decision.action == "ask":
                resolved = self._handle_ask(tool_call, decision)
                if resolved.action == "deny":
                    self._turn_governor.record_result(resolved, risk.level)
                    return self._handle_block(
                        tool_call, risk, pre_hook_results,
                        resolved, start_time,
                    )
                decision = resolved

            # Step 6: Execute (async)
            exec_result = await self._aexecute(tool_call, start_time)

            # Step 7: PostToolUse Hooks
            final_result, post_hook_results = self._hook_registry.run_post_hooks(
                tool_call, exec_result, context
            )

            # Step 7.5: PostToolUseFailure hooks
            if exec_result.status == "error" and exec_result.error:
                self._hook_registry.run_failure_hooks(
                    tool_call,
                    RuntimeError(exec_result.error),
                    context,
                )

            # Record turn-level result
            self._turn_governor.record_result(decision, risk.level)

            # Step 8: Audit
            self._audit_engine.log(
                tool_call=tool_call,
                risk=risk,
                pre_hooks=pre_hook_results,
                permission=decision,
                result=final_result,
                post_hooks=post_hook_results,
                session_id=self._session_id,
            )

            return final_result

        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            logger.exception("Pipeline error for %s", tool_call.tool_name)
            error_result = ToolResult(
                tool_name=tool_call.tool_name,
                status="error",
                error=str(e),
                duration_ms=duration,
            )
            with contextlib.suppress(Exception):
                self._audit_engine.log_error(tool_call, e, self._session_id)
            return error_result

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_tool_executor(self, executor: Callable[[ToolCall], Any]) -> None:
        """Set the callback that actually executes tools."""
        self._tool_executor = executor

    def set_async_tool_executor(self, executor: Callable[..., Any]) -> None:
        """Set an async callback that executes tools.

        The executor should be an async function (coroutine function)
        that accepts a :class:`ToolCall` and returns the tool output.
        When set, :meth:`aprocess` will ``await`` this executor instead
        of calling the sync executor.
        """
        self._async_tool_executor = executor

    def abort(self) -> None:
        """Abort the pipeline. All subsequent process() calls will return blocked.

        This is step 4 of the 14-step pipeline. Once called, every tool call
        is immediately short-circuited with a "Pipeline aborted" result.
        """
        self._aborted = True
        logger.info("Pipeline aborted for session %s", self._session_id)

    @property
    def aborted(self) -> bool:
        """Whether the pipeline has been aborted."""
        return self._aborted

    @property
    def tool_aliases(self) -> dict[str, str]:
        """Configurable tool alias map (alias -> canonical name).

        Set entries to map alternative tool names to their canonical form.
        For example: ``pipeline.tool_aliases["sh"] = "Bash"``
        """
        return self._tool_aliases

    @tool_aliases.setter
    def tool_aliases(self, aliases: dict[str, str]) -> None:
        self._tool_aliases = dict(aliases)

    def verify_session(self, claimed_result: str = "") -> Any:
        """Run the verification engine against this session's audit trail.

        Converts audit records into ToolCall/ToolResult pairs and passes
        them to the VerificationEngine for adversarial validation.

        Parameters
        ----------
        claimed_result : str
            What the agent claims it accomplished.

        Returns
        -------
        VerificationResult
            The aggregate verification verdict.
        """
        from autoharness.core.verification import VerificationEngine

        records = self._audit_engine.get_records(session_id=self._session_id)

        # Convert audit records to ToolCall/ToolResult pairs
        tool_calls: list[ToolCall] = []
        tool_results: list[ToolResult] = []
        for record in records:
            tc = ToolCall(
                tool_name=record.tool_name,
                tool_input={},  # Input is hashed in audit, not stored raw
                session_id=record.session_id,
            )
            tool_calls.append(tc)

            exec_data = record.execution
            status = exec_data.get("status", "success")
            # Map audit statuses to valid ToolResult statuses
            if status not in ("success", "blocked", "error"):
                status = "error" if status == "pending" else "success"
            tr = ToolResult(
                tool_name=record.tool_name,
                status=status,
                error=exec_data.get("error"),
                duration_ms=exec_data.get("duration_ms", 0),
            )
            tool_results.append(tr)

        verifier = VerificationEngine()
        return verifier.verify(
            tool_calls=tool_calls,
            claimed_result=claimed_result,
            tool_results=tool_results,
            context={"session_id": self._session_id, "project_dir": self._project_dir},
        )

    @property
    def on_blocked(self) -> Callable[[ToolCall, PermissionDecision], None] | None:
        return self._on_blocked

    @on_blocked.setter
    def on_blocked(self, callback: Callable[[ToolCall, PermissionDecision], None]) -> None:
        self._on_blocked = callback

    @property
    def on_ask(self) -> AskConfirmationHandler | None:
        """Callback invoked when the pipeline needs user confirmation.

        The callback receives (tool_call, decision) and returns True to
        approve or False to deny. When no callback is set, the pipeline
        falls back to ``ask_default`` (default: ``"deny"``).
        """
        return self._on_ask

    @on_ask.setter
    def on_ask(self, handler: AskConfirmationHandler | None) -> None:
        self._on_ask = handler

    @property
    def ask_default(self) -> str:
        """Default action when an 'ask' decision has no handler: ``"deny"`` or ``"allow"``."""
        return self._ask_default

    @ask_default.setter
    def ask_default(self, value: str) -> None:
        if value not in ("deny", "allow"):
            raise ValueError(f"ask_default must be 'deny' or 'allow', got {value!r}")
        self._ask_default = value

    def get_prompt_addendum(self) -> str:
        """Generate system prompt addendum from constitution rules."""
        from autoharness.compiler.prompt import PromptCompiler

        # Reconstruct constitution from our config (best effort)
        try:
            constitution = self._constitution
            compiler = PromptCompiler()
            return compiler.compile(constitution)
        except Exception:
            return ""

    def get_audit_summary(self) -> dict[str, Any]:
        """Get summary of audit records."""
        return self._audit_engine.get_summary(session_id=self._session_id)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> ToolGovernancePipeline:
        return self

    def __exit__(self, *args: Any) -> None:
        self._audit_engine.close()

    # ------------------------------------------------------------------
    # Sub-engine accessors
    # ------------------------------------------------------------------

    @property
    def risk_classifier(self) -> RiskClassifier:
        return self._risk_classifier

    @property
    def permission_engine(self) -> PermissionEngine:
        return self._permission_engine

    @property
    def hook_registry(self) -> HookRegistry:
        return self._hook_registry

    @property
    def audit_engine(self) -> AuditEngine:
        return self._audit_engine

    @property
    def trust_state(self) -> SessionTrustState:
        return self._trust_state

    @property
    def turn_governor(self) -> TurnGovernor:
        return self._turn_governor

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_ask(
        self, tool_call: ToolCall, decision: PermissionDecision
    ) -> PermissionDecision:
        """Resolve an 'ask' decision via the on_ask callback or ask_default.

        If the tool+reason combination has been previously approved in this
        session (progressive trust), the callback is skipped and the call is
        auto-approved.

        Returns an allow or deny PermissionDecision.
        """
        # Progressive trust: check if already approved in this session
        if self._trust_state.is_trusted(tool_call.tool_name, decision.reason):
            logger.info(
                "ASK auto-approved by session trust: tool=%s reason=%s",
                tool_call.tool_name,
                decision.reason,
            )
            return PermissionDecision(
                action="allow",
                reason=f"Auto-approved (session trust): {decision.reason}",
                source="trust",
                risk_level=decision.risk_level,
            )

        if self._on_ask is not None:
            try:
                approved = self._on_ask(tool_call, decision)
                if approved:
                    logger.info(
                        "ASK approved by callback: tool=%s reason=%s",
                        tool_call.tool_name,
                        decision.reason,
                    )
                    self._trust_state.record_approval(
                        tool_call.tool_name, decision.reason
                    )
                    return PermissionDecision(
                        action="allow",
                        reason=f"User approved: {decision.reason}",
                        source="ask_callback",
                        risk_level=decision.risk_level,
                    )
                else:
                    logger.info(
                        "ASK denied by callback: tool=%s reason=%s",
                        tool_call.tool_name,
                        decision.reason,
                    )
                    self._trust_state.record_denial(
                        tool_call.tool_name, decision.reason
                    )
                    return PermissionDecision(
                        action="deny",
                        reason=f"User denied: {decision.reason}",
                        source="ask_callback",
                        risk_level=decision.risk_level,
                    )
            except Exception as exc:
                logger.warning(
                    "on_ask callback error (falling back to ask_default=%s): %s",
                    self._ask_default,
                    exc,
                )

        # No callback or callback errored — use default
        fallback: Any = self._ask_default
        logger.info(
            "ASK resolved by default (%s): tool=%s reason=%s",
            fallback,
            tool_call.tool_name,
            decision.reason,
        )
        return PermissionDecision(
            action=fallback,
            reason=f"No confirmation handler (default={fallback}): {decision.reason}",
            source="ask_default",
            risk_level=decision.risk_level,
        )

    def _resolve_tool_alias(self, tool_call: ToolCall) -> ToolCall:
        """Step 3: Resolve tool name aliases to canonical names.

        If the tool_call's tool_name is in the alias map, create a new
        ToolCall with the canonical name. Otherwise return as-is.
        """
        canonical = self._tool_aliases.get(tool_call.tool_name)
        if canonical is None:
            return tool_call
        logger.debug(
            "Resolved tool alias: %s -> %s", tool_call.tool_name, canonical
        )
        return ToolCall(
            tool_name=canonical,
            tool_input=tool_call.tool_input,
            metadata={**tool_call.metadata, "_original_tool_name": tool_call.tool_name},
            session_id=tool_call.session_id,
            timestamp=tool_call.timestamp,
        )

    def _run_failure_hooks(
        self,
        tool_call: ToolCall,
        result: ToolResult,
        context: dict[str, Any],
    ) -> list[HookResult]:
        """Step 13: Run PostToolUseFailure hooks when execution errored.

        These hooks receive the failed tool call and its error result,
        allowing logging, alerting, or cleanup actions.
        """
        failure_hooks = self._hook_registry._lifecycle_hooks.get(
            "PostToolUseFailure", []
        )
        results: list[HookResult] = []
        for entry in failure_hooks:
            try:
                hr = entry.handler(tool_call, result, context)
                if isinstance(hr, HookResult):
                    results.append(hr)
            except Exception:
                logger.exception(
                    "PostToolUseFailure hook %s raised an exception",
                    entry.name,
                )
                results.append(
                    HookResult(
                        action=HookAction.allow,
                        reason=f"Failure hook {entry.name!r} raised an exception",
                        severity="warning",
                    )
                )
        return results

    def _validate_tool_call(self, tool_call: ToolCall) -> None:
        """Parse and validate tool call structure."""
        if not tool_call.tool_name:
            raise ValueError("tool_name is required")
        if not isinstance(tool_call.tool_input, dict):
            raise ValueError("tool_input must be a dict")

    def _interface_check(self, tool_call: ToolCall) -> None:
        """Standard mode step 2: validate tool call interface compliance.

        Inspired by Meta-Harness interface validation gate. Ensures the tool
        call conforms to expected schemas before proceeding.
        """
        # Validate tool_input keys are strings
        for key in tool_call.tool_input:
            if not isinstance(key, str):
                raise ValueError(
                    f"tool_input keys must be strings, got {type(key).__name__}"
                )

    def _find_hook_denial(self, hook_results: list[HookResult]) -> HookResult | None:
        """Find the first deny from hook results."""
        for hr in hook_results:
            if hr.action == HookAction.deny:
                return hr
        return None

    def _apply_hook_modifications(
        self, tool_call: ToolCall, hook_results: list[HookResult]
    ) -> ToolCall:
        """Apply input modifications from hooks that returned HookAction.modify."""
        for hr in hook_results:
            if hr.action == HookAction.modify and hr.modified_input:
                # Create new ToolCall with modified input (ToolCall is frozen)
                return ToolCall(
                    tool_name=tool_call.tool_name,
                    tool_input=hr.modified_input,
                    metadata={**tool_call.metadata, "_original_input": tool_call.tool_input},
                    session_id=tool_call.session_id,
                    timestamp=tool_call.timestamp,
                )
        return tool_call

    def _make_permission_decision(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        hook_results: list[HookResult],
    ) -> PermissionDecision:
        """Combine risk assessment, hooks, and permission rules into a decision."""
        # Check risk thresholds
        threshold_action = self._risk_thresholds.get(risk.level.value, "allow")
        if threshold_action == "deny":
            return PermissionDecision(
                action="deny",
                reason=f"Risk level '{risk.level.value}' exceeds threshold"
                + (f": {risk.reason}" if risk.reason else ""),
                source="risk_threshold",
                risk_level=risk.level,
            )
        if threshold_action == "ask":
            return PermissionDecision(
                action="ask",
                reason=f"Risk level '{risk.level.value}' requires confirmation"
                + (f": {risk.reason}" if risk.reason else ""),
                source="risk_threshold",
                risk_level=risk.level,
            )

        # Check hook asks
        for hr in hook_results:
            if hr.action == HookAction.ask:
                return PermissionDecision(
                    action="ask",
                    reason=hr.reason or "Hook requires confirmation",
                    source="hook",
                    risk_level=risk.level,
                )

        # Try permission engine — FAIL-CLOSED: errors result in deny, not allow
        try:
            perm_decision = self._permission_engine.decide(tool_call, risk, hook_results)
            return perm_decision
        except Exception as e:
            logger.error(
                "Permission engine error (DENYING for safety): tool=%s error=%s",
                tool_call.tool_name,
                e,
            )
            return PermissionDecision(
                action="deny",
                reason=f"Permission evaluation failed (fail-closed): {e}",
                source="pipeline_error",
                risk_level=risk.level,
            )

    def _execute(self, tool_call: ToolCall, start_time: float) -> ToolResult:
        """Step 6: Execute the tool via callback."""
        if self._tool_executor is None:
            duration = (time.monotonic() - start_time) * 1000
            return ToolResult(
                tool_name=tool_call.tool_name,
                status="success",
                output="[AutoHarness: tool execution passed governance — no executor set]",
                duration_ms=duration,
            )

        try:
            output = self._tool_executor(tool_call)
            duration = (time.monotonic() - start_time) * 1000
            return ToolResult(
                tool_name=tool_call.tool_name,
                status="success",
                output=output,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            return ToolResult(
                tool_name=tool_call.tool_name,
                status="error",
                error=str(e),
                duration_ms=duration,
            )

    async def _aexecute(self, tool_call: ToolCall, start_time: float) -> ToolResult:
        """Async variant of :meth:`_execute`.

        Prefers the async executor if set; falls back to the sync executor
        (run in the default thread pool to avoid blocking the event loop);
        falls back to a no-op success if neither is set.
        """
        if self._async_tool_executor is not None:
            try:
                output = await self._async_tool_executor(tool_call)
                duration = (time.monotonic() - start_time) * 1000
                return ToolResult(
                    tool_name=tool_call.tool_name,
                    status="success",
                    output=output,
                    duration_ms=duration,
                )
            except Exception as e:
                duration = (time.monotonic() - start_time) * 1000
                return ToolResult(
                    tool_name=tool_call.tool_name,
                    status="error",
                    error=str(e),
                    duration_ms=duration,
                )

        # Fall back to sync executor (wrapped in a thread to avoid blocking)
        if self._tool_executor is not None:
            loop = asyncio.get_event_loop()
            try:
                output = await loop.run_in_executor(
                    None, self._tool_executor, tool_call
                )
                duration = (time.monotonic() - start_time) * 1000
                return ToolResult(
                    tool_name=tool_call.tool_name,
                    status="success",
                    output=output,
                    duration_ms=duration,
                )
            except Exception as e:
                duration = (time.monotonic() - start_time) * 1000
                return ToolResult(
                    tool_name=tool_call.tool_name,
                    status="error",
                    error=str(e),
                    duration_ms=duration,
                )

        # No executor set
        duration = (time.monotonic() - start_time) * 1000
        return ToolResult(
            tool_name=tool_call.tool_name,
            status="success",
            output="[AutoHarness: tool execution passed governance — no executor set]",
            duration_ms=duration,
        )

    def _handle_block(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        hook_results: list[HookResult],
        decision: PermissionDecision,
        start_time: float,
    ) -> ToolResult:
        """Handle a blocked tool call — audit, notify, return blocked result."""
        duration = (time.monotonic() - start_time) * 1000

        # Run block hooks
        self._hook_registry.run_block_hooks(
            tool_call, decision, {"session_id": self._session_id}
        )

        # Notify callback
        if self._on_blocked:
            with contextlib.suppress(Exception):
                self._on_blocked(tool_call, decision)

        # Audit
        self._audit_engine.log_block(
            tool_call=tool_call,
            risk=risk,
            pre_hooks=hook_results,
            permission=decision,
            session_id=self._session_id,
        )

        return ToolResult(
            tool_name=tool_call.tool_name,
            status="blocked",
            blocked_reason=decision.reason,
            duration_ms=duration,
        )

    # ------------------------------------------------------------------
    # Config extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(val: Any) -> Any:
        """Convert a Pydantic model or nested structure to a plain dict."""
        if hasattr(val, "model_dump"):
            return val.model_dump()
        return val

    def _extract_config(self, constitution: Any) -> dict[str, Any]:
        """Extract config dict from a Constitution or dict."""
        self._constitution = constitution  # store for prompt_addendum

        if constitution is None:
            return {}

        # If it's a Constitution object, get the config
        config = getattr(constitution, "config", constitution)

        # If config is a Pydantic model, convert to dict (recursively)
        if hasattr(config, "model_dump"):
            dumped: dict[str, Any] = config.model_dump()
            return dumped
        if isinstance(config, dict):
            return config
        # Try attribute access, converting typed sub-models to dicts
        result: dict[str, Any] = {}
        for key in ("identity", "rules", "permissions", "risk", "hooks", "audit"):
            val = getattr(config, key, None)
            if val is not None:
                result[key] = self._to_dict(val)
        return result

    def _get_custom_rules(self, config: dict[str, Any]) -> list[dict[str, Any]] | None:
        risk = config.get("risk", {})
        if isinstance(risk, dict):
            rules: Any = risk.get("custom_rules")
            if isinstance(rules, list):
                return rules
        return None

    def _get_risk_mode(self, config: dict[str, Any]) -> str:
        risk = config.get("risk", {})
        if isinstance(risk, dict):
            return str(risk.get("classifier", "rules"))
        return "rules"

    def _get_tool_permissions(self, config: dict[str, Any]) -> dict[str, Any]:
        perms = config.get("permissions", {})
        if isinstance(perms, dict):
            tools: Any = perms.get("tools", {})
            if isinstance(tools, dict):
                return tools
        return {}

    def _get_permission_defaults(self, config: dict[str, Any]) -> PermissionDefaults:
        perms = config.get("permissions", {})
        if isinstance(perms, dict):
            defaults_data = perms.get("defaults", {})
            if isinstance(defaults_data, dict):
                return PermissionDefaults(**{
                    k: v for k, v in defaults_data.items()
                    if k in PermissionDefaults.model_fields
                })
        return PermissionDefaults()

    def _get_hook_profile(self, config: dict[str, Any]) -> str:
        hooks = config.get("hooks", {})
        if isinstance(hooks, dict):
            return str(hooks.get("profile", "standard"))
        return "standard"

    def _get_risk_thresholds(self, config: dict[str, Any]) -> dict[str, Any]:
        risk = config.get("risk", {})
        if isinstance(risk, dict):
            thresholds: Any = risk.get("thresholds")
            if isinstance(thresholds, dict):
                return thresholds
        return {"low": "allow", "medium": "allow", "high": "ask", "critical": "deny"}

    def _get_audit_config(self, config: dict[str, Any]) -> dict[str, Any]:
        audit = config.get("audit", {})
        if isinstance(audit, dict):
            return audit
        return {"enabled": True, "output": ".autoharness/audit.jsonl", "retention_days": 30}

    def __repr__(self) -> str:
        return (
            f"<ToolGovernancePipeline mode={self._mode.value!r} "
            f"session={self._session_id!r} "
            f"thresholds={self._risk_thresholds}>"
        )
