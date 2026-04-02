#!/usr/bin/env python3
"""Custom Hooks — write your own governance rules as Python functions.

This example shows how to:
  1. Write custom pre-tool-use hooks for domain-specific rules
  2. Register hooks with the pipeline via the @hook decorator
  3. Register hooks programmatically via the HookRegistry
  4. Combine custom hooks with built-in hooks

Hook function signatures:
  pre_tool_use:  (tool_call: ToolCall, risk: RiskAssessment, context: dict) -> HookResult
  post_tool_use: (tool_call: ToolCall, result: ToolResult, context: dict) -> HookResult
  on_block:      (tool_call: ToolCall, decision: PermissionDecision, context: dict) -> None

Run:
    python examples/custom_hooks.py
"""

import re
from datetime import datetime, timezone

from autoharness import Constitution, HookResult, ToolGovernancePipeline
from autoharness.core.types import (
    HookAction,
    PermissionDecision,
    RiskAssessment,
    ToolCall,
)

# ======================================================================
# Hook 1: Block production database access
# ======================================================================
# This hook scans Bash commands for connection strings or CLI flags
# that target production databases. It prevents accidental data
# destruction in prod environments.

PROD_DB_PATTERNS = [
    re.compile(r"--host[= ].*prod", re.IGNORECASE),
    re.compile(r"psql\s+.*prod", re.IGNORECASE),
    re.compile(r"mysql\s+.*prod", re.IGNORECASE),
    re.compile(r"mongosh?\s+.*prod", re.IGNORECASE),
    re.compile(r"redis-cli\s+.*prod", re.IGNORECASE),
    re.compile(r"DATABASE_URL=.*prod", re.IGNORECASE),
]


def production_db_guard(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict,
) -> HookResult:
    """Block any tool call that appears to target a production database."""
    # Only check shell commands
    if tool_call.tool_name not in ("Bash", "bash", "shell"):
        return HookResult(action=HookAction.allow)

    command = tool_call.tool_input.get("command", "")

    for pattern in PROD_DB_PATTERNS:
        if pattern.search(command):
            return HookResult(
                action=HookAction.deny,
                reason=f"Production database access blocked: command matches '{pattern.pattern}'",
                severity="error",
            )

    return HookResult(action=HookAction.allow)


# ======================================================================
# Hook 2: Cost tracking context
# ======================================================================
# This hook doesn't block anything — it enriches the context with
# cost tracking metadata. Useful for monitoring how many tool calls
# an agent session is making, which feeds into cost dashboards.

_call_counter = 0


def cost_tracker(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict,
) -> HookResult:
    """Track tool call counts for cost monitoring. Never blocks."""
    global _call_counter
    _call_counter += 1

    # Log the call for cost tracking (in production you'd write to a metrics system)
    print(f"  [cost-tracker] Call #{_call_counter}: {tool_call.tool_name}")

    # Always allow — this hook is purely observational
    return HookResult(
        action=HookAction.allow,
        reason=f"Cost tracking: call #{_call_counter}",
        severity="info",
    )


# ======================================================================
# Hook 3: Working hours enforcement
# ======================================================================
# This hook restricts dangerous operations to business hours (9-17 UTC).
# Safe, read-only operations are always allowed. Only write/execute
# operations are restricted outside working hours.

WRITE_TOOLS = {"Bash", "bash", "shell", "Edit", "Write", "file_write", "file_edit"}


def working_hours_guard(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict,
) -> HookResult:
    """Restrict write/execute operations to business hours (9-17 UTC)."""
    # Read-only tools are always fine
    if tool_call.tool_name not in WRITE_TOOLS:
        return HookResult(action=HookAction.allow)

    now = datetime.now(timezone.utc)
    hour = now.hour

    if 9 <= hour < 17:
        return HookResult(
            action=HookAction.allow,
            reason=f"Within working hours (UTC {hour}:00)",
            severity="info",
        )

    # Outside working hours: block write operations
    return HookResult(
        action=HookAction.deny,
        reason=(
            f"Write/execute operations are restricted outside business hours "
            f"(current UTC time: {now.strftime('%H:%M')}; allowed: 09:00-17:00)"
        ),
        severity="warning",
    )


# ======================================================================
# Hook 4: Block notification hook (on_block event)
# ======================================================================
# This fires whenever a tool call is blocked by any hook or rule.
# Use it for alerting, logging to external systems, or sending
# notifications to a Slack channel.

def block_notifier(
    tool_call: ToolCall,
    decision: PermissionDecision,
    context: dict,
) -> None:
    """Log a warning whenever a tool call is blocked."""
    print(
        f"  [ALERT] Blocked: {tool_call.tool_name} "
        f"(reason: {decision.reason}, source: {decision.source})"
    )
    # In production, you might:
    #   - Send a Slack/Teams notification
    #   - Write to an external audit log
    #   - Increment a monitoring metric
    #   - Trigger a PagerDuty alert for critical blocks


# ======================================================================
# Main: register hooks and test them
# ======================================================================


def main() -> None:
    print("=" * 60)
    print("AutoHarness Custom Hooks Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Create a pipeline and get its hook registry
    # ------------------------------------------------------------------
    constitution = Constitution.default()
    pipeline = ToolGovernancePipeline(constitution)
    registry = pipeline.hook_registry

    # ------------------------------------------------------------------
    # Register our custom hooks programmatically.
    # This adds them alongside the built-in hooks (secret scanner,
    # path guard, etc.) that are already registered.
    # ------------------------------------------------------------------
    registry.register("pre_tool_use", production_db_guard, name="production_db_guard")
    registry.register("pre_tool_use", cost_tracker, name="cost_tracker")
    # Note: working_hours_guard is commented out so this example works
    # at any time of day. Uncomment to test:
    # registry.register("pre_tool_use", working_hours_guard, name="working_hours_guard")
    registry.register("on_block", block_notifier, name="block_notifier")

    # ------------------------------------------------------------------
    # Show all registered hooks
    # ------------------------------------------------------------------
    print("\nRegistered hooks:")
    for event, hook_names in registry.list_hooks().items():
        if hook_names:
            print(f"  {event}: {', '.join(hook_names)}")

    # ------------------------------------------------------------------
    # Test 1: Safe command — should pass all hooks
    # ------------------------------------------------------------------
    print("\n--- Test 1: Safe command ---")
    result = pipeline.process(
        ToolCall(tool_name="Bash", tool_input={"command": "echo hello"})
    )
    print(f"Result: {result.status}")

    # ------------------------------------------------------------------
    # Test 2: Production database access — blocked by our custom hook
    # ------------------------------------------------------------------
    print("\n--- Test 2: Production database access ---")
    result = pipeline.process(
        ToolCall(
            tool_name="Bash",
            tool_input={"command": "psql --host=db.prod.internal -c 'DROP TABLE users'"},
        )
    )
    print(f"Result: {result.status}")
    print(f"Reason: {result.blocked_reason}")

    # ------------------------------------------------------------------
    # Test 3: Secret in command — blocked by built-in secret scanner
    # ------------------------------------------------------------------
    print("\n--- Test 3: Secret in command ---")
    result = pipeline.process(
        ToolCall(
            tool_name="Bash",
            tool_input={"command": "export API_KEY=sk-proj-abc123def456ghi789jkl012"},
        )
    )
    print(f"Result: {result.status}")
    print(f"Reason: {result.blocked_reason}")

    # ------------------------------------------------------------------
    # Test 4: Multiple tool calls — cost tracker counts them
    # ------------------------------------------------------------------
    print("\n--- Test 4: Multiple calls (cost tracking) ---")
    for cmd in ["ls", "pwd", "date"]:
        pipeline.process(
            ToolCall(tool_name="Bash", tool_input={"command": cmd})
        )
    print(f"Total calls tracked: {_call_counter}")

    print("\nDone.")


if __name__ == "__main__":
    main()
