# API Reference: Context Engine

## `TokenBudget`

```python
from autoharness import TokenBudget
```

Tracks token usage against the model's context window.

### Constructor

```python
TokenBudget(max_tokens: int)
```

### Methods

#### `record_usage(input_tokens: int, output_tokens: int) -> None`

Record token usage for a turn.

#### `reset() -> None`

Reset usage counters (called after compaction).

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `max_tokens` | `int` | Context window size |
| `used_tokens` | `int` | Total tokens used |
| `remaining` | `int` | Tokens remaining |
| `utilization` | `float` | Usage ratio (0.0 to 1.0) |

### Example

```python
budget = TokenBudget(max_tokens=200_000)
budget.record_usage(50_000, 2_000)
print(budget.utilization)  # 0.26
print(budget.remaining)    # 148_000
```

## `AutoCompactor`

```python
from autoharness import AutoCompactor
```

LLM-based conversation summarization with circuit breaker protection.

### Constructor

```python
AutoCompactor(token_budget: TokenBudget, model: str)
```

### Methods

#### `should_compact(messages: list[dict]) -> bool`

Check if compaction is needed based on token usage threshold.

#### `compact(messages: list[dict], summarizer: Callable) -> tuple[list[dict], str]`

Compact messages using the provided summarizer callback. Returns the compacted messages and the summary text.

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `AUTOCOMPACT_BUFFER_TOKENS` | 13,000 | Safety buffer |
| `MAX_OUTPUT_TOKENS_FOR_SUMMARY` | 20,000 | Reserved for summarization |
| `MAX_CONSECUTIVE_FAILURES` | 3 | Circuit breaker threshold |

## `microcompact`

```python
from autoharness import microcompact
```

```python
microcompact(messages: list[dict], keep_recent: int = 3) -> list[dict]
```

Prune old tool outputs while preserving recent context. Replaces tool result content with `"[content cleared]"` for messages older than `keep_recent` turns.

### Example

```python
messages = [...]  # Long conversation with many tool results
pruned = microcompact(messages, keep_recent=3)
# Old tool results replaced with "[content cleared]"
# Most recent 3 tool results preserved
```
