# Context Management

AutoHarness uses a 5-layer compaction system to keep conversations within the model's context window. This is critical for long-running agent sessions that can easily exceed 200K tokens.

## The five layers

### Layer 1: Microcompact

Prunes old tool outputs while preserving recent context. Applied every iteration before the LLM call.

```python
from autoharness.context.microcompact import microcompact

# Replace old tool results with "[content cleared]"
# Keeps the 3 most recent tool result messages intact
messages = microcompact(messages, keep_recent=3)
```

**What it does:**

- Replaces tool result content older than `keep_recent` turns with `"[content cleared]"`
- Only compacts tools in the `COMPACTABLE_TOOLS` set (bash, grep, file reads, etc.)
- Preserves agent-critical tools (Skill, Task, AskUser) unconditionally
- Only compacts content longer than 100 characters

**Key constants:**

| Constant | Value | Description |
|----------|-------|-------------|
| `KEEP_RECENT` | 3 | Number of recent tool results to preserve |
| `MIN_CONTENT_SIZE` | 100 | Minimum characters before compaction applies |

### Layer 2: AutoCompact

LLM-based summarization triggered when token usage approaches the context window limit.

```python
from autoharness.context.autocompact import AutoCompactor

compactor = AutoCompactor(token_budget=token_budget, model="claude-sonnet-4-6")

if compactor.should_compact(messages):
    messages, summary = compactor.compact(messages, summarizer=my_summarizer)
```

**Threshold formula:**

```
threshold = context_window - MAX_OUTPUT_TOKENS_FOR_SUMMARY - AUTOCOMPACT_BUFFER_TOKENS
```

For a 200K model: `200,000 - 20,000 - 13,000 = 167,000 tokens`

**Key constants:**

| Constant | Value | Description |
|----------|-------|-------------|
| `AUTOCOMPACT_BUFFER_TOKENS` | 13,000 | Safety buffer below context window |
| `MAX_OUTPUT_TOKENS_FOR_SUMMARY` | 20,000 | Reserved for the summarization call |
| `MAX_CONSECUTIVE_FAILURES` | 3 | Circuit breaker for repeated failures |
| `MAX_COMPACT_STREAMING_RETRIES` | 2 | Retries for streaming failures |

### Layer 3: Reactive compact

Emergency recovery when a prompt-too-long error occurs despite auto-compact. Aggressively strips content until the messages fit.

### Layer 4: Post-compact file restoration

After compaction, recently modified files are re-injected into the conversation so the model retains working context.

| Constant | Value | Description |
|----------|-------|-------------|
| `POST_COMPACT_MAX_FILES_TO_RESTORE` | 5 | Max files to re-inject |
| `POST_COMPACT_TOKEN_BUDGET` | 50,000 | Total token budget for restoration |
| `POST_COMPACT_MAX_TOKENS_PER_FILE` | 5,000 | Per-file token limit |

### Layer 5: Session memory compact

A background agent periodically extracts key information into a markdown file, providing persistent memory across compaction events.

## Token budget tracking

The `TokenBudget` tracks cumulative token usage and reports how close the conversation is to the context window:

```python
from autoharness.context.tokens import TokenBudget

budget = TokenBudget(max_tokens=200_000)
budget.record_usage(input_tokens=50_000, output_tokens=2_000)

print(budget.utilization)  # 0.26
print(budget.remaining)    # 148_000
```

## Image stripping

Before compaction, image and document blocks are replaced with `[image]` / `[document]` placeholders. This prevents the compaction API call itself from triggering a prompt-too-long error.

## How it fits in the AgentLoop

The AgentLoop applies context management automatically every iteration:

1. Check if `should_compact()` -- triggers auto-compact if over threshold
2. Apply `microcompact()` -- prune old tool outputs
3. Call LLM with the managed messages

You never need to call these manually unless building a custom loop.

## Related pages

- [Agent Loop](agent-loop.md) -- how context management integrates into the loop
- [Session Management](sessions.md) -- session-level persistence across compactions
