#!/usr/bin/env python3
"""AutoHarness Quickstart — minimal working example.

Shows how to use AutoHarness as governance middleware wrapping
an Anthropic API client. No API key required for the demo.

Run:
    python examples/quickstart.py
"""

from autoharness import Constitution, ToolGovernancePipeline
from autoharness.core.types import ToolCall


def main() -> None:
    print("=" * 60)
    print("AutoHarness Quickstart")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Create a Constitution from a minimal YAML string.
    #
    # The constitution defines what your agent is allowed to do.
    # Here we define a simple rule set: block destructive commands
    # and detect secrets in tool inputs.
    # ------------------------------------------------------------------
    yaml_config = """\
identity:
  name: quickstart-demo
  version: "0.1"

rules:
  - id: no-destructive-commands
    description: Block commands that could destroy data
    enforcement: hook
    severity: error
    triggers:
      - tool: Bash
        pattern: "rm\\\\s+-rf\\\\s+/|DROP\\\\s+TABLE|FORMAT C:"

  - id: no-secrets
    description: Block API keys and tokens from being passed in commands
    enforcement: hook
    severity: error

permissions:
  defaults:
    allow_by_default: true

hooks:
  profile: standard
"""

    constitution = Constitution.from_yaml(yaml_config)
    print(f"\n1. Created constitution: {constitution}")

    # ------------------------------------------------------------------
    # Step 2: Set up the governance pipeline.
    #
    # The pipeline is the central engine that evaluates every tool call
    # against the constitution's rules, risk assessments, and hooks.
    # ------------------------------------------------------------------
    pipeline = ToolGovernancePipeline(constitution)
    print(f"2. Pipeline ready: {pipeline}")

    # ------------------------------------------------------------------
    # Step 3: Check a safe tool call.
    #
    # A simple 'ls' command should pass all governance checks.
    # ------------------------------------------------------------------
    safe_call = ToolCall(
        tool_name="Bash",
        tool_input={"command": "ls -la /tmp"},
    )

    print("\n3. Checking safe tool call: Bash('ls -la /tmp')")
    result = pipeline.process(safe_call)
    print(f"   Status: {result.status}")
    print(f"   Output: {result.output}")

    # ------------------------------------------------------------------
    # Step 4: Check a dangerous tool call.
    #
    # 'rm -rf /' should be blocked by our constitution rules.
    # ------------------------------------------------------------------
    dangerous_call = ToolCall(
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
    )

    print("\n4. Checking dangerous tool call: Bash('rm -rf /')")
    result = pipeline.process(dangerous_call)
    print(f"   Status: {result.status}")
    print(f"   Blocked: {result.blocked_reason}")

    # ------------------------------------------------------------------
    # Step 5: Check a tool call with the default constitution.
    #
    # Constitution.default() includes the built-in secret scanner,
    # destructive command blocking, and more.
    # ------------------------------------------------------------------
    default_constitution = Constitution.default()
    default_pipeline = ToolGovernancePipeline(default_constitution)

    secret_call = ToolCall(
        tool_name="Bash",
        tool_input={
            "command": "curl -H 'Authorization: Bearer sk-abc123def456ghi789jkl012mno345' https://api.example.com"
        },
    )

    print("\n5. Default constitution with secret scanner:")
    result = default_pipeline.process(secret_call)
    print(f"   Status: {result.status}")
    print(f"   Blocked: {result.blocked_reason}")

    # ------------------------------------------------------------------
    # Step 6: Dry-run evaluation (no side effects, no audit trail).
    # ------------------------------------------------------------------
    print("\n6. Dry-run evaluations:")
    for cmd, _label in [
        ("echo hello", "safe echo"),
        ("git push --force origin main", "force push"),
        ("python -m pytest", "test runner"),
    ]:
        decision = pipeline.evaluate(
            ToolCall(tool_name="Bash", tool_input={"command": cmd})
        )
        print(f"   '{cmd}' -> {decision.action} (source: {decision.source})")

    # ------------------------------------------------------------------
    # Step 7: Audit summary.
    # ------------------------------------------------------------------
    print("\n7. Audit summary:")
    summary = pipeline.get_audit_summary()
    for key, value in summary.items():
        print(f"   {key}: {value}")

    print("\nDone. AutoHarness evaluated 4 tool calls with zero API keys needed.")


if __name__ == "__main__":
    main()
