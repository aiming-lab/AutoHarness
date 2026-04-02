# API Reference: Observability

## `AuditEngine`

```python
from autoharness.core.audit import AuditEngine
```

Structured JSONL audit trail with streaming read and rotation support.

### Constructor

```python
AuditEngine(output_path: str = ".autoharness/audit.jsonl", enabled: bool = True, retention_days: int = 30)
```

### Methods

#### `log(tool_call, risk, pre_hooks, permission, result, post_hooks, session_id=None) -> None`

Log a complete tool execution cycle (call -> result).

#### `get_summary(session_id: str | None = None) -> dict`

Return summary statistics from the audit log. Returns a dict with keys: `total_calls`, `blocked_count`, `error_count`, `risk_distribution`, `top_blocked_reasons`, `tools_used`, `session_duration_seconds`.

#### `get_records(session_id=None, event_type=None, limit=100) -> list[AuditRecord]`

Read and return audit records from the log file (most recent first).

#### `stream_records(session_id=None, event_type=None, offset=0, limit=None) -> Iterator[AuditRecord]`

Stream audit records without loading the entire file into memory.

### Audit entry format

Each JSONL line contains:

```json
{
  "timestamp": "2026-03-31T21:34:00Z",
  "session_id": "a1b2c3d4",
  "tool_name": "Bash",
  "tool_input": {"command": "ls -la"},
  "action": "allow",
  "risk_level": "low",
  "matched_rules": [],
  "decision_chain": ["classify:low", "permit:allow"],
  "duration_ms": 1.2
}
```

## `HookRegistry`

```python
from autoharness import HookRegistry
```

Registry for lifecycle hooks.

### Methods

#### `register(event: str, hook_func: Callable, name: str | None = None, priority: int = 100, timeout: float = 10.0) -> None`

Register a hook function for a lifecycle event. Events: `"pre_tool_use"`, `"post_tool_use"`, `"on_block"`. Lower priority number = runs first.

#### `register_hooks(hooks: list[Callable]) -> None`

Register a list of `@hook`-decorated functions. Each must have a `_hook_event` attribute.

#### `register_shell_hook(event: str, command: str, timeout: float = 10.0, matcher: str | None = None, name: str | None = None) -> None`

Register a shell hook that executes an external command via subprocess (Claude Code Hook I/O Protocol).

#### `run_pre_hooks(tool_call: ToolCall, risk: RiskAssessment, context: dict) -> list[HookResult]`

Run all `pre_tool_use` hooks. Short-circuits on the first `deny` result.

#### `run_post_hooks(tool_call: ToolCall, result: ToolResult, context: dict) -> tuple[ToolResult, list[HookResult]]`

Run all `post_tool_use` hooks after tool execution.

#### `run_block_hooks(tool_call: ToolCall, decision: PermissionDecision, context: dict) -> list[HookResult]`

Run all `on_block` hooks when a tool call is denied.

## `MultiAgentGovernor`

```python
from autoharness import MultiAgentGovernor, AgentProfile
```

Governance for multi-agent setups. Manages role-based permissions and fork governance.

### Constructor

```python
MultiAgentGovernor(constitution: Constitution)
```

### Methods

#### `evaluate(agent: AgentProfile, tool_call: ToolCall) -> HookResult`

Evaluate a tool call in the context of a specific agent role.

## Performance constants

| Constant | Value | Description |
|----------|-------|-------------|
| `SLOW_PHASE_LOG_THRESHOLD_MS` | 2,000 | Log warning for slow pipeline phases |
| `HOOK_TIMING_DISPLAY_THRESHOLD_MS` | 500 | Display timing for slow hooks |
