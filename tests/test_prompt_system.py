"""Tests for the system prompt architecture (Phase 2).

Covers: section registry, caching, context management, cache break detection,
MCP delta injection, and tool prompt building.
"""

from __future__ import annotations

import pytest

from autoharness.prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    CacheBreakDetector,
    ContextManager,
    McpInstructionManager,
    SystemPromptRegistry,
    build_tool_prompt_section,
    system_prompt_section,
    uncached_section,
)

# ======================================================================
# Section Registration
# ======================================================================


class TestSectionRegistration:
    """Tests for static and dynamic section registration."""

    def test_register_static_section(self) -> None:
        registry = SystemPromptRegistry()
        section = system_prompt_section("identity", lambda: "You are a helpful agent.")
        registry.register_static(section)
        parts = registry.resolve_static_prefix()
        assert parts == ["You are a helpful agent."]

    def test_register_dynamic_section(self) -> None:
        registry = SystemPromptRegistry()
        section = system_prompt_section("date", lambda: "Today is 2026-03-31.")
        registry.register_dynamic(section)
        parts = registry.resolve_dynamic_suffix()
        assert parts == ["Today is 2026-03-31."]

    def test_duplicate_name_rejected_static(self) -> None:
        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("dup", lambda: "a"))
        with pytest.raises(ValueError, match="Duplicate section name: dup"):
            registry.register_static(system_prompt_section("dup", lambda: "b"))

    def test_duplicate_name_rejected_cross(self) -> None:
        """A name used in static cannot be reused in dynamic."""
        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("shared", lambda: "a"))
        with pytest.raises(ValueError, match="Duplicate section name: shared"):
            registry.register_dynamic(system_prompt_section("shared", lambda: "b"))

    def test_none_sections_excluded(self) -> None:
        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("empty", lambda: None))
        registry.register_static(system_prompt_section("present", lambda: "Hello"))
        parts = registry.resolve_static_prefix()
        assert parts == ["Hello"]


# ======================================================================
# Cache Behavior
# ======================================================================


class TestCacheBehavior:
    """Tests for static caching and dynamic recomputation."""

    def test_static_sections_cached(self) -> None:
        call_count = 0

        def expensive():
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("cached", expensive))

        # First resolve
        parts1 = registry.resolve_static_prefix()
        assert parts1 == ["result-1"]
        assert call_count == 1

        # Second resolve should use cache
        parts2 = registry.resolve_static_prefix()
        assert parts2 == ["result-1"]
        assert call_count == 1  # Not called again

    def test_dynamic_sections_recomputed(self) -> None:
        call_count = 0

        def changing():
            nonlocal call_count
            call_count += 1
            return f"value-{call_count}"

        registry = SystemPromptRegistry()
        registry.register_dynamic(system_prompt_section("dynamic", changing))

        parts1 = registry.resolve_dynamic_suffix()
        assert parts1 == ["value-1"]

        parts2 = registry.resolve_dynamic_suffix()
        assert parts2 == ["value-2"]
        assert call_count == 2

    def test_uncached_section_always_recomputed(self) -> None:
        call_count = 0

        def volatile():
            nonlocal call_count
            call_count += 1
            return f"v{call_count}"

        registry = SystemPromptRegistry()
        section = uncached_section("volatile", volatile, reason="changes every turn")
        registry.register_static(section)

        registry.resolve_static_prefix()
        registry.resolve_static_prefix()
        assert call_count == 2

    def test_clear_cache_forces_recomputation(self) -> None:
        call_count = 0

        def compute():
            nonlocal call_count
            call_count += 1
            return f"v{call_count}"

        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("cached", compute))

        registry.resolve_static_prefix()
        assert call_count == 1

        registry.clear_cache()
        parts = registry.resolve_static_prefix()
        assert parts == ["v2"]
        assert call_count == 2


# ======================================================================
# resolve_all and build_system_prompt
# ======================================================================


class TestResolveAll:
    """Tests for resolve_all() and build_system_prompt()."""

    def test_resolve_all_includes_boundary(self) -> None:
        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("s", lambda: "static"))
        registry.register_dynamic(system_prompt_section("d", lambda: "dynamic"))

        parts = registry.resolve_all()
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in parts
        idx = parts.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        assert parts[:idx] == ["static"]
        assert parts[idx + 1 :] == ["dynamic"]

    def test_build_system_prompt_excludes_boundary(self) -> None:
        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("s", lambda: "static part"))
        registry.register_dynamic(system_prompt_section("d", lambda: "dynamic part"))

        prompt = registry.build_system_prompt()
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in prompt
        assert "static part" in prompt
        assert "dynamic part" in prompt

    def test_build_system_prompt_joins_with_double_newline(self) -> None:
        registry = SystemPromptRegistry()
        registry.register_static(system_prompt_section("a", lambda: "A"))
        registry.register_dynamic(system_prompt_section("b", lambda: "B"))

        prompt = registry.build_system_prompt()
        assert prompt == "A\n\nB"

    def test_exception_in_section_returns_none(self) -> None:
        """A section that raises is treated as None (skipped)."""
        registry = SystemPromptRegistry()
        registry.register_static(
            system_prompt_section("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))  # type: ignore[arg-type,union-attr]
        )
        registry.register_static(system_prompt_section("good", lambda: "ok"))

        # Should not raise, just skip the bad section
        parts = registry.resolve_static_prefix()
        assert parts == ["ok"]


# ======================================================================
# build_tool_prompt_section
# ======================================================================


class TestToolPromptSection:
    """Tests for build_tool_prompt_section helper."""

    def test_empty_dict(self) -> None:
        assert build_tool_prompt_section({}) == ""

    def test_single_tool(self) -> None:
        result = build_tool_prompt_section({"bash": "Use bash for commands."})
        assert "# Tool Instructions" in result
        assert "## bash" in result
        assert "Use bash for commands." in result

    def test_empty_prompt_excluded(self) -> None:
        result = build_tool_prompt_section({"bash": "", "read": "Read files."})
        assert "## bash" not in result
        assert "## read" in result

    def test_tools_sorted(self) -> None:
        result = build_tool_prompt_section({"z_tool": "Z", "a_tool": "A"})
        assert result.index("a_tool") < result.index("z_tool")


# ======================================================================
# ContextManager
# ======================================================================


class TestContextManager:
    """Tests for user/system context separation and caching."""

    def test_user_context_cached(self) -> None:
        cm = ContextManager()
        call_count = 0

        def loader():
            nonlocal call_count
            call_count += 1
            return f"user-{call_count}"

        assert cm.get_user_context(loader) == "user-1"
        assert cm.get_user_context(loader) == "user-1"
        assert call_count == 1

    def test_system_context_cached(self) -> None:
        cm = ContextManager()
        call_count = 0

        def loader():
            nonlocal call_count
            call_count += 1
            return f"sys-{call_count}"

        assert cm.get_system_context(loader) == "sys-1"
        assert cm.get_system_context(loader) == "sys-1"
        assert call_count == 1

    def test_set_injection_invalidates_both(self) -> None:
        cm = ContextManager()
        cm.get_user_context(lambda: "u1")
        cm.get_system_context(lambda: "s1")

        cm.set_injection("debug")
        assert cm.injection == "debug"

        # After injection, caches are invalidated
        assert cm.get_user_context(lambda: "u2") == "u2"
        assert cm.get_system_context(lambda: "s2") == "s2"

    def test_invalidate_clears_caches(self) -> None:
        cm = ContextManager()
        cm.get_user_context(lambda: "old")
        cm.invalidate()
        assert cm.get_user_context(lambda: "new") == "new"


# ======================================================================
# CacheBreakDetector
# ======================================================================


class TestCacheBreakDetector:
    """Tests for prompt cache break detection."""

    def test_first_check_no_break(self) -> None:
        detector = CacheBreakDetector()
        assert detector.check("prompt v1") is False
        assert detector.break_count == 0

    def test_same_prompt_no_break(self) -> None:
        detector = CacheBreakDetector()
        detector.check("same")
        assert detector.check("same") is False
        assert detector.break_count == 0

    def test_changed_prompt_breaks(self) -> None:
        detector = CacheBreakDetector()
        detector.check("v1")
        assert detector.check("v2") is True
        assert detector.break_count == 1

    def test_multiple_breaks_counted(self) -> None:
        detector = CacheBreakDetector()
        detector.check("a")
        detector.check("b")
        detector.check("c")
        assert detector.break_count == 2

    def test_notify_compaction_increments(self) -> None:
        detector = CacheBreakDetector()
        assert detector.break_count == 0
        detector.notify_compaction()
        assert detector.break_count == 1


# ======================================================================
# McpInstructionManager
# ======================================================================


class TestMcpInstructionManager:
    """Tests for MCP instruction delta injection."""

    def test_initial_update_returns_delta(self) -> None:
        mgr = McpInstructionManager()
        delta = mgr.update_servers({"slack": "Use Slack to send messages."})
        assert delta is not None
        assert "slack" in delta
        assert "connected" in delta

    def test_no_change_returns_none(self) -> None:
        mgr = McpInstructionManager()
        mgr.update_servers({"slack": "inst"})
        assert mgr.update_servers({"slack": "inst"}) is None

    def test_added_server_in_delta(self) -> None:
        mgr = McpInstructionManager()
        mgr.update_servers({"a": "A"})
        delta = mgr.update_servers({"a": "A", "b": "B"})
        assert delta is not None
        assert "b" in delta
        assert "connected" in delta

    def test_removed_server_in_delta(self) -> None:
        mgr = McpInstructionManager()
        mgr.update_servers({"a": "A", "b": "B"})
        delta = mgr.update_servers({"a": "A"})
        assert delta is not None
        assert "b" in delta
        assert "disconnected" in delta

    def test_get_full_instructions_empty(self) -> None:
        mgr = McpInstructionManager()
        assert mgr.get_full_instructions() == ""

    def test_get_full_instructions_with_servers(self) -> None:
        mgr = McpInstructionManager()
        mgr.update_servers({"github": "Use GH API.", "slack": "Send messages."})
        full = mgr.get_full_instructions()
        assert "# MCP Server Instructions" in full
        assert "## github" in full
        assert "## slack" in full
        assert "Use GH API." in full

    def test_empty_instruction_not_included(self) -> None:
        mgr = McpInstructionManager()
        mgr.update_servers({"tool": ""})
        full = mgr.get_full_instructions()
        assert "## tool" in full
        # Empty instruction means the header is there but no body line after it
        lines = full.split("\n\n")
        # Should have header and the tool section header only
        assert len(lines) == 2
