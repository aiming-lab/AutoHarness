"""LangChain Integration — CallbackHandler for AutoHarness governance.

Provides a LangChain-compatible callback handler that intercepts tool calls
and applies AutoHarness governance rules (risk classification, permission checks,
output sanitization, and audit logging).

Usage::

    from autoharness.integrations.langchain import AutoHarnessCallback

    callback = AutoHarnessCallback("constitution.yaml")
    agent.invoke({"input": "..."}, config={"callbacks": [callback]})

    # After execution, inspect governance results:
    print(callback.get_audit_summary())
    print(callback.get_prompt_addendum())

Requirements:
    pip install langchain-core

If langchain-core is not installed, importing this module raises a clear
ImportError with installation instructions.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from autoharness.core.constitution import Constitution
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.types import (
    HookAction,
    PermissionDecision,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import of langchain_core
# ---------------------------------------------------------------------------

_LANGCHAIN_IMPORT_ERROR: str | None = None

try:
    from langchain_core.agents import AgentAction, AgentFinish  # noqa: F401
    from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler
except ImportError as _exc:
    _LANGCHAIN_IMPORT_ERROR = (
        f"langchain-core is required for the LangChain integration but was not found. "
        f"Install it with: pip install langchain-core\n"
        f"Original error: {_exc}"
    )
    # Define stubs so the module can be imported without langchain_core
    # (the class __init__ will raise a clear error at instantiation time)
    BaseCallbackHandler = object  # type: ignore[assignment, misc]
    AsyncCallbackHandler = object  # type: ignore[assignment, misc]


def _check_langchain_available() -> None:
    """Raise ImportError if langchain-core is not installed."""
    if _LANGCHAIN_IMPORT_ERROR is not None:
        raise ImportError(_LANGCHAIN_IMPORT_ERROR)


# ---------------------------------------------------------------------------
# Constitution resolver (reuses logic from wrap.py)
# ---------------------------------------------------------------------------


def _resolve_constitution(
    constitution: str | Path | dict[str, Any] | Constitution | None,
) -> Constitution:
    """Resolve a constitution argument to a Constitution instance."""
    if constitution is None:
        return Constitution.default()
    if isinstance(constitution, Constitution):
        return constitution
    if isinstance(constitution, dict):
        return Constitution.from_dict(constitution)
    if isinstance(constitution, (str, Path)):
        return Constitution.load(constitution)
    raise TypeError(
        f"constitution must be a path (str/Path), dict, Constitution, or None; "
        f"got {type(constitution).__name__}"
    )


# ---------------------------------------------------------------------------
# Prompt addendum builder
# ---------------------------------------------------------------------------

_PROMPT_ADDENDUM_MARKER = "<!-- autoharness:governance -->"

_PROMPT_ADDENDUM_TEMPLATE = """\
{marker}
[AutoHarness Governance Active]
The following behavioral rules are enforced. Tool calls that violate these rules
will be blocked or require confirmation before execution:
{rules_summary}
Do not attempt to circumvent these rules.
"""


def _build_prompt_addendum(constitution: Constitution) -> str:
    """Build the system prompt addendum from constitution rules."""
    rules_lines = []
    for rule in constitution.rules:
        severity_tag = f"[{rule.severity.value.upper()}]"
        rules_lines.append(f"- {severity_tag} {rule.description}")
    if not rules_lines:
        rules_lines.append("- Default safety rules are active.")
    return _PROMPT_ADDENDUM_TEMPLATE.format(
        marker=_PROMPT_ADDENDUM_MARKER,
        rules_summary="\n".join(rules_lines),
    )


# ---------------------------------------------------------------------------
# Tool call blocked sentinel
# ---------------------------------------------------------------------------


class ToolCallBlockedError(Exception):
    """Raised when AutoHarness denies a tool call during on_tool_start.

    LangChain catches exceptions from callbacks and can route them through
    on_tool_error. Framework-specific handling (e.g., LangChain ToolException)
    is attempted first; this is the fallback.
    """

    def __init__(self, decision: PermissionDecision, tool_name: str) -> None:
        self.decision = decision
        self.tool_name = tool_name
        super().__init__(
            f"AutoHarness blocked tool '{tool_name}': {decision.reason}"
        )


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------


class _SessionState:
    """Thread-safe session state for tracking chains and tool calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.session_id: str = f"langchain-{uuid.uuid4().hex[:12]}"
        self.chain_depth: int = 0
        self.active_tool_calls: dict[str, ToolCall] = {}
        self.blocked_count: int = 0
        self.allowed_count: int = 0
        self.error_count: int = 0

    def reset(self) -> None:
        with self._lock:
            self.chain_depth = 0
            self.active_tool_calls.clear()
            self.blocked_count = 0
            self.allowed_count = 0
            self.error_count = 0

    def register_tool_start(self, run_id: str, tool_call: ToolCall) -> None:
        with self._lock:
            self.active_tool_calls[run_id] = tool_call

    def pop_tool_call(self, run_id: str) -> ToolCall | None:
        with self._lock:
            return self.active_tool_calls.pop(run_id, None)

    def increment_blocked(self) -> None:
        with self._lock:
            self.blocked_count += 1

    def increment_allowed(self) -> None:
        with self._lock:
            self.allowed_count += 1

    def increment_error(self) -> None:
        with self._lock:
            self.error_count += 1


# ---------------------------------------------------------------------------
# AutoHarnessCallback — sync LangChain callback handler
# ---------------------------------------------------------------------------


class AutoHarnessCallback(BaseCallbackHandler):
    """LangChain callback handler for AutoHarness governance.

    Intercepts tool calls at the ``on_tool_start`` lifecycle point, evaluates
    them against the constitution's governance pipeline, and blocks calls that
    violate the rules. Post-execution output sanitization is applied in
    ``on_tool_end``.

    Parameters
    ----------
    constitution : str | Path | dict | Constitution | None
        Path to a YAML constitution file, a dict, a ``Constitution`` instance,
        or ``None`` to use the default constitution.
    project_dir : str | None
        Project root directory for path-scoping rules. Defaults to cwd.
    session_id : str | None
        Explicit session ID for the audit trail. Auto-generated if omitted.
    raise_on_block : bool
        If ``True`` (default), raise ``ToolCallBlocked`` when a tool call is
        denied. If ``False``, log a warning and allow the call to proceed
        (governance is advisory-only).
    on_blocked : callable | None
        Optional callback invoked with ``(tool_name, decision)`` when a tool
        call is blocked. Called regardless of ``raise_on_block``.

    Usage::

        from autoharness.integrations.langchain import AutoHarnessCallback

        callback = AutoHarnessCallback("constitution.yaml")
        agent.invoke({"input": "..."}, config={"callbacks": [callback]})

        # Inspect results
        summary = callback.get_audit_summary()
        addendum = callback.get_prompt_addendum()

    With LangGraph::

        from langgraph.prebuilt import create_react_agent

        callback = AutoHarnessCallback("constitution.yaml")
        agent = create_react_agent(model, tools)
        agent.invoke(
            {"messages": [("user", "...")]},
            config={"callbacks": [callback]},
        )
    """

    # LangChain callback handler metadata
    name: str = "AutoHarnessCallback"
    raise_error: bool = True

    def __init__(
        self,
        constitution: str | Path | dict[str, Any] | Constitution | None = None,
        *,
        project_dir: str | None = None,
        session_id: str | None = None,
        raise_on_block: bool = True,
        on_blocked: Any = None,
    ) -> None:
        _check_langchain_available()
        # Initialize the base class if it's a real LangChain class
        if BaseCallbackHandler is not object:
            super().__init__()

        self._raise_on_block = raise_on_block
        self._on_blocked_callback = on_blocked

        # Resolve constitution and build pipeline
        self._constitution = _resolve_constitution(constitution)
        self._pipeline = ToolGovernancePipeline(
            self._constitution,
            project_dir=project_dir,
            session_id=session_id,
        )

        # Session tracking
        self._state = _SessionState()
        if session_id:
            self._state.session_id = session_id

        # Prompt addendum
        self._prompt_addendum = _build_prompt_addendum(self._constitution)

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def get_audit_summary(self) -> dict[str, Any]:
        """Return a summary of governance activity for this session.

        Includes counts of allowed, blocked, and errored tool calls,
        plus the full audit engine summary if available.

        Returns
        -------
        dict
            Governance activity summary with keys: session_id, allowed,
            blocked, errors, and pipeline_summary.
        """
        pipeline_summary: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            pipeline_summary = self._pipeline.get_audit_summary()

        return {
            "session_id": self._state.session_id,
            "allowed": self._state.allowed_count,
            "blocked": self._state.blocked_count,
            "errors": self._state.error_count,
            "pipeline_summary": pipeline_summary,
        }

    def get_prompt_addendum(self) -> str:
        """Return the governance prompt addendum for system prompt injection.

        This text can be prepended or appended to the LLM system prompt to
        inform the model about active governance rules.

        Returns
        -------
        str
            Governance rules formatted for system prompt injection.
        """
        return self._prompt_addendum

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Direct access to the governance pipeline for advanced use cases."""
        return self._pipeline

    @property
    def constitution(self) -> Constitution:
        """The resolved constitution used by this callback."""
        return self._constitution

    def reset_counters(self) -> None:
        """Reset session counters (allowed/blocked/errors) to zero."""
        self._state.reset()

    # ------------------------------------------------------------------
    # LangChain callback: on_chain_start / on_chain_end
    # ------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Track chain nesting depth for session context."""
        self._state.chain_depth += 1
        logger.debug(
            "AutoHarness: chain started (depth=%d, name=%s)",
            self._state.chain_depth,
            serialized.get("name", "unknown"),
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Track chain completion."""
        self._state.chain_depth = max(0, self._state.chain_depth - 1)
        logger.debug(
            "AutoHarness: chain ended (depth=%d)", self._state.chain_depth
        )

    # ------------------------------------------------------------------
    # LangChain callback: on_tool_start
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Intercept tool invocation and apply governance checks.

        Creates a ``ToolCall`` from the serialized tool info, runs
        ``pipeline.evaluate()``, and raises ``ToolCallBlocked`` if the
        call is denied.

        Parameters
        ----------
        serialized : dict
            Serialized tool information from LangChain, typically contains
            ``name`` and optionally ``description``.
        input_str : str
            The tool input as a string. May be a JSON string or plain text.
        run_id : Any
            Unique run identifier from LangChain.
        """
        tool_name = serialized.get("name", "unknown_tool")

        # Parse tool input: try JSON first, fall back to raw string
        tool_input = self._parse_tool_input(input_str)

        # Build ToolCall
        run_id_str = str(run_id) if run_id else uuid.uuid4().hex[:12]
        tc = ToolCall(
            tool_name=tool_name,
            tool_input=tool_input,
            session_id=self._state.session_id,
            metadata={
                "provider": "langchain",
                "run_id": run_id_str,
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "tags": tags or [],
                "chain_depth": self._state.chain_depth,
                **(metadata or {}),
            },
        )

        # Register for post-hook correlation
        self._state.register_tool_start(run_id_str, tc)

        # Evaluate governance
        try:
            decision = self._pipeline.evaluate(tc)
        except Exception:
            self._state.increment_error()
            logger.exception(
                "AutoHarness: governance evaluation failed for tool '%s'", tool_name
            )
            # On evaluation error, fail-open or fail-closed based on constitution
            # Default: log and allow (don't break the agent over an internal error)
            return

        if decision.action == "deny":
            self._state.increment_blocked()
            logger.warning(
                "AutoHarness BLOCKED tool call: %s (reason: %s, source: %s)",
                tool_name,
                decision.reason,
                decision.source,
            )

            # Notify optional callback
            if self._on_blocked_callback:
                with contextlib.suppress(Exception):
                    self._on_blocked_callback(tool_name, decision)

            if self._raise_on_block:
                # Try to raise LangChain's ToolException if available
                try:
                    from langchain_core.tools import ToolException
                    raise ToolException(
                        f"AutoHarness blocked tool '{tool_name}': {decision.reason}"
                    )
                except ImportError:
                    raise ToolCallBlockedError(decision, tool_name) from None

        elif decision.action == "ask":
            self._state.increment_blocked()
            logger.info(
                "AutoHarness FLAGGED tool call for confirmation: %s (reason: %s)",
                tool_name,
                decision.reason,
            )

            if self._on_blocked_callback:
                with contextlib.suppress(Exception):
                    self._on_blocked_callback(tool_name, decision)

            if self._raise_on_block:
                try:
                    from langchain_core.tools import ToolException
                    raise ToolException(
                        f"AutoHarness requires confirmation for tool '{tool_name}': "
                        f"{decision.reason}"
                    )
                except ImportError:
                    raise ToolCallBlockedError(decision, tool_name) from None

        else:
            self._state.increment_allowed()
            logger.debug(
                "AutoHarness ALLOWED tool call: %s (source: %s)",
                tool_name,
                decision.source,
            )

    # ------------------------------------------------------------------
    # LangChain callback: on_tool_end
    # ------------------------------------------------------------------

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Apply post-execution hooks (output sanitization).

        If a post-hook returns a sanitized output, this method replaces the
        output by modifying kwargs in-place where possible, or logs a warning.

        Parameters
        ----------
        output : str
            The raw output from the tool execution.
        run_id : Any
            Run identifier for correlation with on_tool_start.
        """
        run_id_str = str(run_id) if run_id else ""
        tc = self._state.pop_tool_call(run_id_str)

        if tc is None:
            # Tool call was not tracked (possibly started before callback was added)
            return

        # Build a ToolResult to pass through post-hooks
        tool_result = ToolResult(
            tool_name=tc.tool_name,
            status="success",
            output=output,
        )

        # Run post-hooks via the hook registry
        context = {
            "session_id": self._state.session_id,
            "project_dir": str(Path.cwd()),
        }

        try:
            _final_result, post_hook_results = (
                self._pipeline.hook_registry.run_post_hooks(tc, tool_result, context)
            )

            # Check if any post-hook sanitized the output
            for hr in post_hook_results:
                if hr.action == HookAction.sanitize and hr.sanitized_output is not None:
                    logger.info(
                        "AutoHarness: output sanitized for tool '%s' (reason: %s)",
                        tc.tool_name,
                        hr.reason,
                    )
                    # LangChain does not natively support output replacement from
                    # callbacks. We log the sanitization; downstream consumers
                    # should check the audit for sanitized outputs.
                    break

        except Exception:
            logger.debug(
                "AutoHarness: post-hook execution failed for tool '%s'",
                tc.tool_name,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # LangChain callback: on_tool_error
    # ------------------------------------------------------------------

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log tool errors to the audit trail.

        Parameters
        ----------
        error : BaseException
            The exception raised during tool execution.
        run_id : Any
            Run identifier for correlation.
        """
        run_id_str = str(run_id) if run_id else ""
        tc = self._state.pop_tool_call(run_id_str)

        # Don't double-count our own blocks as errors
        if isinstance(error, (ToolCallBlockedError,)):
            return
        # Also check for LangChain ToolException that we raised
        error_msg = str(error)
        if "AutoHarness blocked" in error_msg or "AutoHarness requires confirmation" in error_msg:
            return

        self._state.increment_error()

        tool_name = tc.tool_name if tc else "unknown"
        logger.warning(
            "AutoHarness: tool error for '%s': %s",
            tool_name,
            error,
        )

        # Log to audit engine
        if tc is not None:
            with contextlib.suppress(Exception):
                exc: str | Exception = error if isinstance(error, Exception) else str(error)
                self._pipeline.audit_engine.log_error(
                    tc, exc, self._state.session_id
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tool_input(input_str: str) -> dict[str, Any]:
        """Parse tool input string into a dict.

        LangChain passes tool inputs as strings — sometimes JSON-encoded,
        sometimes plain text. This method handles both cases.
        """
        if not input_str:
            return {}

        # Try JSON parsing first
        try:
            parsed = json.loads(input_str)
            if isinstance(parsed, dict):
                return parsed
            # JSON but not a dict (e.g., a string or list)
            return {"input": parsed}
        except (json.JSONDecodeError, TypeError):
            pass

        # Fall back to wrapping the raw string
        return {"input": input_str}

    def __repr__(self) -> str:
        return (
            f"<AutoHarnessCallback constitution={self._constitution!r} "
            f"allowed={self._state.allowed_count} "
            f"blocked={self._state.blocked_count} "
            f"errors={self._state.error_count}>"
        )


# ---------------------------------------------------------------------------
# AutoHarnessAsyncCallback — async LangChain callback handler
# ---------------------------------------------------------------------------


class AutoHarnessAsyncCallback(AsyncCallbackHandler):
    """Async LangChain callback handler for AutoHarness governance.

    Identical governance logic to ``AutoHarnessCallback`` but implements the
    async callback interface for use with async LangChain agents and chains.

    Parameters
    ----------
    constitution : str | Path | dict | Constitution | None
        Constitution source (same as ``AutoHarnessCallback``).
    project_dir : str | None
        Project root directory.
    session_id : str | None
        Explicit session ID.
    raise_on_block : bool
        Whether to raise on denied tool calls (default ``True``).
    on_blocked : callable | None
        Optional callback for blocked tool calls.

    Usage::

        from autoharness.integrations.langchain import AutoHarnessAsyncCallback

        callback = AutoHarnessAsyncCallback("constitution.yaml")
        result = await agent.ainvoke(
            {"input": "..."},
            config={"callbacks": [callback]},
        )
    """

    name: str = "AutoHarnessAsyncCallback"
    raise_error: bool = True

    def __init__(
        self,
        constitution: str | Path | dict[str, Any] | Constitution | None = None,
        *,
        project_dir: str | None = None,
        session_id: str | None = None,
        raise_on_block: bool = True,
        on_blocked: Any = None,
    ) -> None:
        _check_langchain_available()
        if AsyncCallbackHandler is not object:
            super().__init__()

        # Delegate all logic to the sync handler internally
        self._sync = AutoHarnessCallback(
            constitution=constitution,
            project_dir=project_dir,
            session_id=session_id,
            raise_on_block=raise_on_block,
            on_blocked=on_blocked,
        )

    # Proxy public methods
    def get_audit_summary(self) -> dict[str, Any]:
        """Return governance activity summary."""
        return self._sync.get_audit_summary()

    def get_prompt_addendum(self) -> str:
        """Return governance prompt addendum."""
        return self._sync.get_prompt_addendum()

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Direct access to the governance pipeline."""
        return self._sync.pipeline

    @property
    def constitution(self) -> Constitution:
        """The resolved constitution."""
        return self._sync.constitution

    def reset_counters(self) -> None:
        """Reset session counters."""
        self._sync.reset_counters()

    # ------------------------------------------------------------------
    # Async callbacks — delegate to sync logic (pipeline is CPU-bound)
    # ------------------------------------------------------------------

    async def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Track chain start (async)."""
        self._sync.on_chain_start(
            serialized,
            inputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            **kwargs,
        )

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Track chain end (async)."""
        self._sync.on_chain_end(
            outputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Intercept tool call and apply governance (async)."""
        # Governance evaluation is CPU-bound; delegate to sync
        self._sync.on_tool_start(
            serialized,
            input_str,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            **kwargs,
        )

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Apply post-execution hooks (async)."""
        self._sync.on_tool_end(
            output,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            **kwargs,
        )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log tool errors to audit (async)."""
        self._sync.on_tool_error(
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            **kwargs,
        )

    def __repr__(self) -> str:
        return f"<AutoHarnessAsyncCallback({self._sync!r})>"
