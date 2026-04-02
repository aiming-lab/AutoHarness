"""AutoHarness Wrapper API — the main user-facing entry point.

Provides two ways to use AutoHarness governance:

1. **Client wrapping** — transparently intercept tool calls from Anthropic or
   OpenAI clients::

       import anthropic
       from autoharness import AutoHarness

       client = AutoHarness.wrap(anthropic.Anthropic(), constitution="constitution.yaml")
       # Use client.messages.create() as normal — tool calls are governed

2. **Standalone linting** — check a single tool call without wrapping::

       from autoharness import lint_tool_call

       result = lint_tool_call("Bash", {"command": "rm -rf /"}, constitution="constitution.yaml")
       assert result.status == "blocked"
"""

from __future__ import annotations

import contextlib
import copy
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from autoharness.core.constitution import Constitution
from autoharness.core.hooks import HookRegistry
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.types import (
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt addendum injected into system messages
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
        severity_tag = f"[{rule.severity.value.upper()}]" if hasattr(rule, "severity") else ""
        rules_lines.append(f"- {severity_tag} {rule.description}")

    if not rules_lines:
        rules_lines.append("- Default safety rules are active.")

    return _PROMPT_ADDENDUM_TEMPLATE.format(
        marker=_PROMPT_ADDENDUM_MARKER,
        rules_summary="\n".join(rules_lines),
    )


# ---------------------------------------------------------------------------
# Constitution resolver
# ---------------------------------------------------------------------------


def _resolve_constitution(
    constitution: str | Path | dict[str, Any] | Constitution | None,
    project_dir: str | None = None,
) -> Constitution:
    """Resolve a constitution argument to a Constitution instance.

    Accepts:
    - None -> default constitution
    - str/Path -> load from YAML file
    - dict -> build from dict
    - Constitution -> use as-is
    """
    if constitution is None:
        # Use cascading config discovery (user -> project -> local)
        return Constitution.discover(project_dir)

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
# Pipeline factory
# ---------------------------------------------------------------------------


def _build_pipeline(
    constitution: Constitution,
    hooks: list[Callable[..., Any]] | None,
    project_dir: str | None,
    session_id: str | None,
) -> ToolGovernancePipeline:
    """Construct a ToolGovernancePipeline from configuration."""
    # Determine profile from constitution
    hook_config = constitution.hook_config
    profile = "standard"
    if isinstance(hook_config, dict):
        profile = hook_config.get("profile", "standard")
    elif hasattr(hook_config, "value"):
        # It's a HookProfile enum — but we need a string for HookRegistry
        profile = "standard"

    # Build hook registry
    registry = HookRegistry(
        profile=profile,
        project_root=project_dir or os.getcwd(),
    )

    # Register custom hooks
    if hooks:
        registry.register_hooks(hooks)

    # Register decorator-based hooks
    registry.register_from_decorators()

    # Extract risk thresholds from constitution
    risk_config = constitution.risk_config
    _thresholds = None
    if isinstance(risk_config, dict):
        _thresholds = risk_config.get("thresholds")
    elif hasattr(risk_config, "escalation_threshold"):
        # Legacy RiskConfig — map to thresholds dict
        _thresholds = {
            "low": "allow",
            "medium": "allow",
            "high": "ask",
            "critical": "deny",
        }

    # Determine session ID
    sid = session_id or f"autoharness-{uuid.uuid4().hex[:12]}"

    # Determine audit setting
    audit_config = constitution.audit_config
    _audit_enabled = True
    if isinstance(audit_config, dict):
        _audit_enabled = audit_config.get("enabled", True)
    elif hasattr(audit_config, "enabled"):
        _audit_enabled = audit_config.enabled

    return ToolGovernancePipeline(
        constitution,
        project_dir=project_dir,
        session_id=sid,
        hook_registry=registry if hooks else None,
    )


# ---------------------------------------------------------------------------
# Client type detection
# ---------------------------------------------------------------------------


def _detect_client_type(client: Any) -> str:
    """Detect whether a client is Anthropic or OpenAI (sync or async).

    Returns 'anthropic', 'async_anthropic', 'openai', 'async_openai',
    or raises TypeError.
    """
    module = type(client).__module__ or ""
    class_name = type(client).__name__

    # Anthropic: anthropic.Anthropic, anthropic.AsyncAnthropic
    if "anthropic" in module or class_name in ("Anthropic", "AsyncAnthropic"):
        if class_name == "AsyncAnthropic" or "async" in module.lower():
            return "async_anthropic"
        return "anthropic"

    # OpenAI: openai.OpenAI, openai.AsyncOpenAI
    if "openai" in module or class_name in ("OpenAI", "AsyncOpenAI"):
        if class_name == "AsyncOpenAI" or "async" in module.lower():
            return "async_openai"
        return "openai"

    raise TypeError(
        f"Unsupported client type: {class_name} (module: {module}). "
        f"AutoHarness supports Anthropic and OpenAI clients."
    )


# ---------------------------------------------------------------------------
# Anthropic wrapper
# ---------------------------------------------------------------------------


class _GovernedMessagesAPI:
    """Proxy for `client.messages` that intercepts `.create()` calls."""

    def __init__(
        self,
        original_messages: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._original = original_messages
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum

    def __getattr__(self, name: str) -> Any:
        """Proxy all attributes except 'create' to the original messages API."""
        return getattr(self._original, name)

    def create(self, **kwargs: Any) -> Any:
        """Intercept messages.create() to inject governance."""
        # Step 1: Inject prompt addendum into system message
        kwargs = self._inject_system_prompt(kwargs)

        # Step 2: Call the original API
        response = self._original.create(**kwargs)

        # Step 3: Govern tool_use blocks in the response
        return self._govern_response(response)

    def stream(self, **kwargs: Any) -> _GovernedStream:
        """Wrap streaming create with governance.

        Governance is applied when the stream completes and tool_use
        blocks are fully received, not during streaming. Text chunks
        are passed through unchanged; tool_use blocks are buffered and
        governed when complete.

        Returns a ``_GovernedStream`` context manager that yields stream
        events and attaches ``blocked_tool_results`` to the final message.
        """
        kwargs = self._inject_system_prompt(kwargs)
        original_stream = self._original.stream(**kwargs)
        return _GovernedStream(original_stream, self._pipeline)

    def _inject_system_prompt(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Add governance addendum to the system message if not present."""
        kwargs = copy.copy(kwargs)
        system = kwargs.get("system", "")

        if isinstance(system, str):
            if _PROMPT_ADDENDUM_MARKER not in system:
                separator = "\n\n" if system.strip() else ""
                kwargs["system"] = system + separator + self._prompt_addendum
        elif isinstance(system, list):
            # system can be a list of content blocks for Anthropic
            full_text = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in system
            )
            if _PROMPT_ADDENDUM_MARKER not in full_text:
                system = list(system)  # copy
                system.append({"type": "text", "text": self._prompt_addendum})
                kwargs["system"] = system

        return kwargs

    def _govern_response(self, response: Any) -> Any:
        """Check each tool_use block in the response against the pipeline.

        Blocked tool calls are handled by keeping the original tool_use block
        (so the agent loop can match it with a tool_result) AND storing a
        synthetic error tool_result that the caller should feed back. This
        tells the LLM that the tool was blocked, so it can adjust.

        The ``blocked_tool_results`` attribute on the response (or proxy)
        contains a list of ``{"tool_use_id": ..., "content": ..., "is_error": True}``
        dicts that must be sent back as ``tool_result`` messages.
        """
        # Anthropic responses have response.content = list of content blocks
        if not hasattr(response, "content") or not isinstance(response.content, list):
            return response

        new_content: list[Any] = []
        blocked_tool_results: list[dict[str, Any]] = []
        modified = False

        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type != "tool_use":
                new_content.append(block)
                continue

            # Extract tool call info
            tool_name = getattr(block, "name", "unknown")
            tool_input = getattr(block, "input", {})
            tool_use_id = getattr(block, "id", "unknown")

            # Build a ToolCall for the pipeline
            tc = ToolCall(
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {},
                metadata={"tool_use_id": tool_use_id, "provider": "anthropic"},
            )

            # Evaluate
            decision = self._pipeline.evaluate(tc)

            if decision.action == "deny":
                logger.warning(
                    "AutoHarness BLOCKED tool call: %s (reason: %s)",
                    tool_name,
                    decision.reason,
                )
                # Keep the tool_use block so the agent loop can pair it with a result
                new_content.append(block)
                # Generate a synthetic tool_result the caller MUST send back
                blocked_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": (
                        f"[AutoHarness] Tool call BLOCKED: {decision.reason}. "
                        f"This tool call was denied by the governance policy. "
                        f"Do not retry the same operation."
                    ),
                })
                modified = True
            elif decision.action == "ask":
                # Ask — use the pipeline's ask handler
                resolved = self._pipeline._handle_ask(tc, decision)
                if resolved.action == "deny":
                    logger.info(
                        "AutoHarness ASK->DENIED tool call: %s (reason: %s)",
                        tool_name,
                        resolved.reason,
                    )
                    new_content.append(block)
                    blocked_tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "is_error": True,
                        "content": (
                            f"[AutoHarness] Tool call DENIED (confirmation rejected): "
                            f"{resolved.reason}. Do not retry."
                        ),
                    })
                    modified = True
                else:
                    # Approved — pass through
                    new_content.append(block)
            else:
                # Allowed — pass through unchanged
                new_content.append(block)

        if modified or blocked_tool_results:
            # Replace response content and attach blocked results
            try:
                response.content = new_content
                response.blocked_tool_results = blocked_tool_results
            except (AttributeError, TypeError):
                response = _ResponseProxy(response, new_content, blocked_tool_results)

        return response


class _GovernedStream:
    """Context manager wrapping an Anthropic streaming response with governance.

    Text chunks are yielded unchanged. Tool_use blocks are buffered until
    complete, then governed. Blocked tool calls produce synthetic error
    tool_results available via ``blocked_tool_results`` after the stream
    finishes.

    Usage::

        with governed_messages.stream(model="...", ...) as stream:
            for event in stream:
                # text_delta events pass through unchanged
                print(event)
        # After stream completes:
        blocked = stream.blocked_tool_results
    """

    def __init__(self, original_stream: Any, pipeline: ToolGovernancePipeline) -> None:
        self._original_stream = original_stream
        self._pipeline = pipeline
        self._blocked_tool_results: list[dict[str, Any]] = []
        self._tool_use_blocks: list[dict[str, Any]] = []
        self._current_tool_use: dict[str, Any] | None = None
        self._stream_context: Any = None

    @property
    def blocked_tool_results(self) -> list[dict[str, Any]]:
        """Synthetic tool_result messages for blocked tool calls.

        Available after the stream has been fully consumed. The caller
        MUST send these back to the LLM as tool_result messages so it
        knows the tool was blocked.
        """
        return self._blocked_tool_results

    def __enter__(self) -> _GovernedStream:
        self._stream_context = self._original_stream.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        # Govern any remaining buffered tool_use blocks
        self._govern_buffered_tools()
        if self._stream_context is not None:
            with contextlib.suppress(Exception):
                self._original_stream.__exit__(*args)

    def __iter__(self) -> _GovernedStream:
        return self

    def __next__(self) -> Any:
        try:
            event = next(self._stream_context)
        except StopIteration:
            # Stream ended — govern any remaining tool_use blocks
            self._govern_buffered_tools()
            raise

        # Detect tool_use events and buffer them
        event_type = getattr(event, "type", None)

        if event_type == "content_block_start":
            block = getattr(event, "content_block", None)
            if block is not None and getattr(block, "type", None) == "tool_use":
                self._current_tool_use = {
                    "id": getattr(block, "id", "unknown"),
                    "name": getattr(block, "name", "unknown"),
                    "input_json": "",
                }

        elif event_type == "content_block_delta":
            delta = getattr(event, "delta", None)
            if (
                self._current_tool_use is not None
                and delta is not None
                and getattr(delta, "type", None) == "input_json_delta"
            ):
                self._current_tool_use["input_json"] += getattr(
                    delta, "partial_json", ""
                )

        elif event_type == "content_block_stop":
            if self._current_tool_use is not None:
                self._tool_use_blocks.append(self._current_tool_use)
                self._current_tool_use = None

        return event

    def _govern_buffered_tools(self) -> None:
        """Apply governance to all buffered tool_use blocks."""
        import json as _json

        for block_info in self._tool_use_blocks:
            tool_name = block_info.get("name", "unknown")
            tool_use_id = block_info.get("id", "unknown")
            input_json_str = block_info.get("input_json", "{}")

            try:
                tool_input = _json.loads(input_json_str)
            except (_json.JSONDecodeError, TypeError):
                tool_input = {}

            tc = ToolCall(
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {},
                metadata={"tool_use_id": tool_use_id, "provider": "anthropic"},
            )

            decision = self._pipeline.evaluate(tc)

            if decision.action == "deny":
                logger.warning(
                    "AutoHarness BLOCKED streamed tool call: %s (reason: %s)",
                    tool_name,
                    decision.reason,
                )
                self._blocked_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": (
                        f"[AutoHarness] Tool call BLOCKED: {decision.reason}. "
                        f"This tool call was denied by the governance policy. "
                        f"Do not retry the same operation."
                    ),
                })
            elif decision.action == "ask":
                resolved = self._pipeline._handle_ask(tc, decision)
                if resolved.action == "deny":
                    logger.info(
                        "AutoHarness ASK->DENIED streamed tool call: %s (reason: %s)",
                        tool_name,
                        resolved.reason,
                    )
                    self._blocked_tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "is_error": True,
                        "content": (
                            f"[AutoHarness] Tool call DENIED (confirmation rejected): "
                            f"{resolved.reason}. Do not retry."
                        ),
                    })

        # Clear buffer
        self._tool_use_blocks.clear()


class _ResponseProxy:
    """Lightweight proxy when the original response object is immutable."""

    def __init__(
        self,
        original: Any,
        new_content: list[Any],
        blocked_tool_results: list[dict[str, Any]] | None = None,
    ) -> None:
        self._original = original
        self.content = new_content
        self.blocked_tool_results = blocked_tool_results or []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class AnthropicWrapper:
    """Wrapped Anthropic client with governance middleware.

    Proxies all attributes to the original client. The `messages` attribute
    returns a governed messages API that intercepts `create()` calls.
    """

    def __init__(
        self,
        client: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._client = client
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum
        self._governed_messages = _GovernedMessagesAPI(
            client.messages, pipeline, prompt_addendum,
        )

    @property
    def messages(self) -> _GovernedMessagesAPI:
        """Return the governed messages API."""
        return self._governed_messages

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Access the governance pipeline for audit/introspection."""
        return self._pipeline

    def __getattr__(self, name: str) -> Any:
        """Proxy everything else to the original client."""
        return getattr(self._client, name)

    def __repr__(self) -> str:
        return f"<AnthropicWrapper client={type(self._client).__name__}>"


# ---------------------------------------------------------------------------
# Async Anthropic wrapper
# ---------------------------------------------------------------------------


class _AsyncGovernedMessagesAPI:
    """Async proxy for `client.messages` that intercepts `.create()` calls."""

    def __init__(
        self,
        original_messages: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._original = original_messages
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum

    def __getattr__(self, name: str) -> Any:
        """Proxy all attributes except 'create' to the original messages API."""
        return getattr(self._original, name)

    async def create(self, **kwargs: Any) -> Any:
        """Intercept messages.create() to inject governance (async)."""
        # Step 1: Inject prompt addendum into system message
        kwargs = self._inject_system_prompt(kwargs)

        # Step 2: Call the original async API
        response = await self._original.create(**kwargs)

        # Step 3: Govern tool_use blocks in the response
        return self._govern_response(response)

    def _inject_system_prompt(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Add governance addendum to the system message if not present."""
        return _GovernedMessagesAPI._inject_system_prompt(self, kwargs)  # type: ignore[arg-type]

    def _govern_response(self, response: Any) -> Any:
        """Check each tool_use block in the response against the pipeline."""
        return _GovernedMessagesAPI._govern_response(self, response)  # type: ignore[arg-type]


class AsyncAnthropicWrapper:
    """Wrapped AsyncAnthropic client with governance middleware.

    Proxies all attributes to the original client. The `messages` attribute
    returns a governed messages API that intercepts `create()` calls.
    """

    def __init__(
        self,
        client: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._client = client
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum
        self._governed_messages = _AsyncGovernedMessagesAPI(
            client.messages, pipeline, prompt_addendum,
        )

    @property
    def messages(self) -> _AsyncGovernedMessagesAPI:
        """Return the governed messages API."""
        return self._governed_messages

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Access the governance pipeline for audit/introspection."""
        return self._pipeline

    def __getattr__(self, name: str) -> Any:
        """Proxy everything else to the original client."""
        return getattr(self._client, name)

    def __repr__(self) -> str:
        return f"<AsyncAnthropicWrapper client={type(self._client).__name__}>"


# ---------------------------------------------------------------------------
# OpenAI wrapper
# ---------------------------------------------------------------------------


class _GovernedCompletionsAPI:
    """Proxy for `client.chat.completions` that intercepts `.create()` calls."""

    def __init__(
        self,
        original_completions: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._original = original_completions
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    def create(self, **kwargs: Any) -> Any:
        """Intercept chat.completions.create() to inject governance."""
        # Step 1: Inject prompt addendum into system messages
        kwargs = self._inject_system_prompt(kwargs)

        # Step 2: Call the original API
        response = self._original.create(**kwargs)

        # Step 3: Govern tool_calls in the response
        return self._govern_response(response)

    def _inject_system_prompt(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Add governance addendum to the first system message."""
        kwargs = copy.copy(kwargs)
        messages = kwargs.get("messages", [])

        if not messages:
            return kwargs

        messages = list(messages)  # shallow copy

        # Find first system message
        for i, msg in enumerate(messages):
            if isinstance(msg, dict) and msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str) and _PROMPT_ADDENDUM_MARKER not in content:
                    messages[i] = {**msg, "content": content + "\n\n" + self._prompt_addendum}
                    kwargs["messages"] = messages
                    return kwargs

        # No system message found — prepend one
        messages.insert(0, {"role": "system", "content": self._prompt_addendum})
        kwargs["messages"] = messages
        return kwargs

    def _govern_response(self, response: Any) -> Any:
        """Check tool_calls in the response against the pipeline.

        Blocked tool calls generate synthetic tool-result messages that the
        caller must send back to the LLM, stored in
        ``response.blocked_tool_results``.
        """
        import json as _json

        # OpenAI responses: response.choices[0].message.tool_calls
        if not hasattr(response, "choices") or not response.choices:
            return response

        choice = response.choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            return response

        tool_calls_list = getattr(message, "tool_calls", None)
        if not tool_calls_list:
            return response

        blocked_tool_results: list[dict[str, Any]] = []

        for tc_obj in tool_calls_list:
            func = getattr(tc_obj, "function", None)
            if func is None:
                continue

            tool_name = getattr(func, "name", "unknown")
            tool_call_id = getattr(tc_obj, "id", "unknown")

            try:
                tool_input = _json.loads(getattr(func, "arguments", "{}"))
            except (_json.JSONDecodeError, TypeError):
                tool_input = {}

            tc = ToolCall(
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {},
                metadata={
                    "tool_call_id": tool_call_id,
                    "provider": "openai",
                },
            )

            decision = self._pipeline.evaluate(tc)

            if decision.action == "deny":
                logger.warning(
                    "AutoHarness BLOCKED tool call: %s (reason: %s)",
                    tool_name,
                    decision.reason,
                )
                blocked_tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": (
                        f"[AutoHarness] Tool call BLOCKED: {decision.reason}. "
                        f"Do not retry the same operation."
                    ),
                })
            elif decision.action == "ask":
                resolved = self._pipeline._handle_ask(tc, decision)
                if resolved.action == "deny":
                    blocked_tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": (
                            f"[AutoHarness] Tool call DENIED: {resolved.reason}. "
                            f"Do not retry."
                        ),
                    })

        if blocked_tool_results:
            try:
                response.blocked_tool_results = blocked_tool_results
            except (AttributeError, TypeError):
                # Wrap if response is frozen
                response = _ResponseProxy(response, response.choices, blocked_tool_results)

        return response


class _GovernedChatAPI:
    """Proxy for `client.chat` that returns governed completions."""

    def __init__(
        self,
        original_chat: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._original = original_chat
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum
        self._governed_completions = _GovernedCompletionsAPI(
            original_chat.completions, pipeline, prompt_addendum,
        )

    @property
    def completions(self) -> _GovernedCompletionsAPI:
        return self._governed_completions

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class OpenAIWrapper:
    """Wrapped OpenAI client with governance middleware.

    Proxies all attributes to the original client. The `chat.completions`
    path returns a governed API that intercepts `create()` calls.
    """

    def __init__(
        self,
        client: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._client = client
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum
        self._governed_chat = _GovernedChatAPI(
            client.chat, pipeline, prompt_addendum,
        )

    @property
    def chat(self) -> _GovernedChatAPI:
        """Return the governed chat API."""
        return self._governed_chat

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Access the governance pipeline for audit/introspection."""
        return self._pipeline

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def __repr__(self) -> str:
        return f"<OpenAIWrapper client={type(self._client).__name__}>"


# ---------------------------------------------------------------------------
# Async OpenAI wrapper
# ---------------------------------------------------------------------------


class _AsyncGovernedCompletionsAPI:
    """Async proxy for `client.chat.completions` that intercepts `.create()` calls."""

    def __init__(
        self,
        original_completions: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._original = original_completions
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    async def create(self, **kwargs: Any) -> Any:
        """Intercept chat.completions.create() to inject governance (async)."""
        # Step 1: Inject prompt addendum into system messages
        kwargs = self._inject_system_prompt(kwargs)

        # Step 2: Call the original async API
        response = await self._original.create(**kwargs)

        # Step 3: Govern tool_calls in the response
        return self._govern_response(response)

    def _inject_system_prompt(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Add governance addendum to the first system message."""
        return _GovernedCompletionsAPI._inject_system_prompt(self, kwargs)  # type: ignore[arg-type]

    def _govern_response(self, response: Any) -> Any:
        """Check tool_calls in the response against the pipeline."""
        return _GovernedCompletionsAPI._govern_response(self, response)  # type: ignore[arg-type]


class _AsyncGovernedChatAPI:
    """Async proxy for `client.chat` that returns governed completions."""

    def __init__(
        self,
        original_chat: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._original = original_chat
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum
        self._governed_completions = _AsyncGovernedCompletionsAPI(
            original_chat.completions, pipeline, prompt_addendum,
        )

    @property
    def completions(self) -> _AsyncGovernedCompletionsAPI:
        return self._governed_completions

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class AsyncOpenAIWrapper:
    """Wrapped AsyncOpenAI client with governance middleware.

    Proxies all attributes to the original client. The `chat.completions`
    path returns a governed API that intercepts `create()` calls.
    """

    def __init__(
        self,
        client: Any,
        pipeline: ToolGovernancePipeline,
        prompt_addendum: str,
    ) -> None:
        self._client = client
        self._pipeline = pipeline
        self._prompt_addendum = prompt_addendum
        self._governed_chat = _AsyncGovernedChatAPI(
            client.chat, pipeline, prompt_addendum,
        )

    @property
    def chat(self) -> _AsyncGovernedChatAPI:
        """Return the governed chat API."""
        return self._governed_chat

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Access the governance pipeline for audit/introspection."""
        return self._pipeline

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def __repr__(self) -> str:
        return f"<AsyncOpenAIWrapper client={type(self._client).__name__}>"


# ---------------------------------------------------------------------------
# AutoHarness — main entry point
# ---------------------------------------------------------------------------


class AutoHarness:
    """Main entry point for AutoHarness governance middleware.

    Usage::

        import anthropic
        from autoharness import AutoHarness

        # Wrap with auto-discovered or default constitution
        client = AutoHarness.wrap(anthropic.Anthropic())

        # Wrap with explicit constitution
        client = AutoHarness.wrap(
            anthropic.Anthropic(),
            constitution="path/to/constitution.yaml",
        )

        # Use as normal — governance is transparent
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": "List files"}],
        )
    """

    @classmethod
    def wrap(
        cls,
        client: Any,
        constitution: str | Path | dict[str, Any] | Constitution | None = None,
        hooks: list[Callable[..., Any]] | None = None,
        project_dir: str | None = None,
        session_id: str | None = None,
    ) -> AnthropicWrapper | OpenAIWrapper | AsyncAnthropicWrapper | AsyncOpenAIWrapper:
        """Wrap an LLM client with governance middleware.

        Parameters
        ----------
        client
            An Anthropic or OpenAI client instance (sync or async).
        constitution
            Path to a YAML file, a dict, a Constitution instance, or None
            for auto-discovery / defaults.
        hooks
            List of custom hook functions decorated with ``@hook``.
        project_dir
            Project root directory for path scoping. Defaults to cwd.
        session_id
            Session ID for audit trail. Auto-generated if not provided.

        Returns
        -------
        AnthropicWrapper | OpenAIWrapper | AsyncAnthropicWrapper | AsyncOpenAIWrapper
            A wrapped client that intercepts tool_use and applies governance.

        Raises
        ------
        TypeError
            If the client type is not supported.
        """
        # Detect client type
        client_type = _detect_client_type(client)

        # Resolve constitution
        resolved = _resolve_constitution(constitution, project_dir)
        logger.info("AutoHarness wrapping %s client with constitution: %r", client_type, resolved)

        # Build pipeline
        pipeline = _build_pipeline(resolved, hooks, project_dir, session_id)

        # Build prompt addendum
        addendum = _build_prompt_addendum(resolved)

        # Return the appropriate wrapper
        if client_type == "anthropic":
            return AnthropicWrapper(client, pipeline, addendum)
        elif client_type == "async_anthropic":
            return AsyncAnthropicWrapper(client, pipeline, addendum)
        elif client_type == "async_openai":
            return AsyncOpenAIWrapper(client, pipeline, addendum)
        else:
            return OpenAIWrapper(client, pipeline, addendum)

    @classmethod
    def from_constitution(
        cls,
        constitution: str | Path | dict[str, Any] | Constitution | None = None,
        project_dir: str | None = None,
        session_id: str | None = None,
    ) -> ToolGovernancePipeline:
        """Create a standalone governance pipeline without wrapping a client.

        Useful for programmatic tool-call checking without an LLM client.

        Parameters
        ----------
        constitution
            Path, dict, or Constitution instance.
        project_dir
            Project root directory for path scoping.
        session_id
            Session ID for audit trail.

        Returns
        -------
        ToolGovernancePipeline
            A configured pipeline instance.
        """
        resolved = _resolve_constitution(constitution, project_dir)
        return _build_pipeline(resolved, hooks=None, project_dir=project_dir, session_id=session_id)


# ---------------------------------------------------------------------------
# Standalone function (with pipeline caching)
# ---------------------------------------------------------------------------

# Module-level pipeline cache for lint_tool_call performance.
# Key = (constitution_path_or_id, project_dir). Avoids rebuilding the full
# pipeline (incl. opening a new audit file handle) on every call.
_lint_pipeline_cache: dict[tuple[str, str | None], ToolGovernancePipeline] = {}


def lint_tool_call(
    tool_name: str,
    tool_input: dict[str, Any] | None,
    constitution: str | Path | dict[str, Any] | Constitution | None = None,
    project_dir: str | None = None,
    session_id: str | None = None,
    hooks: list[Any] | None = None,
    **kwargs: Any,
) -> ToolResult:
    """One-shot governance check without wrapping a client.

    Evaluates a single tool call against the constitution and returns
    a ToolResult indicating whether the call would be allowed, blocked,
    or flagged.

    The pipeline is cached per (constitution, project_dir) combination
    so repeated calls avoid the overhead of rebuilding the pipeline.

    Parameters
    ----------
    tool_name : str
        Name of the tool being called (e.g., "Bash", "Edit", "Write").
    tool_input : dict
        Arguments that would be passed to the tool.
    constitution
        Path, dict, Constitution, or None for defaults.
    project_dir : str | None
        Project root for path scoping.
    session_id : str | None
        Session ID for audit.
    **kwargs
        Additional metadata added to the ToolCall.

    Returns
    -------
    ToolResult
        A result with status "success" (allowed), "blocked", or "error".

    Examples
    --------
    >>> result = lint_tool_call("Bash", {"command": "rm -rf /"})
    >>> result.status
    'blocked'
    >>> result.blocked_reason
    'Secret detected in tool input: ...'

    >>> result = lint_tool_call("Read", {"file_path": "/tmp/safe.txt"})
    >>> result.status
    'success'
    """
    # Build a cache key from the constitution identity
    pdir = project_dir or str(Path.cwd())
    if isinstance(constitution, (str, Path)):
        cache_key = (str(constitution), pdir)
    elif constitution is None:
        cache_key = ("__default__", pdir)
    else:
        cache_key = (str(id(constitution)), pdir)

    # Gracefully handle None tool_input
    if tool_input is None:
        tool_input = {}

    pipeline = _lint_pipeline_cache.get(cache_key)
    if pipeline is None:
        resolved = _resolve_constitution(constitution, project_dir)
        pipeline = _build_pipeline(
            resolved, hooks=hooks,
            project_dir=project_dir, session_id=session_id,
        )
        # Only cache when no custom hooks (custom hooks are per-call)
        if hooks is None:
            _lint_pipeline_cache[cache_key] = pipeline
    elif hooks is not None:
        # Rebuild pipeline with custom hooks (don't cache)
        resolved = _resolve_constitution(constitution, project_dir)
        pipeline = _build_pipeline(
            resolved, hooks=hooks,
            project_dir=project_dir, session_id=session_id,
        )

    # Build ToolCall
    tc = ToolCall(
        tool_name=tool_name,
        tool_input=tool_input,
        metadata=kwargs.get("metadata", {}),
    )

    # Evaluate
    try:
        decision = pipeline.evaluate(tc)
    except Exception as exc:
        logger.exception("Error during governance evaluation")
        return ToolResult(
            tool_name=tool_name,
            status="error",
            error=f"Governance evaluation failed: {exc}",
        )

    # Map decision to ToolResult
    if decision.action == "deny":
        return ToolResult(
            tool_name=tool_name,
            status="blocked",
            blocked_reason=decision.reason,
        )
    elif decision.action == "ask":
        return ToolResult(
            tool_name=tool_name,
            status="blocked",
            blocked_reason=f"Requires confirmation: {decision.reason}",
        )
    else:
        return ToolResult(
            tool_name=tool_name,
            status="success",
            output=f"Tool call '{tool_name}' passed governance checks",
        )
