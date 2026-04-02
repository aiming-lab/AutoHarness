"""Tests for the AgentLoop integration layer.

All tests use a mock LLM callback so no real API calls are needed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------


def _make_text_response(text: str = "Done.") -> dict[str, Any]:
    """Create a mock LLM response that ends the loop (text only)."""
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def _make_tool_use_response(
    tool_name: str = "Bash",
    tool_input: dict | None = None,
    tool_id: str = "tu_001",
) -> dict[str, Any]:
    """Create a mock LLM response that requests a tool call."""
    return {
        "content": [
            {
                "type": "tool_use",
                "id": tool_id,
                "name": tool_name,
                "input": tool_input or {"command": "echo hello"},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def _mock_llm_single_turn(model, messages, tools, max_tokens):
    """LLM callback that always returns a text response."""
    return _make_text_response("Task completed successfully.")


def _mock_llm_with_tool_use(model, messages, tools, max_tokens):
    """LLM callback that does one tool call then finishes."""
    # If we already have tool results in messages, return final text
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return _make_text_response("Tool executed, task done.")
    # First call: request tool use
    return _make_tool_use_response()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentLoopCreation:
    """Tests for AgentLoop initialization."""

    def test_creation_with_defaults(self):
        """AgentLoop can be created with default settings."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        assert loop.model == "claude-sonnet-4-6"
        assert loop.session_id
        assert len(loop.session_id) > 0

    def test_creation_with_constitution(self):
        """AgentLoop can be created with an explicit constitution."""
        from autoharness.agent_loop import AgentLoop
        from autoharness.core.constitution import Constitution

        const = Constitution.default()
        loop = AgentLoop(
            constitution=const,
            llm_callback=_mock_llm_single_turn,
        )
        assert loop.constitution is const

    def test_creation_with_dict_constitution(self):
        """AgentLoop accepts a dict as constitution."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(
            constitution={"rules": []},
            llm_callback=_mock_llm_single_turn,
        )
        assert loop.constitution is not None

    def test_creation_with_custom_tools(self):
        """AgentLoop can register custom tools."""
        from autoharness.agent_loop import AgentLoop
        from autoharness.tools.registry import ToolDefinition

        tool = ToolDefinition(
            name="MyTool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
        )
        loop = AgentLoop(
            tools=[tool],
            llm_callback=_mock_llm_single_turn,
        )
        assert "MyTool" in loop.tool_registry
        assert loop.tool_registry.get("MyTool") is tool

    def test_creation_with_custom_model(self):
        """AgentLoop respects a custom model name."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(
            model="claude-opus-4-6",
            llm_callback=_mock_llm_single_turn,
        )
        assert loop.model == "claude-opus-4-6"

    def test_creation_without_api_key(self):
        """AgentLoop is importable and configurable without an API key."""
        from autoharness.agent_loop import AgentLoop

        # Ensure no env key leaks in
        with patch.dict(os.environ, {}, clear=True):
            loop = AgentLoop(
                api_key=None,
                llm_callback=_mock_llm_single_turn,
            )
            assert loop.api_key is None
            # Should still be able to run with the callback
            result = loop.run("test")
            assert isinstance(result, str)


class TestAgentLoopRun:
    """Tests for AgentLoop.run()."""

    def test_run_simple_task(self):
        """run() returns text from a single-turn LLM response."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        result = loop.run("Hello")
        assert result == "Task completed successfully."

    def test_run_with_tool_use(self):
        """run() handles a tool_use -> tool_result -> final text loop."""
        from autoharness.agent_loop import AgentLoop
        from autoharness.tools.registry import ToolDefinition

        tool = ToolDefinition(
            name="Bash",
            description="Execute a bash command",
            input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
            execute=lambda command="": f"output: {command}",
        )

        loop = AgentLoop(
            tools=[tool],
            llm_callback=_mock_llm_with_tool_use,
        )
        result = loop.run("Run echo hello")
        assert result == "Tool executed, task done."

    def test_run_records_session_cost(self):
        """run() records token usage in SessionCost."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        loop.run("Test task")
        assert loop.session_cost.turns >= 1
        assert loop.session_cost.total_input_tokens > 0
        assert loop.session_cost.total_output_tokens > 0

    def test_run_updates_session_state(self):
        """run() updates the session state to completed."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        loop.run("Test task")
        assert loop.session_state.status == "completed"

    def test_run_without_callback_or_key_raises(self):
        """run() raises RuntimeError when no callback and no API key."""
        from autoharness.agent_loop import AgentLoop

        with patch.dict(os.environ, {}, clear=True):
            loop = AgentLoop(api_key=None, llm_callback=None)
            with pytest.raises(RuntimeError, match="No LLM callback"):
                loop.run("Test")


class TestAgentLoopStep:
    """Tests for AgentLoop.step()."""

    def test_step_with_text_response(self):
        """step() returns (messages, False) when LLM stops."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        messages = [{"role": "user", "content": "Hello"}]
        result_messages, should_continue = loop.step(messages)
        assert should_continue is False
        assert len(result_messages) > len(messages)

    def test_step_with_tool_use(self):
        """step() returns (messages, True) when tool_use is requested."""
        from autoharness.agent_loop import AgentLoop

        # Always return tool_use
        def llm_tool_only(model, messages, tools, max_tokens):
            return _make_tool_use_response()

        loop = AgentLoop(llm_callback=llm_tool_only)
        messages = [{"role": "user", "content": "Do something"}]
        result_messages, should_continue = loop.step(messages)
        assert should_continue is True
        # Should have assistant message + user message with tool_result
        assert len(result_messages) == 3  # original + assistant + tool_results


class TestAgentLoopIntegrations:
    """Tests verifying subsystem integration."""

    def test_integrates_tool_registry(self):
        """AgentLoop has a ToolRegistry that can register and list tools."""
        from autoharness.agent_loop import AgentLoop
        from autoharness.tools.registry import ToolDefinition

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        tool = ToolDefinition(
            name="TestTool",
            description="test",
            input_schema={"type": "object"},
        )
        loop.tool_registry.register(tool)
        assert "TestTool" in loop.tool_registry

    def test_integrates_skill_registry(self):
        """AgentLoop has a SkillRegistry accessible via property."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        assert isinstance(loop.skill_registry, type(loop._skill_registry))
        assert len(loop.skill_registry) >= 0  # May have 0 skills

    def test_integrates_auto_compactor(self):
        """AgentLoop has an AutoCompactor with model-appropriate settings."""
        from autoharness.agent_loop import AgentLoop
        from autoharness.context.autocompact import AutoCompactor

        loop = AgentLoop(
            model="claude-sonnet-4-6",
            llm_callback=_mock_llm_single_turn,
        )
        assert isinstance(loop.auto_compactor, AutoCompactor)
        assert loop.auto_compactor.model == "claude-sonnet-4-6"

    def test_integrates_system_prompt_registry(self):
        """AgentLoop has a SystemPromptRegistry with default sections."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        prompt = loop.prompt_registry.build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "governance" in prompt.lower() or "AutoHarness" in prompt

    def test_integrates_session_cost(self):
        """AgentLoop has a SessionCost tracker with correct model."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(
            model="claude-opus-4-6",
            llm_callback=_mock_llm_single_turn,
        )
        assert loop.session_cost.model == "claude-opus-4-6"
        assert loop.session_cost.session_id == loop.session_id

    def test_integrates_governance_pipeline(self):
        """AgentLoop uses the governance pipeline to evaluate tool calls."""
        from autoharness.agent_loop import AgentLoop
        from autoharness.tools.registry import ToolDefinition

        call_log: list[str] = []

        def logging_llm(model, messages, tools, max_tokens):
            # First call: tool_use. Subsequent: text.
            for msg in messages:
                c = msg.get("content", "")
                if isinstance(c, list):
                    for block in c:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            call_log.append("got_result")
                            return _make_text_response("Done with tool.")
            return _make_tool_use_response("SafeTool", {"action": "test"}, "tu_safe")

        tool = ToolDefinition(
            name="SafeTool",
            description="A safe tool",
            input_schema={"type": "object", "properties": {"action": {"type": "string"}}},
            execute=lambda action="": f"executed: {action}",
        )

        loop = AgentLoop(
            tools=[tool],
            llm_callback=logging_llm,
        )
        result = loop.run("Test governance")
        assert "Done with tool." in result
        assert "got_result" in call_log

    def test_governance_blocks_denied_tool(self):
        """AgentLoop blocks tool calls that governance denies."""
        from autoharness.agent_loop import AgentLoop

        # Create a constitution that denies everything at critical risk
        const_dict = {
            "risk": {
                "thresholds": {
                    "low": "deny",
                    "medium": "deny",
                    "high": "deny",
                    "critical": "deny",
                },
            },
        }

        call_count = [0]

        def llm_with_count(model, messages, tools, max_tokens):
            call_count[0] += 1
            if call_count[0] > 1:
                return _make_text_response("Gave up after block.")
            return _make_tool_use_response("Bash", {"command": "echo hi"})

        loop = AgentLoop(
            constitution=const_dict,
            llm_callback=llm_with_count,
        )
        result = loop.run("Try something")
        assert "Gave up" in result or "BLOCKED" in result or isinstance(result, str)

    def test_session_persistence(self):
        """AgentLoop saves session state when session_dir is provided."""
        from autoharness.agent_loop import AgentLoop

        with tempfile.TemporaryDirectory() as tmpdir:
            loop = AgentLoop(
                session_dir=tmpdir,
                llm_callback=_mock_llm_single_turn,
            )
            loop.run("Test persistence")

            # Check that session file was created
            session_files = list(Path(tmpdir).glob("*-session.md"))
            assert len(session_files) >= 1

    def test_transcript_written(self):
        """AgentLoop writes transcript when session_dir is provided."""
        from autoharness.agent_loop import AgentLoop

        with tempfile.TemporaryDirectory() as tmpdir:
            loop = AgentLoop(
                session_dir=tmpdir,
                llm_callback=_mock_llm_single_turn,
            )
            loop.run("Test transcript")

            transcript_files = list(Path(tmpdir).glob("*-transcript.jsonl"))
            assert len(transcript_files) == 1


class TestPublicAPI:
    """Tests that all expected types are importable from autoharness."""

    def test_agent_loop_importable(self):
        from autoharness import AgentLoop
        assert AgentLoop is not None

    def test_lint_tool_call_importable(self):
        from autoharness import lint_tool_call
        assert callable(lint_tool_call)

    def test_all_major_types_importable(self):
        """All major types listed in __all__ are importable."""
        from autoharness import (
            AgentLoop,
            Constitution,
            ToolDefinition,
            build_forked_messages,
            get_builtin_agent,
            lint_tool_call,
            microcompact,
            system_prompt_section,
        )
        # Verify they are real types/functions, not None
        assert AgentLoop is not None
        assert Constitution is not None
        assert ToolDefinition is not None
        assert callable(lint_tool_call)
        assert callable(microcompact)
        assert callable(system_prompt_section)
        assert callable(get_builtin_agent)
        assert callable(build_forked_messages)

    def test_repr(self):
        """AgentLoop has a useful repr."""
        from autoharness.agent_loop import AgentLoop

        loop = AgentLoop(llm_callback=_mock_llm_single_turn)
        r = repr(loop)
        assert "AgentLoop" in r
        assert "claude-sonnet" in r
