# AutoHarness GitHub Action

Validate AI agent tool calls against governance rules defined in a constitution file. Catches unsafe agent behaviors (destructive commands, secret exposure, unauthorized access) before they reach production.

## Usage

```yaml
- uses: autoharness/autoharness@v1
  with:
    constitution: 'constitution.yaml'
    max-blocks: '0'
```

### Full workflow example

```yaml
name: Agent Governance
on: [push, pull_request]

jobs:
  autoharness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: autoharness/autoharness@v1
        with:
          constitution: 'constitution.yaml'
          max-blocks: '0'
          audit-output: 'autoharness-report.json'
```

## Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `constitution` | Path to constitution.yaml | No | `constitution.yaml` |
| `max-blocks` | Maximum allowed blocked actions (0 = fail on any block) | No | `0` |
| `audit-output` | Path to write audit report | No | — |
| `version` | AutoHarness version to install | No | latest |

## What it does

1. **Installs** AutoHarness from PyPI
2. **Validates** your constitution file for syntax and rule correctness
3. **Audits** recorded tool calls against your governance rules, failing the check if blocked actions exceed `max-blocks`

## Constitution file

See the [AutoHarness documentation](https://github.com/aiming-lab/AutoHarness) for the full constitution schema and examples.
