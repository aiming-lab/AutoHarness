# Agent Loop

The `AgentLoop` is the heart of AutoHarness. It wires together every subsystem -- context management, prompt assembly, tool execution, skill injection, governance, and session management -- into a single coherent execution loop.

## How it works

Each iteration of the loop follows these steps:

```
1. Check if auto-compact is needed (token budget)
2. Apply microcompact to old tool results
3. Call the LLM with system prompt + tools
4. Record token usage for cost tracking
5. If stop_reason != "tool_use" → return final text
6. For each tool_use block:
   a. Run through 14-step governance pipeline
   b. If denied → return synthetic error to LLM
   c. If allowed → execute tool, return result
7. Append tool results to conversation
8. Go to step 1
```

## Basic usage

```python
from autoharness import AgentLoop

loop = AgentLoop(
    model="claude-sonnet-4-6",
    constitution="constitution.yaml",
)
result = loop.run("Fix the failing tests in auth.py")
print(result)
```

## Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | `"claude-sonnet-4-6"` | Model identifier |
| `api_key` | `str \| None` | `None` | API key (falls back to `ANTHROPIC_API_KEY`) |
| `constitution` | `str \| Path \| dict \| Constitution \| None` | `None` | Governance constitution |
| `tools` | `list[ToolDefinition] \| None` | `None` | Additional tools to register |
| `skills_dir` | `str \| None` | `None` | Directory to scan for skill files |
| `session_dir` | `str \| None` | `None` | Directory for session persistence |
| `project_dir` | `str \| None` | `None` | Project root (for path scoping) |
| `llm_callback` | `LLMCallback \| None` | `None` | Custom LLM call function |
| `max_iterations` | `int` | `200` | Maximum loop iterations |

## Custom LLM callback

Replace the default Anthropic API call with any LLM provider:

```python
def my_llm(model, messages, tools, max_tokens):
    """Custom LLM callback.

    Returns dict with keys: content, stop_reason, usage
    """
    response = my_api_call(model, messages, tools, max_tokens)
    return {
        "content": [{"type": "text", "text": response.text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }

loop = AgentLoop(
    model="my-model",
    llm_callback=my_llm,
)
```

## Single-step mode

For custom loops that need finer control, use `step()`:

```python
loop = AgentLoop(model="claude-sonnet-4-6")
messages = [{"role": "user", "content": "List all Python files"}]

while True:
    messages, should_continue = loop.step(messages)
    if not should_continue:
        break
```

## Accessing subsystems

Every subsystem is accessible via properties:

```python
loop = AgentLoop(model="claude-sonnet-4-6")

loop.tool_registry      # ToolRegistry -- registered tools
loop.skill_registry     # SkillRegistry -- loaded skills
loop.prompt_registry    # SystemPromptRegistry -- prompt sections
loop.token_budget       # TokenBudget -- context window tracking
loop.auto_compactor     # AutoCompactor -- compaction engine
loop.pipeline           # ToolGovernancePipeline -- governance
loop.session_cost       # SessionCost -- token/cost tracking
loop.session_state      # SessionState -- session metadata
loop.constitution       # Constitution -- active constitution
loop.session_id         # str -- unique session identifier
```

## Async support

```python
result = await loop.arun("Fix the bug")
```

!!! note
    `arun()` currently wraps the synchronous `run()` in an executor. A fully async implementation with async LLM calls and async tool orchestration is planned.

## How subsystems connect

The AgentLoop initializes each subsystem and connects them:

1. **Constitution** resolves from path/dict/auto-discovery
2. **ToolRegistry** registers user-provided tools
3. **SkillRegistry** scans skill directories
4. **SystemPromptRegistry** registers identity, governance rules, skills, and tool instructions
5. **TokenBudget** configures from model's context window
6. **AutoCompactor** watches token usage and triggers compaction
7. **ToolGovernancePipeline** evaluates every tool call
8. **SessionCost** tracks per-turn token usage
9. **TranscriptWriter** logs conversation to JSONL (when `session_dir` is set)

!!! note
    **ModelRouter**, **FeatureFlags**, **AntiDistillation**, and **SentimentAnalyzer** are standalone modules available in `autoharness.agents.model_router`, `autoharness.core.anti_distillation`, and `autoharness.core.sentiment` respectively. They are not currently wired into AgentLoop but can be used independently.

## Related pages

- [Context Management](context-management.md) -- 5-layer compaction system
- [Governance Pipeline](governance.md) -- 14-step tool evaluation
- [Tool System](tools.md) -- tool registration and orchestration
- [Session Management](sessions.md) -- persistence and cost tracking
