# Agent Orchestration

AutoHarness supports multi-agent patterns for production agent architectures: fork semantics, background agents, swarm mode, and coordinator mode.

## Built-in agent types

Four agent types are available out of the box:

| Agent | Model | Tools | Use case |
|-------|-------|-------|----------|
| **Explore** | Haiku | Read, Grep, Glob, Bash | Fast read-only codebase exploration |
| **Plan** | Opus | Read, Grep, Glob, Bash | Architecture planning (read-only) |
| **Verification** | Sonnet | Read, Grep, Glob, Bash | Adversarial testing and verification |
| **GeneralPurpose** | Sonnet | All | General-purpose sub-agent |

```python
from autoharness import get_builtin_agent

explore = get_builtin_agent("explore")
print(explore.name)   # "Explore"
print(explore.tools)  # ["Read", "Grep", "Glob", "Bash"]
```

## Fork semantics

Fork is the key cost optimization for sub-agents. A forked agent inherits the parent's full conversation history and shares the prompt cache -- achieving **95% cost reduction** compared to a fresh context.

```python
from autoharness import AgentLoop, build_forked_messages

loop = AgentLoop(model="claude-sonnet-4-6")

# After running some tasks, fork a sub-agent
parent_messages = [
    {"role": "user", "content": "Analyze the auth module"},
    {"role": "assistant", "content": result},
]
forked_messages = build_forked_messages(
    parent_messages=parent_messages,
    directive="Find all files that import the auth module",
)
```

**How fork works:**

1. The parent's full conversation history is preserved
2. Every `tool_use` block in the last assistant message gets a placeholder `tool_result`
3. The sub-agent directive is appended to the last text block
4. All forked agents share the same message prefix, so the LLM prompt cache hits

!!! note
    Fork detection (`is_in_fork_child()`) prevents recursive forking. A sub-agent cannot fork another sub-agent.

## Background agents

Long-running sub-agents can be launched asynchronously:

- Returns an `agent_id` and `output_file` immediately
- The parent continues working while the background agent runs
- Completion triggers a notification
- Auto-backgrounds after 120 seconds if still running

## Swarm mode

Multiple agents run in parallel and communicate via JSONL mailbox files:

- Each agent has a role and a set of available tools
- Agents communicate by reading/writing to a shared mailbox
- Shutdown requires a handshake protocol (request/response)
- Idle agents poll for new messages on a 5-second interval

## Coordinator mode

An orchestrator agent delegates all tool use to worker agents:

- The coordinator never executes tools directly
- All work is dispatched to typed worker agents
- Coordinator and fork modes are mutually exclusive

## Agent definition format

Custom agents use YAML frontmatter + markdown prompt:

```yaml
---
name: security-reviewer
description: "Review code changes for security vulnerabilities"
tools: [Read, Grep, Glob]
model: sonnet
max_iterations: 30
---

# Security Review Agent

You are a security review agent. Analyze code for:
- SQL injection
- XSS vulnerabilities
- Secret exposure
- Path traversal
```

## Intelligent model routing

The model router (`agents/model_router.py`) automatically selects the appropriate model tier based on task complexity:

| Tier | Use case | Example models |
|------|----------|----------------|
| **FAST** | Simple lookups, search, file reads | Haiku, GPT-4o-mini |
| **STANDARD** | General coding, analysis, most tasks | Sonnet, GPT-4o |
| **PREMIUM** | Architecture decisions, security review, complex debugging | Opus, o1 |

The router analyzes the task description and conversation context to determine the appropriate tier. This optimizes cost and latency -- most tasks run on STANDARD, with PREMIUM reserved for genuinely complex work.

```python
from autoharness.agents.model_router import ModelRouter, ModelTier

router = ModelRouter()
tier = router.estimate_complexity("Fix a typo in the README")  # ModelTier.FAST
tier = router.estimate_complexity("Redesign the authentication architecture")  # ModelTier.PREMIUM
```

## Multi-agent governance

Sub-agents inherit governance from the parent constitution. Each agent type can have role-based permissions:

```yaml
permissions:
  agents:
    explore:
      tools: [Read, Grep, Glob]  # Read-only
    general:
      tools: all
      deny_patterns: ["rm -rf"]  # Still governed
```

## Related pages

- [Agent Loop](agent-loop.md) -- the execution loop that agents run within
- [Multi-Agent Workflows Guide](../guides/multi-agent.md) -- practical examples
- [Fork Semantics](../api/agent-loop.md) -- API details for `build_forked_messages`
