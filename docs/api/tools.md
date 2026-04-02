# API Reference: Tool System

## `ToolDefinition`

```python
from autoharness import ToolDefinition
```

Complete definition of a registered tool.

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    aliases: list[str] = []
    search_hint: str = ""
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    is_destructive: bool = False
    should_defer: bool = False
    always_load: bool = False
    max_result_size_chars: int = 50_000
    source: str = "builtin"
    enabled: bool = True
    execute: Callable[..., Any] | None = None
    validate_input: Callable[[dict], bool] | None = None
    prompt_fn: Callable[[], str | None] | None = None
```

### Methods

#### `prompt() -> str | None`

Return this tool's system prompt contribution. Delegates to `prompt_fn` if set.

#### `to_api_schema() -> dict`

Convert to Anthropic API tool schema format:

```python
{"name": "Bash", "description": "...", "input_schema": {...}}
```

## `ToolRegistry`

```python
from autoharness import ToolRegistry
```

Central registry for all available tools.

### Methods

#### `register(tool: ToolDefinition) -> None`

Register a tool. Raises `ValueError` if a tool with the same name already exists.

```python
registry = ToolRegistry()
registry.register(ToolDefinition(
    name="Bash",
    description="Execute shell commands",
    input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
))
```

#### `unregister(name: str) -> None`

Remove a tool from the registry.

#### `get(name: str) -> ToolDefinition | None`

Get a tool by name or alias. Returns `None` if not found.

#### `to_api_schemas() -> list[dict]`

Get all enabled, non-deferred tools as Anthropic API schemas.

#### `get_tool_prompts() -> dict[str, str]`

Collect prompt contributions from all registered tools.

## `ToolOrchestrator`

```python
from autoharness import ToolOrchestrator
```

Orchestrates tool execution with concurrency rules.

### Constructor

```python
ToolOrchestrator(registry: ToolRegistry)
```

### Behavior

- Tools with `is_concurrency_safe=True` run in parallel (up to 10)
- Tools with `is_concurrency_safe=False` run serially
- Results are returned in submission order
