# Session Management

AutoHarness provides persistent, resumable agent sessions with structured state, cost tracking, and conversation transcripts.

## Session persistence format

Each session is saved as a Markdown file with YAML frontmatter:

```markdown
---
date: 2026-03-31T21:34:00Z
project: my-project
branch: feature/auth
status: in-progress
session_id: a1b2c3d4
---
## Working: [Refactoring auth module]
## In Progress: [Adding JWT support]
## What Has Failed: [Direct token validation -- needs middleware]
## Next Step: [Implement refresh token rotation]
```

**Storage location:** `~/.autoharness/sessions/*-session.md`

Sessions older than 7 days are automatically cleaned up.

## Session state

```python
from autoharness import SessionState

state = SessionState(
    project="my-project",
    branch="feature/auth",
)
state.in_progress.append("Adding JWT support")
state.failed.append("Direct token validation")
state.next_step = "Implement refresh token rotation"
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Auto-generated unique ID |
| `date` | `str` | ISO timestamp |
| `project` | `str` | Project name |
| `branch` | `str` | Git branch |
| `status` | `str` | `in-progress` or `completed` |
| `working` | `list[str]` | Currently active tasks |
| `in_progress` | `list[str]` | Tasks underway |
| `failed` | `list[str]` | Failed attempts (avoid retrying) |
| `next_step` | `str` | Recommended next action |

## Resume briefings

When resuming a session, a structured briefing is generated:

```
PROJECT: my-project (feature/auth)
WHAT WE'RE BUILDING: JWT-based authentication
CURRENT STATE: In Progress
WHAT NOT TO RETRY: Direct token validation (needs middleware)
NEXT STEP: Implement refresh token rotation
```

## Cost tracking

The `SessionCost` tracker records per-turn token usage:

```python
from autoharness import SessionCost

cost = SessionCost(session_id="abc123", model="claude-sonnet-4-6")
cost.record_turn(
    input_tokens=50_000,
    output_tokens=2_000,
    cache_read=45_000,
    cache_write=5_000,
)
print(cost.total_input_tokens)   # 50000
print(cost.total_output_tokens)  # 2000
```

## Transcript logging

Conversations are logged to JSONL files for debugging and analysis:

```python
from autoharness import TranscriptWriter

writer = TranscriptWriter(".autoharness/sessions/abc-transcript.jsonl")
writer.append({
    "role": "user",
    "content": "Fix the auth bug",
    "timestamp": 1711900000.0,
})
writer.close()
```

The AgentLoop automatically manages transcript logging when `session_dir` is provided.

## Using sessions with AgentLoop

```python
from autoharness import AgentLoop

loop = AgentLoop(
    model="claude-sonnet-4-6",
    session_dir=".autoharness/sessions/",
)
result = loop.run("Fix the auth bug")

# Session state is automatically saved on completion
print(loop.session_id)
print(loop.session_cost.total_input_tokens)
```

## Related pages

- [Agent Loop](agent-loop.md) -- how sessions integrate with the execution loop
- [Observability](observability.md) -- audit trails alongside session transcripts
