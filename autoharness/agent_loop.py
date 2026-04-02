"""AgentLoop -- the core agent execution loop that integrates all AutoHarness subsystems.

This is the heart of the framework. It wires together:
- Context management (token tracking, auto-compaction)
- Prompt assembly (section framework, cache boundaries)
- Tool system (registry, concurrent orchestration, output budgets)
- Skill system (two-layer injection)
- Governance (14-step pipeline, permissions, hooks)
- Session management (persistence, cost tracking)
- Agent orchestration (built-in agents, fork, background)

Usage:
    from autoharness import AgentLoop

    loop = AgentLoop(
        model="claude-sonnet-4-6",
        api_key="sk-...",
        constitution="constitution.yaml",  # optional
    )
    result = loop.run("Fix the bug in auth.py")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from autoharness.context.autocompact import AutoCompactor
from autoharness.context.microcompact import microcompact
from autoharness.context.models import get_context_window, get_max_output_tokens
from autoharness.context.tokens import TokenBudget, estimate_message_tokens
from autoharness.core.constitution import Constitution
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.types import ToolCall
from autoharness.prompt.sections import (
    SystemPromptRegistry,
    system_prompt_section,
    uncached_section,
)
from autoharness.session.cost import SessionCost
from autoharness.session.persistence import SessionState, save_session
from autoharness.session.transcript import TranscriptWriter
from autoharness.skills.loader import SkillRegistry, load_skills_into_registry
from autoharness.tools.orchestrator import ToolOrchestrator
from autoharness.tools.registry import ToolDefinition, ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM callback type
# ---------------------------------------------------------------------------

LLMCallback = Callable[
    [str, list[dict[str, Any]], list[dict[str, Any]], int],
    dict[str, Any],
]
"""Signature: (model, messages, tools, max_tokens) -> response_dict

The response_dict should contain:
- "content": list of content blocks (text / tool_use)
- "stop_reason": str ("end_turn" | "tool_use" | ...)
- "usage": {"input_tokens": int, "output_tokens": int}
"""


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------


class AgentLoop:
    """Core agent execution loop integrating all AutoHarness subsystems.

    Wires together context management, prompt assembly, tool execution,
    skill injection, governance, and session management into a single
    coherent agent loop.

    Parameters
    ----------
    model : str
        Model identifier (e.g., ``"claude-sonnet-4-6"``).
    api_key : str or None
        API key for the LLM provider. When ``None``, the loop is still
        importable and configurable but requires an ``llm_callback`` to
        actually run.
    constitution : str, Path, dict, Constitution, or None
        Governance constitution. ``None`` uses auto-discovered defaults.
    tools : list[ToolDefinition] or None
        Additional tools to register beyond defaults.
    skills_dir : str or None
        Directory to scan for skill files. ``None`` uses default paths.
    session_dir : str or None
        Directory for session persistence files.
    project_dir : str or None
        Project root directory (for path scoping and governance).
    llm_callback : LLMCallback or None
        Custom LLM call function. When provided, this replaces the
        default Anthropic API call, enabling testing and alternate
        providers.
    max_iterations : int
        Maximum loop iterations before forced stop.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        constitution: str | Path | dict[str, Any] | Constitution | None = None,
        tools: list[ToolDefinition] | None = None,
        skills_dir: str | None = None,
        session_dir: str | None = None,
        project_dir: str | None = None,
        llm_callback: LLMCallback | None = None,
        max_iterations: int = 200,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_iterations = max_iterations
        self.project_dir = project_dir or str(Path.cwd())
        self.session_dir = session_dir

        # --- Session identity ---
        self._session_id = str(uuid.uuid4())[:12]

        # --- Constitution ---
        self._constitution = self._resolve_constitution(constitution)

        # --- Tool Registry ---
        self._tool_registry = ToolRegistry()
        if tools:
            for tool in tools:
                self._tool_registry.register(tool)

        # --- Tool Orchestrator ---
        self._tool_orchestrator = ToolOrchestrator(registry=self._tool_registry)

        # --- Skill Registry ---
        self._skill_registry = SkillRegistry()
        self._load_skills(skills_dir)

        # --- System Prompt Registry ---
        self._prompt_registry = SystemPromptRegistry()
        self._register_default_prompt_sections()

        # --- Token Budget ---
        context_window = get_context_window(model)
        self._token_budget = TokenBudget(max_tokens=context_window)

        # --- AutoCompactor ---
        self._auto_compactor = AutoCompactor(
            token_budget=self._token_budget,
            model=model,
        )

        # --- Governance Pipeline ---
        self._pipeline = ToolGovernancePipeline(
            self._constitution,
            project_dir=self.project_dir,
            session_id=self._session_id,
        )

        # --- Session Cost ---
        self._session_cost = SessionCost(
            session_id=self._session_id,
            model=model,
        )

        # --- Session State ---
        self._session_state = SessionState(
            session_id=self._session_id,
            project=os.path.basename(self.project_dir),
        )

        # --- Transcript Writer ---
        self._transcript_writer: TranscriptWriter | None = None
        if session_dir:
            transcript_path = str(
                Path(session_dir) / f"{self._session_id}-transcript.jsonl"
            )
            self._transcript_writer = TranscriptWriter(transcript_path)

        # --- LLM callback ---
        self._llm_callback: LLMCallback | None = llm_callback

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        """Unique session identifier."""
        return self._session_id

    @property
    def tool_registry(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._tool_registry

    @property
    def skill_registry(self) -> SkillRegistry:
        """Access the skill registry."""
        return self._skill_registry

    @property
    def prompt_registry(self) -> SystemPromptRegistry:
        """Access the system prompt registry."""
        return self._prompt_registry

    @property
    def token_budget(self) -> TokenBudget:
        """Access the token budget tracker."""
        return self._token_budget

    @property
    def auto_compactor(self) -> AutoCompactor:
        """Access the auto-compactor."""
        return self._auto_compactor

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Access the governance pipeline."""
        return self._pipeline

    @property
    def session_cost(self) -> SessionCost:
        """Access the session cost tracker."""
        return self._session_cost

    @property
    def session_state(self) -> SessionState:
        """Access the session state."""
        return self._session_state

    @property
    def constitution(self) -> Constitution:
        """Access the governance constitution."""
        return self._constitution

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def run(self, task: str) -> str:
        """Run the agent loop synchronously on a task.

        Parameters
        ----------
        task : str
            The user task / instruction to execute.

        Returns
        -------
        str
            The final text response from the agent.

        Raises
        ------
        RuntimeError
            If no LLM callback and no API key are available.
        """
        # Build system prompt
        system_prompt = self._prompt_registry.build_system_prompt()

        # Create initial messages
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": task},
        ]

        # Record task in session state
        self._session_state.in_progress.append(task[:200])

        # Log to transcript
        if self._transcript_writer:
            self._transcript_writer.append(
                {"role": "user", "content": task, "timestamp": time.time()}
            )

        # Get tool schemas for LLM
        tool_schemas = self._tool_registry.to_api_schemas()

        final_text = ""

        for iteration in range(self.max_iterations):
            # Step 1: Check if auto-compact needed
            estimated_tokens = estimate_message_tokens(messages)
            self._token_budget.record_usage(estimated_tokens, 0)

            if self._auto_compactor.should_compact(messages):
                logger.info("AgentLoop: triggering auto-compact at iteration %d", iteration)
                try:
                    messages, _summary = self._auto_compactor.compact(
                        messages,
                        summarizer=self._make_summarizer(system_prompt),
                    )
                    self._token_budget.reset()
                except Exception:
                    logger.warning("AgentLoop: auto-compact failed, continuing without compaction")

            # Step 2: Apply microcompact to old tool results
            messages = microcompact(messages, keep_recent=3)

            # Step 3: Call LLM
            max_output = get_max_output_tokens(self.model)
            response = self._call_llm(system_prompt, messages, tool_schemas, max_output)

            # Step 4: Extract response content
            content_blocks = response.get("content", [])
            stop_reason = response.get("stop_reason", "end_turn")
            usage = response.get("usage", {})

            # Record token usage
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            self._session_cost.record_turn(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read=usage.get("cache_read_input_tokens", 0),
                cache_write=usage.get("cache_creation_input_tokens", 0),
            )

            # Append assistant message to conversation
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content_blocks,
            }
            messages.append(assistant_msg)

            # Log to transcript
            if self._transcript_writer:
                self._transcript_writer.append(
                    {
                        "role": "assistant",
                        "content": content_blocks,
                        "timestamp": time.time(),
                        "usage": usage,
                    }
                )

            # Step 5: If stop_reason != "tool_use", we're done
            if stop_reason != "tool_use":
                # Extract final text
                final_text = self._extract_text(content_blocks)
                break

            # Step 6: Process tool_use blocks
            tool_results: list[dict[str, Any]] = []
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue

                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                tool_use_id = block.get("id", "unknown")

                # Step 6a: Run through governance pipeline
                tc = ToolCall(
                    tool_name=tool_name,
                    tool_input=tool_input if isinstance(tool_input, dict) else {},
                    metadata={"tool_use_id": tool_use_id},
                )
                decision = self._pipeline.evaluate(tc)

                if decision.action == "deny":
                    # Step 6c: Blocked - return synthetic error
                    logger.warning(
                        "AgentLoop: BLOCKED tool call %s: %s",
                        tool_name,
                        decision.reason,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": (
                            f"[AutoHarness] Tool call BLOCKED: {decision.reason}. "
                            f"Do not retry the same operation."
                        ),
                        "is_error": True,
                    })
                elif decision.action == "ask":
                    # For non-interactive, default to deny
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": (
                            f"[AutoHarness] Tool call requires confirmation: {decision.reason}. "
                            f"Confirmation not available in non-interactive mode."
                        ),
                        "is_error": True,
                    })
                else:
                    # Step 6b: Allowed - execute via orchestrator or tool registry
                    result = self._execute_tool(tool_name, tool_input, tool_use_id)
                    tool_results.append(result)

            # Append tool results to conversation
            user_msg: dict[str, Any] = {
                "role": "user",
                "content": tool_results,
            }
            messages.append(user_msg)

            # Log tool results to transcript
            if self._transcript_writer:
                self._transcript_writer.append(
                    {
                        "role": "user",
                        "content": tool_results,
                        "timestamp": time.time(),
                    }
                )
        else:
            # Exhausted max_iterations
            logger.warning(
                "AgentLoop: max iterations (%d) reached", self.max_iterations
            )
            final_text = self._extract_text(content_blocks)

        # Save session state
        self._session_state.status = "completed"
        if self.session_dir:
            save_session(self._session_state, self.session_dir)

        # Close transcript writer
        if self._transcript_writer:
            self._transcript_writer.close()

        return final_text

    async def arun(self, task: str) -> str:
        """Run the agent loop asynchronously.

        Currently wraps the synchronous :meth:`run` in an executor.
        A fully async implementation (with async LLM calls and async
        tool orchestration) is planned for a future release.

        Parameters
        ----------
        task : str
            The user task / instruction to execute.

        Returns
        -------
        str
            The final text response from the agent.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run, task)

    def step(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Execute a single agent step (for custom loops).

        Parameters
        ----------
        messages : list[dict]
            Current conversation messages (must include at least one
            user message).

        Returns
        -------
        tuple[list[dict], bool]
            Updated messages list and a boolean indicating whether the
            loop should continue (True = more steps needed, False = done).
        """
        system_prompt = self._prompt_registry.build_system_prompt()
        tool_schemas = self._tool_registry.to_api_schemas()
        max_output = get_max_output_tokens(self.model)

        # Call LLM
        response = self._call_llm(system_prompt, messages, tool_schemas, max_output)
        content_blocks = response.get("content", [])
        stop_reason = response.get("stop_reason", "end_turn")
        usage = response.get("usage", {})

        # Record usage
        self._session_cost.record_turn(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

        # Append assistant response
        messages = list(messages)
        messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason != "tool_use":
            return messages, False

        # Process tool calls
        tool_results: list[dict[str, Any]] = []
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue

            tool_name = block.get("name", "unknown")
            tool_input = block.get("input", {})
            tool_use_id = block.get("id", "unknown")

            tc = ToolCall(
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {},
                metadata={"tool_use_id": tool_use_id},
            )
            decision = self._pipeline.evaluate(tc)

            if decision.action == "deny":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": f"[AutoHarness] BLOCKED: {decision.reason}",
                    "is_error": True,
                })
            else:
                result = self._execute_tool(tool_name, tool_input, tool_use_id)
                tool_results.append(result)

        messages.append({"role": "user", "content": tool_results})
        return messages, True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_constitution(
        self,
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
            f"constitution must be a path, dict, Constitution, or None; "
            f"got {type(constitution).__name__}"
        )

    def _load_skills(self, skills_dir: str | None) -> None:
        """Discover and load skills into the registry."""
        try:
            load_skills_into_registry(
                self._skill_registry,
                project_dir=skills_dir,
            )
        except Exception:
            logger.debug("AgentLoop: no skills loaded (skills_dir=%s)", skills_dir)

    def _register_default_prompt_sections(self) -> None:
        """Register default system prompt sections."""
        # Static: identity section
        self._prompt_registry.register_static(
            system_prompt_section(
                "identity",
                lambda: (
                    "You are an AI agent powered by AutoHarness governance. "
                    "Your tool calls are governed by a constitution that enforces "
                    "safety rules. Blocked tool calls will return error messages."
                ),
            )
        )

        # Static: governance rules summary
        constitution = self._constitution
        self._prompt_registry.register_static(
            system_prompt_section(
                "governance",
                lambda: self._build_governance_summary(constitution),
            )
        )

        # Dynamic: skill descriptions (changes when skills are loaded)
        skill_registry = self._skill_registry
        self._prompt_registry.register_dynamic(
            uncached_section(
                "skills",
                lambda: skill_registry.get_prompt_descriptions() or None,
                reason="Skill list may change between turns",
            )
        )

        # Dynamic: tool prompts
        tool_registry = self._tool_registry
        self._prompt_registry.register_dynamic(
            uncached_section(
                "tool_instructions",
                lambda: self._build_tool_prompts(tool_registry) or None,
                reason="Tool availability may change",
            )
        )

    def _build_governance_summary(self, constitution: Constitution) -> str:
        """Build a governance rules summary for the system prompt."""
        rules = constitution.rules
        if not rules:
            return "Default safety rules are active."
        lines = ["The following governance rules are enforced:"]
        for rule in rules:
            severity = (
                f"[{rule.severity.value.upper()}]"
                if hasattr(rule, "severity") and rule.severity
                else ""
            )
            lines.append(f"- {severity} {rule.description}")
        return "\n".join(lines)

    def _build_tool_prompts(self, tool_registry: ToolRegistry) -> str:
        """Collect tool prompt contributions."""
        prompts = tool_registry.get_tool_prompts()
        if not prompts:
            return ""
        lines = ["# Tool Instructions"]
        for name, prompt in sorted(prompts.items()):
            if prompt:
                lines.append(f"## {name}")
                lines.append(prompt)
        return "\n\n".join(lines) if len(lines) > 1 else ""

    def _call_llm(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Call the LLM via callback or built-in Anthropic client.

        Returns a response dict with ``content``, ``stop_reason``, and ``usage`` keys.
        """
        if self._llm_callback is not None:
            return self._llm_callback(self.model, messages, tools, max_tokens)

        if not self.api_key:
            raise RuntimeError(
                "No LLM callback and no API key provided. "
                "Either pass api_key, set ANTHROPIC_API_KEY, or provide llm_callback."
            )

        # Use Anthropic SDK
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The anthropic package is required for direct API calls. "
                "Install it with: pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)

        # Convert Anthropic response to our dict format
        content_blocks: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                content_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        usage_dict: dict[str, int] = {}
        if hasattr(response, "usage") and response.usage:
            usage_dict["input_tokens"] = getattr(response.usage, "input_tokens", 0)
            usage_dict["output_tokens"] = getattr(response.usage, "output_tokens", 0)
            usage_dict["cache_read_input_tokens"] = getattr(
                response.usage, "cache_read_input_tokens", 0
            )
            usage_dict["cache_creation_input_tokens"] = getattr(
                response.usage, "cache_creation_input_tokens", 0
            )

        return {
            "content": content_blocks,
            "stop_reason": response.stop_reason,
            "usage": usage_dict,
        }

    def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        """Execute a tool via the registry.

        Returns an Anthropic-style tool_result dict.
        """
        tool_def = self._tool_registry.get(tool_name)
        if tool_def is None or tool_def.execute is None:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": (
                    f"Tool '{tool_name}' passed governance but has no executor. "
                    f"Register a tool with an execute callback to run it."
                ),
            }

        try:
            result = tool_def.execute(**tool_input)
            content = result if isinstance(result, str) else json.dumps(result, default=str)
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
        except Exception as exc:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"Error executing {tool_name}: {exc}",
                "is_error": True,
            }

    def _extract_text(self, content_blocks: list[Any]) -> str:
        """Extract text from content blocks."""
        parts: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)

    def _make_summarizer(self, system_prompt: str) -> Callable[[str], str]:
        """Create a summarizer callback for auto-compaction."""

        def summarizer(prompt: str) -> str:
            response = self._call_llm(
                system_prompt="You are a conversation summarizer.",
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                max_tokens=20_000,
            )
            return self._extract_text(response.get("content", []))

        return summarizer

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<AgentLoop model={self.model!r} session={self._session_id!r} "
            f"tools={len(self._tool_registry)} skills={len(self._skill_registry)}>"
        )
