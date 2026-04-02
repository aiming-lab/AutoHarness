# Production Deployment

Best practices for running AutoHarness in production environments.

## Constitution for production

Start with the `strict` template and customize:

```bash
autoharness init --template strict
```

Key production settings:

```yaml
version: "1.0"
identity:
  name: production-agent
  boundaries:
    - "Only modify files within ${PROJECT_DIR}"
    - "Never access credentials, secrets, or .env files"
    - "Never run destructive commands without explicit approval"

permissions:
  defaults:
    unknown_tool: deny     # Deny unknown tools in production
    unknown_path: deny
    on_error: deny         # Always fail closed
  tools:
    bash:
      policy: restricted
      deny_patterns:
        - "rm -rf"
        - "curl.*\\| bash"
        - "chmod 777"
        - "sudo"
        - ">/dev/sd"
      ask_patterns:
        - "git push"
        - "docker"
        - "kubectl"

risk:
  thresholds:
    low: allow
    medium: log
    high: deny             # Block high-risk in production
    critical: deny

audit:
  enabled: true
  format: jsonl
  output: /var/log/autoharness/audit.jsonl
```

!!! warning
    Never set `on_error: allow` in production. This creates a fail-open posture where parsing errors silently allow tool execution.

## Environment variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."       # API key
export AUTOHARNESS_HOOK_PROFILE="strict"   # Maximum enforcement
```

## Audit log management

### Log rotation

The audit engine supports log rotation. Configure in your constitution or handle externally:

```bash
# External rotation with logrotate
/var/log/autoharness/audit.jsonl {
    daily
    rotate 30
    compress
    missingok
}
```

### Compliance reports

Generate HTML reports for compliance review:

```bash
autoharness audit report --format html --output /var/www/reports/audit.html
```

## Monitoring

### Health checks

```python
from autoharness import AgentLoop

loop = AgentLoop(model="claude-sonnet-4-6")

# Check subsystem health
print(f"Tools: {len(loop.tool_registry)}")
print(f"Skills: {len(loop.skill_registry)}")
print(f"Token budget: {loop.token_budget.remaining:,}")
```

### Cost monitoring

```python
cost = loop.session_cost
if cost.total_input_tokens > 500_000:
    alert("Session exceeding token budget")
```

## Error handling

The AgentLoop handles common failure modes:

| Failure | Recovery |
|---------|----------|
| Prompt too long | Reactive compact (emergency compaction) |
| Max output truncated | Automatic retry (up to 3 times) |
| API rate limit | Exponential backoff (200ms to 2s) |
| Auto-compact failure | Circuit breaker after 3 consecutive failures |
| Tool execution error | Error returned to LLM as tool_result |

## Security checklist

- [ ] Constitution uses `on_error: deny`
- [ ] Secret detection is enabled (built-in, always on)
- [ ] Audit logging is enabled and writing to a persistent location
- [ ] Path scoping is set to `${PROJECT_DIR}`
- [ ] API keys are in environment variables, not in code
- [ ] `unknown_tool: deny` for production constitutions
- [ ] Hook profile is `standard` or `strict`

## Claude Code integration

Install AutoHarness as a Claude Code hook with one command:

```bash
autoharness install --target claude-code
```

This registers AutoHarness as a pre/post tool-use hook in `.claude/settings.json`.

## Related pages

- [Configuration](../getting-started/configuration.md) -- constitution reference
- [Observability](../concepts/observability.md) -- audit and monitoring
- [Governance Pipeline](../concepts/governance.md) -- understanding enforcement
