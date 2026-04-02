#!/usr/bin/env python3
"""Context Management Demo — 5-layer compaction system.

Shows how to:
  1. Use TokenBudget for tracking token usage
  2. Query model context windows
  3. Use microcompact to clear old tool results
  4. Use AutoCompactor with circuit breaker
  5. Restore files after compaction
  6. Parse token budget syntax ("+500k")
  7. Use OutputRecoveryLoop for max_tokens retry

Run:
    python examples/context_management_demo.py
"""

from autoharness.context import (
    COMPACTABLE_TOOLS,
    POST_COMPACT_MAX_FILES_TO_RESTORE,
    POST_COMPACT_TOKEN_BUDGET,
    # AutoCompactor
    AutoCompactor,
    # Recovery
    OutputRecoveryLoop,
    RetryConfig,
    # Token tracking
    TokenBudget,
    compute_backoff_ms,
    estimate_message_tokens,
    estimate_tokens,
    find_token_budget_positions,
    get_budget_continuation_message,
    # Model windows
    get_context_window,
    get_max_output_tokens,
    has_1m_context,
    is_retryable_status,
    # Microcompact
    microcompact,
    model_supports_1m,
    # Token budget parsing
    parse_token_budget,
    # Post-compact restoration
    restore_files_after_compact,
)


def main() -> None:
    print("=" * 60)
    print("AutoHarness Context Management Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. TokenBudget — track token usage against a maximum budget.
    # ------------------------------------------------------------------
    print("\n1. TokenBudget tracking:")

    budget = TokenBudget(max_tokens=200_000, reserve=13_000)
    print(f"   Max tokens: {budget.max_tokens:,}")
    print(f"   Reserve: {budget.reserve:,}")
    print(f"   Effective window: {budget.effective_window:,}")
    print(f"   Available: {budget.available:,}")

    # Simulate a few API calls
    budget.record_usage(input_tokens=50_000, output_tokens=5_000)
    print("\n   After turn 1 (50k in, 5k out):")
    print(f"     Usage: {budget.current_usage:,} tokens ({budget.usage_ratio:.1%})")
    print(f"     Available: {budget.available:,}")
    print(f"     Should warn: {budget.should_warn}")
    print(f"     Should compact: {budget.should_compact}")

    budget.record_usage(input_tokens=100_000, output_tokens=10_000)
    print("\n   After turn 2 (100k in, 10k out):")
    print(f"     Usage: {budget.current_usage:,} tokens ({budget.usage_ratio:.1%})")
    print(f"     Should warn: {budget.should_warn}")
    print(f"     Should compact: {budget.should_compact}")

    # ------------------------------------------------------------------
    # 2. Model context windows.
    # ------------------------------------------------------------------
    print("\n2. Model context windows:")
    for model in ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]:
        window = get_context_window(model)
        max_out = get_max_output_tokens(model)
        max_out_esc = get_max_output_tokens(model, escalated=True)
        supports_1m = model_supports_1m(model)
        print(f"   {model}:")
        print(f"     Context: {window:,} | Max output: {max_out:,} | Escalated: {max_out_esc:,}")
        print(f"     Supports 1M: {supports_1m}")

    # 1M context variant
    model_1m = "claude-opus-4-6[1m]"
    print(f"\n   {model_1m}:")
    print(f"     Context: {get_context_window(model_1m):,}")
    print(f"     has_1m_context: {has_1m_context(model_1m)}")

    # ------------------------------------------------------------------
    # 3. Token estimation.
    # ------------------------------------------------------------------
    print("\n3. Token estimation:")
    text = "This is a sample text for token estimation purposes."
    print(f"   Text: '{text}'")
    print(f"   Estimated tokens: {estimate_tokens(text)}")

    messages = [
        {"role": "user", "content": "Please list all Python files in the project."},
        {"role": "assistant", "content": "I'll search for Python files using the Glob tool."},
        {"role": "user", "content": "Thanks! Now read the main one."},
    ]
    msg_tokens = estimate_message_tokens(messages)
    print(
        f"   Message list ({len(messages)} messages):"
        f" ~{msg_tokens} tokens"
    )

    # ------------------------------------------------------------------
    # 4. Microcompact — clear old tool results.
    # ------------------------------------------------------------------
    print("\n4. Microcompact — clearing old tool results:")

    conversation = [
        {"role": "user", "content": "Find all test files"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "I'll search for test files."},
            {"type": "tool_use", "id": "tu_1",
             "name": "Bash",
             "input": {"command": "find . -name '*test*'"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "tool_name": "Bash",
             "content": "x" * 500},  # Large result
        ]},
        {"role": "assistant", "content": "Found many test files. Let me read one."},
        {"role": "user", "content": "Read the main test file please."},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Reading the file now."},
            {"type": "tool_use", "id": "tu_2",
             "name": "Read",
             "input": {"file_path": "tests/test_main.py"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_2", "tool_name": "Read",
             "content": "y" * 300},  # Recent result
        ]},
        {"role": "assistant", "content": "Here's the test file content."},
        {"role": "user", "content": "Now fix the failing test."},
    ]

    conv_tokens = estimate_message_tokens(conversation)
    print(
        f"   Original: {len(conversation)} messages,"
        f" ~{conv_tokens} tokens"
    )
    compacted = microcompact(conversation, keep_recent=3)
    print(f"   After microcompact (keep_recent=3): ~{estimate_message_tokens(compacted)} tokens")
    print(f"   Tokens saved: ~{getattr(compacted, 'tokens_saved', 0)}")
    print(f"   Compactable tools: {sorted(COMPACTABLE_TOOLS)[:6]}...")

    # ------------------------------------------------------------------
    # 5. AutoCompactor with circuit breaker.
    # ------------------------------------------------------------------
    print("\n5. AutoCompactor with circuit breaker:")

    budget2 = TokenBudget(max_tokens=200_000, reserve=13_000)
    # Simulate high usage to trigger compaction
    budget2.record_usage(input_tokens=170_000, output_tokens=5_000)

    compactor = AutoCompactor(
        token_budget=budget2,
        max_consecutive_failures=3,
        model="claude-sonnet-4-6",
    )

    print(f"   Compact threshold: {compactor.compact_threshold:,}")
    print(f"   Warning threshold: {compactor.warning_threshold:,}")
    print(f"   Circuit open: {compactor.circuit_open}")
    print(f"   Should compact: {compactor.should_compact(conversation)}")

    # Demonstrate compaction with a mock summarizer
    def mock_summarizer(prompt: str) -> str:
        return (
            "Summary: User asked to find and fix test"
            " files. Several test files were found."
            " Currently fixing the main test."
        )

    compacted_msgs, summary = compactor.compact(conversation, mock_summarizer)
    print(f"\n   Compacted {len(conversation)} messages -> {len(compacted_msgs)} messages")
    print(f"   Summary: {summary[:80]}...")

    # Demonstrate circuit breaker
    def failing_summarizer(prompt: str) -> str:
        raise RuntimeError("LLM API error")

    print("\n   Simulating 3 consecutive failures to trip circuit breaker:")
    for i in range(3):
        try:
            compactor.compact(conversation, failing_summarizer)
        except RuntimeError:
            print(f"     Failure {i+1}: circuit_open={compactor.circuit_open}")

    print(f"   Circuit breaker tripped: {compactor.circuit_open}")

    # Reset
    compactor.reset_circuit_breaker()
    print(f"   After reset: circuit_open={compactor.circuit_open}")

    # ------------------------------------------------------------------
    # 6. Post-compact file restoration.
    # ------------------------------------------------------------------
    print("\n6. Post-compact file restoration:")

    recent_files = [
        {"path": "/project/src/main.py", "content": "def main():\n    print('hello')\n" * 10},
        {"path": "/project/tests/test_main.py",
         "content": "def test_main():\n    assert True\n" * 5},
    ]

    skills_data = [
        {"name": "commit", "definition": "# Commit Skill\nCreate conventional commits..."},
    ]

    restored = restore_files_after_compact(
        compacted_msgs,
        recent_files=recent_files,
        skills=skills_data,
    )
    print(f"   Before restoration: {len(compacted_msgs)} messages")
    print(f"   After restoration: {len(restored)} messages")
    print(f"   Max files to restore: {POST_COMPACT_MAX_FILES_TO_RESTORE}")
    print(f"   File token budget: {POST_COMPACT_TOKEN_BUDGET:,}")

    # ------------------------------------------------------------------
    # 7. Token budget parsing ("+500k" syntax).
    # ------------------------------------------------------------------
    print("\n7. Token budget parsing:")
    test_cases = [
        "+500k",
        "use 2M tokens",
        "spend 1.5M tokens",
        "allocate 100k",
        "just do it",  # No budget
    ]
    for text in test_cases:
        parsed = parse_token_budget(text)
        find_token_budget_positions(text)
        print(f"   '{text}' -> {parsed:,} tokens" if parsed else f"   '{text}' -> None")

    # Budget continuation message
    msg = get_budget_continuation_message(pct=0.75, turn_tokens=5000, budget=500_000)
    print(f"\n   Budget status (75%): {msg}")

    msg = get_budget_continuation_message(pct=0.95, turn_tokens=8000, budget=500_000)
    print(f"   Budget status (95%): {msg}")

    # ------------------------------------------------------------------
    # 8. OutputRecoveryLoop — retry on max_tokens truncation.
    # ------------------------------------------------------------------
    print("\n8. OutputRecoveryLoop — max_tokens retry:")

    loop = OutputRecoveryLoop(max_retries=3)

    # Simulate a truncated response
    truncated_response = {"stop_reason": "max_tokens", "content": "partial output..."}
    normal_response = {"stop_reason": "end_turn", "content": "complete output"}

    print(f"   Truncated response: should_retry={loop.should_retry(truncated_response)}")
    print(f"   Truncated again: should_retry={loop.should_retry(truncated_response)}")
    print(f"   Normal response: should_retry={loop.should_retry(normal_response)}")

    loop.reset()
    print(f"   After reset, truncated: should_retry={loop.should_retry(truncated_response)}")

    # RetryConfig and backoff
    config = RetryConfig(max_retries=3, initial_backoff_ms=200, max_backoff_ms=5000)
    print("\n   Backoff delays: ", end="")
    for attempt in range(4):
        delay = compute_backoff_ms(attempt, config)
        print(f"{delay}ms", end=" ")
    print()

    # Retryable status codes
    print(f"   is_retryable_status(429) = {is_retryable_status(429)}")
    print(f"   is_retryable_status(200) = {is_retryable_status(200)}")
    print(f"   is_retryable_status(503) = {is_retryable_status(503)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
