# Observability

AutoHarness provides full governance traceability through structured audit trails, performance metrics, and session transcripts.

## Audit trail

Every governance decision is logged to a structured JSONL file:

```json
{
  "timestamp": "2026-03-31T21:34:00Z",
  "session_id": "a1b2c3d4",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /tmp/old"},
  "action": "allow",
  "risk_level": "medium",
  "matched_rules": [],
  "decision_chain": ["classify:medium", "permit:allow", "trust:allow"],
  "duration_ms": 2.3
}
```

Each entry records:

- **Decision** -- allow, deny, or ask
- **Risk level** -- low, medium, high, critical
- **Matched rules** -- which built-in patterns triggered
- **Decision chain** -- the sequence of pipeline steps that produced the decision
- **Timing** -- per-call duration in milliseconds

## Audit reports

### CLI summary

```bash
autoharness audit summary
```

Shows total decisions, allow/deny/ask distribution, and top block reasons.

### HTML export

```bash
autoharness audit report --format html --output report.html
```

Generates a compliance-ready HTML report with charts, risk distribution, and decision details.

### Programmatic access

```python
from autoharness.core.audit import AuditEngine

engine = AuditEngine(output_path=".autoharness/audit.jsonl")
summary = engine.get_summary()
print(summary["total_calls"])
print(summary["blocked_count"])
print(summary["top_blocked_reasons"])
```

## Per-call timing

Every tool call through the governance pipeline is timed. Slow phases (over 2 seconds) are logged automatically:

```
WARNING: Slow phase detected: PreHook took 2,340ms for tool Bash
```

Hook execution over 500ms triggers a timing display in the CLI output.

| Constant | Value | Description |
|----------|-------|-------------|
| `SLOW_PHASE_LOG_THRESHOLD_MS` | 2,000 | Log warning for slow pipeline phases |
| `HOOK_TIMING_DISPLAY_THRESHOLD_MS` | 500 | Show timing for slow hooks |

## Session transcripts

Full conversation history is logged to JSONL for debugging:

```python
from autoharness import AgentLoop

loop = AgentLoop(
    model="claude-sonnet-4-6",
    session_dir=".autoharness/sessions/",
)
# Transcript automatically written to {session_id}-transcript.jsonl
```

Each transcript entry includes role, content, timestamp, and token usage.

## Cost tracking

Token usage is tracked per-session with cache awareness:

```python
cost = loop.session_cost
print(f"Input: {cost.total_input_tokens:,}")
print(f"Output: {cost.total_output_tokens:,}")
```

## Related pages

- [Governance Pipeline](governance.md) -- the pipeline that generates audit events
- [Session Management](sessions.md) -- session-level transcripts and cost tracking
- [Configuration](../getting-started/configuration.md) -- audit configuration in the constitution
