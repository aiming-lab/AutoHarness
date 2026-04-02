# Tool System

AutoHarness provides a production-grade tool system with central registration, concurrent orchestration, output budgets, and lazy schema discovery.

## Tool registry

All tools are registered in a central `ToolRegistry`:

```python
from autoharness import ToolDefinition, ToolRegistry

registry = ToolRegistry()

registry.register(ToolDefinition(
    name="Bash",
    description="Execute shell commands",
    input_schema={
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    is_read_only=False,
    is_concurrency_safe=False,
    max_result_size_chars=50_000,
    execute=lambda command: subprocess.run(command, shell=True, capture_output=True).stdout,
))
```

## ToolDefinition fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Tool name |
| `description` | `str` | required | Tool description for the LLM |
| `input_schema` | `dict` | required | JSON Schema for tool input |
| `aliases` | `list[str]` | `[]` | Alternative names |
| `search_hint` | `str` | `""` | 3-10 word capability phrase for ToolSearch |
| `is_read_only` | `bool` | `False` | Whether the tool only reads data |
| `is_concurrency_safe` | `bool` | `False` | Whether it can run in parallel |
| `is_destructive` | `bool` | `False` | Whether it makes irreversible changes |
| `should_defer` | `bool` | `False` | Defer schema loading (use ToolSearch) |
| `always_load` | `bool` | `False` | Force include in initial prompt |
| `max_result_size_chars` | `int` | `50,000` | Output truncation limit |
| `source` | `str` | `"builtin"` | Origin: `builtin`, `conditional`, `mcp`, `skill` |
| `execute` | `Callable` | `None` | Execution function |
| `prompt_fn` | `Callable` | `None` | System prompt contribution |

## Concurrent orchestration

The `ToolOrchestrator` executes tools with concurrency rules:

- **Read-only tools** (`is_concurrency_safe=True`) run in parallel (up to 10)
- **Write tools** (`is_concurrency_safe=False`) run serially
- Results are yielded in **submission order**, not completion order

```python
from autoharness import ToolOrchestrator

orchestrator = ToolOrchestrator(registry=registry)
```

## Output budgets

Each tool has a `max_result_size_chars` limit. When output exceeds this limit, the overflow is persisted to disk and the tool returns a file path reference instead.

This prevents a single large tool result (e.g., `cat` on a 10MB file) from consuming the entire context window.

## ToolSearch (lazy schema discovery)

When you have 20+ tools, loading all schemas into the system prompt wastes context. ToolSearch solves this:

1. Non-essential tools are registered with `should_defer=True`
2. Only tool names and descriptions appear in the prompt
3. The model calls `ToolSearch` to discover full schemas on demand

```python
# Register a deferred tool
registry.register(ToolDefinition(
    name="DatabaseQuery",
    description="Execute SQL queries",
    input_schema={...},
    should_defer=True,
    search_hint="query database SQL select",
))
```

The model sees `DatabaseQuery` in its tool list but only fetches the full schema when it needs to use it.

## Tool prompt contributions

Each tool can contribute instructions to the system prompt:

```python
registry.register(ToolDefinition(
    name="Bash",
    description="Execute shell commands",
    input_schema={...},
    prompt_fn=lambda: (
        "When using Bash, prefer single commands over scripts. "
        "Always quote file paths containing spaces."
    ),
))
```

These are assembled by the [Prompt System](../api/prompt.md) into the system prompt automatically.

## Related pages

- [Agent Loop](agent-loop.md) -- how tools integrate into the execution loop
- [Governance Pipeline](governance.md) -- how tool calls are validated
- [Skill System](skills.md) -- skills as a special kind of tool
