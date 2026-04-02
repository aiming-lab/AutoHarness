#!/usr/bin/env python3
"""Anthropic Client Integration — wrap an Anthropic client with AutoHarness governance.

This example shows how to:
  1. Wrap an Anthropic client so all tool_use responses are governed
  2. Use a custom constitution file
  3. Access the governance pipeline for audit/introspection

The wrapped client is a drop-in replacement — use client.messages.create()
exactly as you normally would. AutoHarness intercepts tool_use blocks in the
response and blocks any that violate your constitution.

Prerequisites:
    pip install anthropic autoharness

Run:
    ANTHROPIC_API_KEY=sk-... python examples/anthropic_integration.py

If you don't have an API key, this example includes a mock mode that
demonstrates the wrapping without making real API calls.
"""

import os

from autoharness import AutoHarness, Constitution, ToolGovernancePipeline
from autoharness.core.types import ToolCall


def demo_with_real_client() -> None:
    """Wrap a real Anthropic client and make a governed API call."""
    import anthropic

    # ------------------------------------------------------------------
    # 1. Create the Anthropic client as usual
    # ------------------------------------------------------------------
    raw_client = anthropic.Anthropic()

    # ------------------------------------------------------------------
    # 2. Wrap it with AutoHarness governance.
    #
    #    Options:
    #      constitution=None         -> auto-discover constitution.yaml in cwd
    #      constitution="path.yaml"  -> load from a specific file
    #      constitution={...}        -> inline dict configuration
    #      hooks=[my_hook_fn]        -> add custom Python hooks
    #      project_dir="./myproject" -> scope path guards to this directory
    # ------------------------------------------------------------------
    client = AutoHarness.wrap(
        raw_client,
        constitution=None,  # Uses default constitution (auto-discovery)
    )

    print(f"Wrapped client: {client}")
    print(f"Pipeline: {client.pipeline}")

    # ------------------------------------------------------------------
    # 3. Use the client exactly as normal.
    #    AutoHarness transparently:
    #      a) Injects governance rules into the system prompt
    #      b) Evaluates every tool_use block in the response
    #      c) Blocks tool calls that violate the constitution
    # ------------------------------------------------------------------
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        tools=[
            {
                "name": "Bash",
                "description": "Execute a shell command",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to run"},
                    },
                    "required": ["command"],
                },
            },
        ],
        messages=[
            {"role": "user", "content": "List the files in the current directory"},
        ],
    )

    # ------------------------------------------------------------------
    # 4. Check the response for governance annotations.
    #    Blocked tool calls have _autoharness_blocked = True.
    # ------------------------------------------------------------------
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            blocked = getattr(block, "_autoharness_blocked", False)
            reason = getattr(block, "_autoharness_reason", None)
            if blocked:
                print(f"BLOCKED: {block.name} -> {reason}")
            else:
                print(f"ALLOWED: {block.name}({block.input})")
        elif getattr(block, "type", None) == "text":
            print(f"Text: {block.text[:100]}...")


def demo_with_mock() -> None:
    """Demonstrate wrapping without a real API key.

    This shows the pipeline evaluation directly, which is how AutoHarness
    works internally when it intercepts tool_use blocks.
    """
    print("(Running in mock mode — no ANTHROPIC_API_KEY set)\n")

    # ------------------------------------------------------------------
    # 1. Create a standalone pipeline (no client needed).
    #    ToolGovernancePipeline accepts a Constitution directly.
    # ------------------------------------------------------------------
    constitution = Constitution.default()
    pipeline = ToolGovernancePipeline(constitution)

    print(f"Pipeline: {pipeline}")

    # ------------------------------------------------------------------
    # 2. Simulate what happens when the LLM returns tool_use blocks.
    #    The pipeline evaluates each tool call against the constitution.
    # ------------------------------------------------------------------
    test_cases = [
        # (tool_name, tool_input, expected_outcome)
        ("Bash", {"command": "ls -la"}, "safe listing"),
        ("Bash", {"command": "rm -rf /"}, "filesystem destruction"),
        ("Bash", {"command": "git push --force origin main"}, "force push to main"),
        ("Bash", {"command": "curl https://api.github.com/repos"}, "safe API call"),
        ("Edit", {"file_path": ".env", "content": "SECRET=x"}, "editing secrets file"),
        ("Read", {"file_path": "README.md"}, "safe file read"),
    ]

    print("\nSimulated tool call governance:")
    print("-" * 60)

    for tool_name, tool_input, description in test_cases:
        tc = ToolCall(
            tool_name=tool_name,
            tool_input=tool_input,
            metadata={"provider": "anthropic"},
        )

        decision = pipeline.evaluate(tc)

        status_icon = {
            "allow": "PASS",
            "deny": "DENY",
            "ask": " ASK",
        }.get(decision.action, "????")

        print(f"  [{status_icon}] {description}")
        print(f"         {tool_name}({tool_input})")
        if decision.action != "allow":
            print(f"         Reason: {decision.reason}")
        print()

    # ------------------------------------------------------------------
    # 3. Show how wrapping would work (with a mock client class)
    # ------------------------------------------------------------------
    print("-" * 60)
    print("To wrap a real Anthropic client:")
    print()
    print("    import anthropic")
    print("    from autoharness import AutoHarness")
    print()
    print('    client = AutoHarness.wrap(anthropic.Anthropic())')
    print("    # Use client.messages.create() as normal")
    print("    # Tool calls are automatically governed")
    print()


def main() -> None:
    print("=" * 60)
    print("AutoHarness Anthropic Integration Demo")
    print("=" * 60)
    print()

    if os.environ.get("ANTHROPIC_API_KEY"):
        demo_with_real_client()
    else:
        demo_with_mock()

    print("Done.")


if __name__ == "__main__":
    main()
