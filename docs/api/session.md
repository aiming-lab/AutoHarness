# API Reference: Session

## `SessionState`

```python
from autoharness import SessionState
```

Structured session state for persistence and resume.

```python
@dataclass
class SessionState:
    session_id: str          # Auto-generated UUID prefix
    date: str                # ISO timestamp
    project: str = ""
    branch: str = ""
    status: str = "in-progress"
    working: list[str] = []
    in_progress: list[str] = []
    not_started: list[str] = []
    failed: list[str] = []
    open_questions: list[str] = []
    next_step: str = ""
```

## `SessionCost`

```python
from autoharness import SessionCost
```

Per-session token usage and cost tracking.

### Constructor

```python
SessionCost(session_id: str, model: str)
```

### Methods

#### `record_turn(input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> None`

Record token usage for a single turn.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `total_input_tokens` | `int` | Cumulative input tokens |
| `total_output_tokens` | `int` | Cumulative output tokens |

## `TranscriptWriter`

```python
from autoharness import TranscriptWriter
```

JSONL conversation transcript writer.

### Constructor

```python
TranscriptWriter(path: str)
```

### Methods

#### `append(entry: dict) -> None`

Append a transcript entry. Entries should include `role`, `content`, and `timestamp`.

#### `close() -> None`

Flush and close the transcript file.

### Example

```python
writer = TranscriptWriter(".autoharness/sessions/abc-transcript.jsonl")
writer.append({
    "role": "user",
    "content": "Fix the auth bug",
    "timestamp": 1711900000.0,
})
writer.append({
    "role": "assistant",
    "content": [{"type": "text", "text": "I'll fix that now."}],
    "timestamp": 1711900001.0,
    "usage": {"input_tokens": 1000, "output_tokens": 50},
})
writer.close()
```

## `save_session`

```python
from autoharness.session.persistence import save_session

path = save_session(state: SessionState, base_dir: str | Path | None = None) -> Path
```

Save session state to a markdown file with YAML frontmatter. Default directory: `~/.autoharness/sessions/`.
