# API Reference: AgentLoop

::: autoharness.agent_loop.AgentLoop

## `AgentLoop`

```python
from autoharness import AgentLoop
```

The core agent execution loop that integrates all AutoHarness subsystems.

### Constructor

```python
AgentLoop(
    model: str = "claude-sonnet-4-6",
    api_key: str | None = None,
    constitution: str | Path | dict | Constitution | None = None,
    tools: list[ToolDefinition] | None = None,
    skills_dir: str | None = None,
    session_dir: str | None = None,
    project_dir: str | None = None,
    llm_callback: LLMCallback | None = None,
    max_iterations: int = 200,
)
```

| Parameter | Description |
|-----------|-------------|
| `model` | Model identifier (e.g., `"claude-sonnet-4-6"`, `"claude-opus-4-6"`) |
| `api_key` | API key. Falls back to `ANTHROPIC_API_KEY` environment variable |
| `constitution` | Path to YAML file, dict, `Constitution` instance, or `None` for defaults |
| `tools` | Additional `ToolDefinition` instances to register |
| `skills_dir` | Directory to scan for `.md` skill files |
| `session_dir` | Directory for session persistence and transcripts |
| `project_dir` | Project root for path scoping. Defaults to current working directory |
| `llm_callback` | Custom LLM function replacing the default Anthropic API call |
| `max_iterations` | Hard limit on loop iterations (default 200) |

### Methods

#### `run(task: str) -> str`

Run the agent loop synchronously. Returns the final text response.

```python
result = loop.run("Fix the failing tests")
```

Raises `RuntimeError` if no LLM callback and no API key are available.

#### `arun(task: str) -> str`

Async version of `run()`. Currently wraps `run()` in an executor.

```python
result = await loop.arun("Fix the failing tests")
```

#### `step(messages: list[dict]) -> tuple[list[dict], bool]`

Execute a single agent step. Returns updated messages and a boolean indicating whether more steps are needed.

```python
messages, should_continue = loop.step(messages)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `session_id` | `str` | Unique session identifier |
| `tool_registry` | `ToolRegistry` | Registered tools |
| `skill_registry` | `SkillRegistry` | Loaded skills |
| `prompt_registry` | `SystemPromptRegistry` | System prompt sections |
| `token_budget` | `TokenBudget` | Context window tracker |
| `auto_compactor` | `AutoCompactor` | Compaction engine |
| `pipeline` | `ToolGovernancePipeline` | Governance pipeline |
| `session_cost` | `SessionCost` | Token/cost tracker |
| `session_state` | `SessionState` | Session metadata |
| `constitution` | `Constitution` | Active constitution |

## `LLMCallback`

```python
LLMCallback = Callable[
    [str, list[dict], list[dict], int],
    dict[str, Any],
]
```

Signature: `(model, messages, tools, max_tokens) -> response_dict`

The response dict must contain:

- `"content"`: list of content blocks (`{"type": "text", "text": "..."}` or `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}`)
- `"stop_reason"`: `"end_turn"` or `"tool_use"`
- `"usage"`: `{"input_tokens": int, "output_tokens": int}`

## `build_forked_messages`

```python
from autoharness import build_forked_messages

forked = build_forked_messages(
    parent_messages: list[dict],
    directive: str,
) -> list[dict]
```

Build a forked message list for a sub-agent that shares the parent's prompt cache.

## `get_builtin_agent`

```python
from autoharness import get_builtin_agent

agent = get_builtin_agent(name: str) -> AgentDefinition
```

Get a built-in agent definition. Available names: `"explore"`, `"plan"`, `"verification"`, `"general"`.
