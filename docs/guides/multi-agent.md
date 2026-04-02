# Multi-Agent Workflows

AutoHarness supports several multi-agent patterns. This guide shows practical examples of each.

## Pattern 1: Fork a read-only explorer

The most common pattern -- fork a lightweight sub-agent to search the codebase while the parent continues working.

```python
from autoharness import AgentLoop, build_forked_messages, get_builtin_agent

loop = AgentLoop(model="claude-sonnet-4-6")

# Run a task first to build context
result = loop.run("Start refactoring the auth module")

# Fork an explorer to find related files
explore_agent = get_builtin_agent("explore")
parent_messages = [
    {"role": "user", "content": "Start refactoring the auth module"},
    {"role": "assistant", "content": result},
]
forked = build_forked_messages(
    parent_messages=parent_messages,
    directive="Find all files that import auth.py or use the User model",
)
# The forked messages share the parent's prompt cache
# Cost: ~5% of a fresh agent context
```

!!! tip
    Use fork for any read-only sub-task. The prompt cache sharing makes it nearly free compared to starting a fresh agent.

## Pattern 2: Verification agent

After completing a task, fork a verification agent that adversarially tests the result:

```python
verifier = get_builtin_agent("verification")
parent_messages = [
    {"role": "user", "content": "Start refactoring the auth module"},
    {"role": "assistant", "content": result},
]
forked = build_forked_messages(
    parent_messages=parent_messages,
    directive=(
        "Verify the auth refactoring. Run: "
        "1) pytest tests/ 2) mypy src/ 3) ruff check src/ "
        "4) Check edge cases in auth flow. "
        "Report PASS/FAIL/PARTIAL for each check."
    ),
)
```

The verification agent follows a strict protocol:

- Runs build, test suite, linter/type-check
- Performs adversarial probing of edge cases
- Reports PASS / FAIL / PARTIAL for each check
- Cannot say PASS without running all checks

## Pattern 3: Parallel task decomposition

Split a large task into parallel sub-agents:

```python
from autoharness import AgentLoop, get_builtin_agent

# Create specialized agents for parallel work
tasks = [
    ("explore", "Map the database schema and all migration files"),
    ("explore", "Find all API endpoint definitions and their auth requirements"),
    ("plan", "Analyze the test coverage gaps in the auth module"),
]

results = []
for agent_type, directive in tasks:
    agent = get_builtin_agent(agent_type)
    forked = build_forked_messages(
        parent_messages=parent_messages,
        directive=directive,
    )
    results.append(forked)
```

## Pattern 4: Coordinator mode

The coordinator never executes tools directly -- it delegates everything to workers:

```python
loop = AgentLoop(
    model="claude-sonnet-4-6",
    constitution="constitution.yaml",
)

# The coordinator instructs workers
result = loop.run(
    "Refactor the payment module. "
    "Use an explore agent to map the codebase, "
    "then a general agent to make changes, "
    "then a verification agent to validate."
)
```

## Governance across agents

All sub-agents inherit the parent's constitution. Each agent type can have role-specific permissions:

```yaml
permissions:
  agents:
    explore:
      tools: [Read, Grep, Glob]    # Read-only
    verification:
      tools: [Read, Grep, Glob, Bash]
      deny_patterns: ["git push", "npm publish"]
    general:
      tools: all
```

## Cost optimization

| Pattern | Cost vs. fresh context |
|---------|----------------------|
| Fork (shared cache) | ~5% |
| Background agent | 100% (independent context) |
| Swarm member | 100% (independent context) |

Fork is dramatically cheaper because all forked agents share the same message prefix, enabling prompt cache hits.

## Related pages

- [Agent Orchestration](../concepts/agents.md) -- architecture details
- [Agent Loop](../concepts/agent-loop.md) -- the execution loop
- [Build a Custom Agent](custom-agent.md) -- single-agent customization
