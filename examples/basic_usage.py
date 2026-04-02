#!/usr/bin/env python3
"""Basic AutoHarness Usage — the simplest possible integration.

This example shows how to:
  1. Create a governance pipeline with default rules
  2. Evaluate tool calls (both safe and dangerous)
  3. Use the one-shot lint_tool_call() helper
  4. Print audit summaries

Run:
    python examples/basic_usage.py
"""

from autoharness import Constitution, ToolGovernancePipeline
from autoharness.core.types import ToolCall


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Create a pipeline with the built-in default constitution.
    #    This includes rules for secret detection, destructive command
    #    blocking, path traversal protection, and more.
    # ------------------------------------------------------------------
    constitution = Constitution.default()
    pipeline = ToolGovernancePipeline(constitution)

    print("=" * 60)
    print("AutoHarness Basic Usage Demo")
    print("=" * 60)
    print(f"\nPipeline: {pipeline}")
    print(f"Constitution: {constitution}")

    # ------------------------------------------------------------------
    # 2. Evaluate a safe tool call.
    #    This should pass all governance checks and be allowed.
    # ------------------------------------------------------------------
    safe_call = ToolCall(
        tool_name="Bash",
        tool_input={"command": "ls -la"},
    )

    print("\n--- Safe tool call ---")
    print(f"Tool: {safe_call.tool_name}")
    print(f"Input: {safe_call.tool_input}")

    result = pipeline.process(safe_call)
    print(f"Status: {result.status}")
    print(f"Output: {result.output}")

    # ------------------------------------------------------------------
    # 3. Evaluate a dangerous tool call.
    #    rm -rf / should be classified as high/critical risk and blocked.
    # ------------------------------------------------------------------
    dangerous_call = ToolCall(
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
    )

    print("\n--- Dangerous tool call ---")
    print(f"Tool: {dangerous_call.tool_name}")
    print(f"Input: {dangerous_call.tool_input}")

    result = pipeline.process(dangerous_call)
    print(f"Status: {result.status}")
    print(f"Blocked reason: {result.blocked_reason}")

    # ------------------------------------------------------------------
    # 4. Evaluate a tool call that contains a secret.
    #    The built-in secret scanner will detect the API key and block it.
    # ------------------------------------------------------------------
    secret_call = ToolCall(
        tool_name="Bash",
        tool_input={"command": "curl -H 'Authorization: Bearer sk-abc123def456ghi789jkl012mno345' https://api.example.com"},
    )

    print("\n--- Tool call with secret ---")
    print(f"Tool: {secret_call.tool_name}")

    result = pipeline.process(secret_call)
    print(f"Status: {result.status}")
    print(f"Blocked reason: {result.blocked_reason}")

    # ------------------------------------------------------------------
    # 5. Batch evaluation — process multiple tool calls at once.
    # ------------------------------------------------------------------
    print("\n--- Batch evaluation ---")

    batch_calls = [
        ToolCall(tool_name="Bash", tool_input={"command": "echo hello"}),
        ToolCall(tool_name="Bash", tool_input={"command": "git push --force origin main"}),
        ToolCall(tool_name="Bash", tool_input={"command": "python -m pytest"}),
    ]

    results = pipeline.process_batch(batch_calls)
    for tc, res in zip(batch_calls, results, strict=False):
        cmd = tc.tool_input.get("command", "")
        status_label = f"{res.status}"
        if res.blocked_reason:
            status_label += f" ({res.blocked_reason[:60]}...)"
        print(f"  '{cmd}' -> {status_label}")

    # ------------------------------------------------------------------
    # 6. Use evaluate() for a dry-run check (no execution, no audit).
    #    Returns a PermissionDecision with action, reason, and source.
    # ------------------------------------------------------------------
    print("\n--- Dry-run evaluation ---")

    decision = pipeline.evaluate(
        ToolCall(tool_name="Bash", tool_input={"command": "echo hello"})
    )
    print(f"'echo hello' -> action={decision.action}, source={decision.source}")

    decision = pipeline.evaluate(
        ToolCall(tool_name="Bash", tool_input={"command": "rm -rf /"})
    )
    print(f"'rm -rf /'   -> action={decision.action}, reason={decision.reason}")

    # ------------------------------------------------------------------
    # 7. Print audit summary.
    #    The pipeline tracks all processed calls for the session.
    # ------------------------------------------------------------------
    print("\n--- Audit Summary ---")
    summary = pipeline.get_audit_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")

    print("\nDone.")


if __name__ == "__main__":
    main()
