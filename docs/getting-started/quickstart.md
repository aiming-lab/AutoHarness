# Quickstart

Build your first governed AI agent in five steps.

## 1. Install AutoHarness

```bash
pip install autoharness
```

## 2. Create a constitution

Generate a starter constitution file:

```bash
autoharness init --template default
```

This creates `constitution.yaml` in your project directory:

```yaml
version: "1.0"
identity:
  name: my-agent
  boundaries:
    - "Only modify files within the project directory"
    - "Never access credentials or secret files"

permissions:
  defaults:
    unknown_tool: ask
    unknown_path: deny
    on_error: deny
  tools:
    bash:
      policy: restricted
      deny_patterns: ["rm -rf /", "curl.*| bash"]
      ask_patterns: ["git push --force", "DROP TABLE"]
    file_write:
      policy: restricted
      deny_paths: ["~/.ssh/*", "**/.env"]
      scope: "${PROJECT_DIR}"

risk:
  thresholds:
    low: allow
    medium: ask
    high: ask
    critical: deny

audit:
  enabled: true
  format: jsonl
  output: .autoharness/audit.jsonl
```

## 3. Wrap an existing client

```python
import anthropic
from autoharness import AutoHarness

client = AutoHarness.wrap(
    anthropic.Anthropic(),
    constitution="constitution.yaml",
)

# Use client exactly as before -- governance is transparent
response = client.messages.create(
    model="claude-sonnet-4-6-20250131",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Delete all log files"}],
    tools=[{
        "name": "Bash",
        "description": "Run shell commands",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
        },
    }],
)
```

If the model tries to run `rm -rf /`, the governance pipeline blocks it before execution.

## 4. Or use the full agent loop

```python
from autoharness import AgentLoop

loop = AgentLoop(
    model="claude-sonnet-4-6",
    constitution="constitution.yaml",
)
result = loop.run("Fix the failing tests in auth.py")
print(result)
```

The `AgentLoop` integrates context management, tool orchestration, skill injection, and session tracking -- all governed by your constitution.

## 5. View the audit log

```bash
autoharness audit summary
```

```
Audit Summary
=============
Total decisions: 47
  Allowed: 41 (87.2%)
  Denied:   4 (8.5%)
  Asked:    2 (4.3%)

Top block reasons:
  1. Input matches denied pattern: rm -rf   (2)
  2. Secret detected in output              (1)
  3. Path outside project scope             (1)
```

Or export an HTML report for compliance review:

```bash
autoharness audit report --format html --output report.html
```

## What's next?

- [Configuration](configuration.md) -- customize your constitution
- [Agent Loop](../concepts/agent-loop.md) -- understand how all subsystems connect
- [Governance Pipeline](../concepts/governance.md) -- learn the 14-step pipeline
- [Wrap an Existing Client](../guides/wrap-client.md) -- detailed integration guide
