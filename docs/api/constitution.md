# API Reference: Constitution

## `Constitution`

```python
from autoharness import Constitution
```

The governance constitution -- central configuration for AutoHarness.

### Factory methods

#### `Constitution.load(path: str | Path) -> Constitution`

Load from a YAML file.

```python
const = Constitution.load("constitution.yaml")
```

#### `Constitution.from_dict(data: dict) -> Constitution`

Create from a Python dictionary.

```python
const = Constitution.from_dict({
    "version": "1.0",
    "permissions": {
        "defaults": {"on_error": "deny"},
    },
})
```

#### `Constitution.default() -> Constitution`

Auto-discover and load the default constitution. Searches:

1. `constitution.yaml` in current directory
2. `.autoharness/constitution.yaml` in project directory
3. `~/.autoharness/constitution.yaml`
4. Built-in defaults

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `rules` | `list[Rule]` | Governance rules |
| `identity` | `dict` | Agent identity metadata |
| `permissions` | `PermissionDefaults` | Default permission settings |
| `tool_permissions` | `dict[str, ToolPermission]` | Per-tool permission configs |
| `risk_thresholds` | `dict[str, str]` | Risk level to action mapping |
| `audit_config` | `dict` | Audit settings |

## `ToolGovernancePipeline`

```python
from autoharness import ToolGovernancePipeline
```

The 14-step tool evaluation pipeline.

### Constructor

```python
ToolGovernancePipeline(
    constitution: Constitution,
    project_dir: str = ".",
    session_id: str = "",
)
```

### Methods

#### `evaluate(tool_call: ToolCall) -> HookResult`

Run a tool call through the full 14-step pipeline.

```python
from autoharness.core.types import ToolCall

tc = ToolCall(tool_name="Bash", tool_input={"command": "ls"})
result = pipeline.evaluate(tc)
print(result.action)  # "allow" | "deny" | "ask"
print(result.reason)  # explanation string
```

## `HookResult`

```python
from autoharness import HookResult
```

Result of a governance decision.

| Field | Type | Description |
|-------|------|-------------|
| `action` | `str` | `"allow"`, `"deny"`, or `"ask"` |
| `reason` | `str` | Human-readable explanation |

## `hook` decorator

```python
from autoharness import hook, HookResult

@hook("pre_tool_use", name="my_hook")
def my_hook(tool_name: str, tool_input: dict, context: dict) -> HookResult:
    return HookResult(action="allow")
```

Register a Python function as a governance hook.

| Parameter | Description |
|-----------|-------------|
| `event` | Hook event: `"pre_tool_use"`, `"post_tool_use"`, etc. |
| `name` | Unique hook identifier |

## `lint_tool_call`

```python
from autoharness import lint_tool_call

result = lint_tool_call(
    tool_name: str,
    tool_input: dict,
    constitution: str | dict | Constitution | None = None,
) -> HookResult
```

Evaluate a single tool call without an LLM client. Uses default constitution if none provided.
