"""Tests for the Tool System (Phase 3).

Covers: ToolDefinition, ToolRegistry, ToolOrchestrator, OutputBudgetManager,
ToolSearch, ToolMatcher, and SpeculativeClassifier.
"""
from __future__ import annotations

import pytest

from autoharness.tools.matcher import ToolMatcher
from autoharness.tools.orchestrator import ToolOrchestrator
from autoharness.tools.output_budget import OutputBudgetManager
from autoharness.tools.registry import ToolDefinition, ToolRegistry
from autoharness.tools.search import ToolSearch
from autoharness.tools.speculative import SpeculativeClassifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(name: str = "TestTool", **kwargs) -> ToolDefinition:
    defaults = {
        "description": f"A test tool called {name}",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    }
    defaults.update(kwargs)
    return ToolDefinition(name=name, **defaults)


# ---------------------------------------------------------------------------
# ToolDefinition tests
# ---------------------------------------------------------------------------

class TestToolDefinition:
    def test_creation_defaults(self):
        td = _make_tool()
        assert td.name == "TestTool"
        assert td.is_read_only is False
        assert td.is_concurrency_safe is False
        assert td.is_destructive is False
        assert td.should_defer is False
        assert td.always_load is False
        assert td.max_result_size_chars == 50_000
        assert td.source == "builtin"
        assert td.enabled is True
        assert td.aliases == []

    def test_to_api_schema(self):
        td = _make_tool(name="Bash", description="Run commands")
        schema = td.to_api_schema()
        assert schema["name"] == "Bash"
        assert schema["description"] == "Run commands"
        assert "input_schema" in schema
        # Should not include internal fields
        assert "is_read_only" not in schema
        assert "source" not in schema

    def test_prompt_none_by_default(self):
        td = _make_tool()
        assert td.prompt() is None

    def test_prompt_with_callback(self):
        td = _make_tool(prompt_fn=lambda: "Use this tool carefully.")
        assert td.prompt() == "Use this tool carefully."


# ---------------------------------------------------------------------------
# ToolRegistry tests
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _make_tool("Read")
        reg.register(tool)
        assert reg.get("Read") is tool
        assert len(reg) == 1

    def test_get_by_alias(self):
        reg = ToolRegistry()
        tool = _make_tool("Bash", aliases=["sh", "shell"])
        reg.register(tool)
        assert reg.get("sh") is tool
        assert reg.get("shell") is tool

    def test_get_missing_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("NonExistent") is None

    def test_duplicate_name_raises(self):
        reg = ToolRegistry()
        reg.register(_make_tool("Bash"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_make_tool("Bash"))

    def test_unregister(self):
        reg = ToolRegistry()
        tool = _make_tool("Edit", aliases=["e"])
        reg.register(tool)
        assert "Edit" in reg
        assert "e" in reg
        reg.unregister("Edit")
        assert "Edit" not in reg
        assert "e" not in reg
        assert len(reg) == 0

    def test_unregister_nonexistent_is_noop(self):
        reg = ToolRegistry()
        reg.unregister("Ghost")  # Should not raise

    def test_list_all(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A"))
        reg.register(_make_tool("B", enabled=False))
        assert len(reg.list_all()) == 2

    def test_list_enabled(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A"))
        reg.register(_make_tool("B", enabled=False))
        enabled = reg.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "A"

    def test_list_deferred(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A", should_defer=False))
        reg.register(_make_tool("B", should_defer=True))
        reg.register(_make_tool("C", should_defer=True, enabled=False))
        deferred = reg.list_deferred()
        assert len(deferred) == 1
        assert deferred[0].name == "B"

    def test_list_immediate(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A", should_defer=False))
        reg.register(_make_tool("B", should_defer=True))
        reg.register(_make_tool("C", should_defer=True, always_load=True))
        immediate = reg.list_immediate()
        names = {t.name for t in immediate}
        assert "A" in names
        assert "B" not in names
        assert "C" in names

    def test_to_api_schemas_excludes_deferred(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A"))
        reg.register(_make_tool("B", should_defer=True))
        schemas = reg.to_api_schemas(include_deferred=False)
        assert len(schemas) == 1
        assert schemas[0]["name"] == "A"

    def test_to_api_schemas_includes_deferred(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A"))
        reg.register(_make_tool("B", should_defer=True))
        schemas = reg.to_api_schemas(include_deferred=True)
        assert len(schemas) == 2

    def test_get_tool_prompts(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A", prompt_fn=lambda: "prompt A"))
        reg.register(_make_tool("B"))  # no prompt
        reg.register(_make_tool("C", prompt_fn=lambda: "prompt C", enabled=False))
        prompts = reg.get_tool_prompts()
        assert prompts == {"A": "prompt A"}

    def test_contains(self):
        reg = ToolRegistry()
        reg.register(_make_tool("X", aliases=["y"]))
        assert "X" in reg
        assert "y" in reg
        assert "z" not in reg


# ---------------------------------------------------------------------------
# ToolOrchestrator tests
# ---------------------------------------------------------------------------

class TestToolOrchestratorSync:
    def test_sync_batch_empty(self):
        orch = ToolOrchestrator()
        assert orch.execute_batch_sync([], lambda n, d: {}) == []

    def test_sync_batch_executes_all(self):
        calls = [
            {"name": "Read", "id": "1", "input": {"path": "/a"}},
            {"name": "Write", "id": "2", "input": {"path": "/b"}},
        ]
        results = []
        def executor(name, data):
            result = {"tool": name, "ok": True}
            results.append(result)
            return result

        orch = ToolOrchestrator()
        out = orch.execute_batch_sync(calls, executor)
        assert len(out) == 2
        assert out[0]["tool"] == "Read"
        assert out[1]["tool"] == "Write"

    def test_sync_batch_handles_errors(self):
        calls = [{"name": "Fail", "id": "1", "input": {}}]
        def executor(name, data):
            raise RuntimeError("boom")

        orch = ToolOrchestrator()
        out = orch.execute_batch_sync(calls, executor)
        assert len(out) == 1
        assert out[0]["is_error"] is True
        assert "boom" in out[0]["content"]


class TestToolOrchestratorAsync:
    @pytest.mark.asyncio
    async def test_async_batch_empty(self):
        orch = ToolOrchestrator()
        async def executor(name, data):
            return {}
        result = await orch.execute_batch([], executor)
        assert result == []

    @pytest.mark.asyncio
    async def test_async_batch_concurrent_safe(self):
        reg = ToolRegistry()
        reg.register(_make_tool("SafeTool", is_concurrency_safe=True))

        execution_order = []
        async def executor(name, data):
            execution_order.append(name)
            return {"tool": name, "ok": True}

        calls = [
            {"name": "SafeTool", "id": "1", "input": {}},
            {"name": "SafeTool", "id": "2", "input": {}},
        ]
        orch = ToolOrchestrator(registry=reg)
        out = await orch.execute_batch(calls, executor)
        assert len(out) == 2
        assert all(r["ok"] for r in out)

    @pytest.mark.asyncio
    async def test_async_batch_error_handling(self):
        async def executor(name, data):
            raise ValueError("async boom")

        calls = [{"name": "X", "id": "42", "input": {}}]
        orch = ToolOrchestrator()
        out = await orch.execute_batch(calls, executor)
        assert len(out) == 1
        assert out[0]["is_error"] is True
        assert "async boom" in out[0]["content"]


# ---------------------------------------------------------------------------
# OutputBudgetManager tests
# ---------------------------------------------------------------------------

class TestOutputBudgetManager:
    def test_within_budget_returns_unchanged(self):
        mgr = OutputBudgetManager()
        output = "short output"
        result = mgr.apply_budget("Read", "id1", output, max_size=1000)
        assert result == output

    def test_exceeds_budget_truncates_and_persists(self, tmp_path):
        mgr = OutputBudgetManager(storage_dir=str(tmp_path / "outputs"))
        big_output = "x" * 200
        result = mgr.apply_budget("Read", "id2", big_output, max_size=50)
        assert len(result) < len(big_output) + 200  # truncated + footer
        assert "Output truncated" in result
        assert "200 chars total" in result
        # Verify file was persisted
        persisted = (tmp_path / "outputs" / "id2.txt").read_text()
        assert persisted == big_output

    def test_exact_budget_returns_unchanged(self):
        mgr = OutputBudgetManager()
        output = "a" * 100
        result = mgr.apply_budget("Read", "id3", output, max_size=100)
        assert result == output


# ---------------------------------------------------------------------------
# ToolSearch tests
# ---------------------------------------------------------------------------

class TestToolSearch:
    def test_search_no_registry(self):
        ts = ToolSearch(registry=None)
        assert ts.search("anything") == []

    def test_search_no_deferred_tools(self):
        reg = ToolRegistry()
        reg.register(_make_tool("A", should_defer=False))
        ts = ToolSearch(registry=reg)
        assert ts.search("test") == []

    def test_search_by_name(self):
        reg = ToolRegistry()
        reg.register(_make_tool("FileSearch", should_defer=True, description="Find files"))
        reg.register(_make_tool("WebSearch", should_defer=True, description="Search the web"))
        ts = ToolSearch(registry=reg)
        results = ts.search("file")
        assert len(results) >= 1
        assert results[0]["name"] == "FileSearch"

    def test_search_by_hint(self):
        reg = ToolRegistry()
        reg.register(_make_tool(
            "NotebookEdit",
            should_defer=True,
            description="Edit notebooks",
            search_hint="jupyter notebook cell editing",
        ))
        ts = ToolSearch(registry=reg)
        results = ts.search("jupyter")
        assert len(results) == 1
        assert results[0]["name"] == "NotebookEdit"

    def test_search_max_results(self):
        reg = ToolRegistry()
        for i in range(10):
            reg.register(_make_tool(f"Tool{i}", should_defer=True, description="a test tool"))
        ts = ToolSearch(registry=reg)
        results = ts.search("test", max_results=3)
        assert len(results) == 3

    def test_search_by_alias(self):
        reg = ToolRegistry()
        reg.register(_make_tool(
            "CodeGrep",
            should_defer=True,
            description="Search code",
            aliases=["rg", "ripgrep"],
        ))
        ts = ToolSearch(registry=reg)
        results = ts.search("ripgrep")
        assert len(results) == 1
        assert results[0]["name"] == "CodeGrep"

    def test_invalidate_cache(self):
        ts = ToolSearch()
        ts._description_cache["foo"] = "bar"
        ts.invalidate_cache()
        assert ts._description_cache == {}


# ---------------------------------------------------------------------------
# ToolMatcher tests
# ---------------------------------------------------------------------------

class TestToolMatcher:
    def test_wildcard_matches_everything(self):
        m = ToolMatcher("*")
        assert m.matches("Bash")
        assert m.matches("Read")
        assert m.matches("anything")

    def test_exact_match(self):
        m = ToolMatcher("Bash")
        assert m.matches("Bash")
        assert m.matches("bash")  # case insensitive
        assert not m.matches("BashTool")

    def test_or_pattern(self):
        m = ToolMatcher("Bash|Edit|Write")
        assert m.matches("Bash")
        assert m.matches("Edit")
        assert m.matches("Write")
        assert not m.matches("Read")

    def test_prefix_glob(self):
        m = ToolMatcher("mcp_*")
        assert m.matches("mcp_notion")
        assert m.matches("mcp_gmail")
        assert not m.matches("Bash")

    def test_repr(self):
        m = ToolMatcher("Bash|Edit")
        assert "Bash|Edit" in repr(m)


# ---------------------------------------------------------------------------
# SpeculativeClassifier tests
# ---------------------------------------------------------------------------

class TestSpeculativeClassifier:
    @pytest.mark.asyncio
    async def test_start_and_get_result(self):
        sc = SpeculativeClassifier()

        def classifier(cmd: str) -> str:
            return "allow" if "ls" in cmd else "ask"

        await sc.start_check("ls -la", classifier, "t1")
        result = await sc.get_result("t1")
        assert result == "allow"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        sc = SpeculativeClassifier()
        result = await sc.get_result("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_all(self):
        sc = SpeculativeClassifier()

        def classifier(cmd: str) -> str:
            return "allow"

        await sc.start_check("echo hi", classifier, "t1")
        sc.cancel_all()
        assert len(sc._pending) == 0

    @pytest.mark.asyncio
    async def test_classifier_failure_returns_ask(self):
        sc = SpeculativeClassifier()

        def bad_classifier(cmd: str) -> str:
            raise RuntimeError("boom")

        await sc.start_check("rm -rf /", bad_classifier, "t1")
        result = await sc.get_result("t1")
        assert result == "ask"
