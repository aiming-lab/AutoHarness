# Governance Pipeline

Every tool call in AutoHarness passes through a **14-step pipeline** before execution. This is the core safety mechanism -- it ensures that dangerous operations are blocked, suspicious ones require confirmation, and every decision is audit-logged.

## The 14 steps

```
1.  Turn Governor     Per-turn rate/budget limits check
2.  Parse/Validate    Check tool call structure & required fields
3.  Alias Resolution  Map tool aliases to canonical tool names
4.  Abort Check       Bail out if pipeline.abort() was called
5.  Risk Classify     Regex-based risk assessment (78 built-in patterns)
6.  PreToolUse Hooks  Run pre_tool_use hooks (secret scanner, path guard, etc.)
7.  Hook Denial       Short-circuit if any hook denies
8.  Hook Modify       Apply input rewrites from modify-hooks
9.  Permission        Merge risk thresholds + hooks + constitution rules
10. Handle Ask        Progressive trust + user confirmation callback
11. Execute           Invoke the actual tool via callback
12. PostToolUse Hooks Run post_tool_use hooks (output sanitization, etc.)
13. Failure Hooks     Run PostToolUseFailure hooks if execution errored
14. Audit             Log the complete lifecycle to JSONL
```

## Dual enforcement

YAML constitution rules compile into **two enforcement paths**:

| Path | Compliance | Mechanism |
|------|-----------|-----------|
| **System prompt** | ~80% | Rules are injected as LLM instructions |
| **Runtime hooks** | 100% | Rules are enforced as code before/after execution |

This dual approach means the LLM usually respects the rules (reducing unnecessary tool calls), but even when it doesn't, the hooks catch it.

## Risk classification

The built-in risk classifier uses 78 regex patterns across these categories:

- **Dangerous commands** -- `rm -rf`, `mkfs`, `dd if=`, `chmod 777`
- **Secret patterns** (9 families) -- API keys, tokens, passwords, certificates
- **Path traversal** -- `../../`, symlink attacks
- **Network exfiltration** -- `curl ... | bash`, reverse shells
- **Privilege escalation** -- `sudo`, `su`, `chown`

Each tool call receives a risk level: `low`, `medium`, `high`, or `critical`.

## Permission cascade

When a tool call is evaluated, permissions are resolved in this order:

1. Tool-specific `deny_patterns` -- if matched, **deny** (no override)
2. Tool-specific `ask_patterns` -- if matched, **ask** for confirmation
3. Tool-specific `policy` -- `open`, `restricted`, or `locked`
4. Path validation (8 layers with TOCTOU protection)
5. Constitution defaults (`unknown_tool`, `unknown_path`, `on_error`)
6. Risk threshold mapping
7. Progressive trust (session-level trust escalation with decay)
8. Turn governor (iteration limits, rate limiting)

!!! warning
    The permission engine is **fail-closed** by default. If any step encounters an error, the tool call is denied. Set `on_error: deny` in your constitution (this is the default).

## Hook lifecycle

Hooks are registered for lifecycle events and run as part of the pipeline:

```python
from autoharness import hook, HookResult

@hook("pre_tool_use", name="block_production")
def block_production(tool_call, risk, context):
    if "production" in tool_call.tool_input.get("command", ""):
        return HookResult(action="deny", reason="Production commands blocked")
    return HookResult(action="allow")
```

Hook events:

| Event | When | Can block? |
|-------|------|------------|
| `PreToolUse` | Before tool execution | Yes |
| `PostToolUse` | After successful execution | Yes (suppress result) |
| `PostToolUseFailure` | After failed execution | No |
| `SessionStart` | Session begins | No |
| `SessionEnd` | Session ends | No |
| `PermissionDenied` | Permission check fails | No |

## Progressive trust

Trust escalates within a session as the agent demonstrates safe behavior:

- Each allowed tool call increases trust slightly
- Denied calls reduce trust
- Trust decays over time (session-level, not persistent)
- Higher trust can upgrade `ask` decisions to `allow` for low-risk operations

## Turn governor

Prevents runaway loops:

- **Iteration limit** -- hard cap on loop iterations (default: 200)
- **Rejection spiral detection** -- if N consecutive tool calls are denied, the agent is asked to reconsider its approach
- **Rate limiting** -- throttles tool calls per time window

## Anti-distillation

AutoHarness includes an anti-distillation system (`core/anti_distillation.py`) that injects decoy tools into the tool registry. These decoys are designed to detect model extraction attempts -- if a downstream model calls a decoy tool, it signals that the agent's behavior is being replicated without authorization. Decoy tools are transparent to legitimate users but act as canary traps for extraction pipelines.

## Frustration detection

The sentiment analysis module (`core/sentiment.py`) uses regex-based pattern matching to detect user frustration signals in conversation. When frustration is detected, the agent can adapt its behavior -- for example, simplifying responses, offering to escalate, or adjusting its approach. This provides a lightweight alternative to full NLP sentiment analysis with zero external dependencies.

## Related pages

- [Configuration](../getting-started/configuration.md) -- constitution YAML format
- [Agent Loop](agent-loop.md) -- how governance integrates into the execution loop
- [Observability](observability.md) -- audit trail and reporting
