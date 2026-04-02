# CLI Reference

AutoHarness provides a command-line interface for managing constitutions, checking tool calls, auditing governance decisions, and integrating with development tools.

## `autoharness init`

Generate a starter constitution file.

```bash
# Interactive template selection
autoharness init

# Specific template
autoharness init --template strict

# Available templates: default, minimal, strict, soc2, hipaa, financial
```

Creates `constitution.yaml` in the current directory.

## `autoharness validate`

Validate a constitution file for syntax and semantic errors.

```bash
autoharness validate constitution.yaml
```

Checks:

- YAML syntax
- Required fields present
- Permission policies are valid
- Risk thresholds map to known actions
- Pattern regexes compile

## `autoharness check`

Check a tool call against your constitution rules.

```bash
# From stdin (JSON)
echo '{"tool_name": "Bash", "tool_input": {"command": "rm -rf ~"}}' \
    | autoharness check --stdin --format json

# With a specific constitution
echo '{"tool_name": "Bash", "tool_input": {"command": "ls"}}' \
    | autoharness check --stdin --constitution constitution.yaml
```

Output formats: `text` (default), `json`.

### Example output

```json
{
  "action": "deny",
  "risk_level": "critical",
  "reason": "Input matches denied pattern: rm -rf",
  "matched_rules": ["dangerous_command_rm_rf"]
}
```

## `autoharness audit`

View and manage the audit trail.

### `autoharness audit summary`

Display a summary of governance decisions.

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

### `autoharness audit report`

Generate a detailed report.

```bash
# HTML report for compliance review
autoharness audit report --format html --output report.html

# JSON report for programmatic consumption
autoharness audit report --format json
```

### `autoharness audit check`

Validate audit log integrity.

```bash
autoharness audit check
```

### `autoharness audit clean`

Remove old audit entries.

```bash
autoharness audit clean --older-than 30d
```

## `autoharness install`

Install AutoHarness as a hook for supported tools.

```bash
# Install as Claude Code pre/post tool-use hook
autoharness install --target claude-code
```

This registers AutoHarness in `.claude/settings.json` as a shell hook that runs on every tool call.

## `autoharness export`

Export your constitution for use with other tools.

```bash
# Export for Cursor
autoharness export --format cursor

# Export for Windsurf
autoharness export --format windsurf
```

## `autoharness version`

Display the installed version.

```bash
autoharness version
```

```
AutoHarness v0.1.0
```

## Global options

| Option | Description |
|--------|-------------|
| `--help` | Show help for any command |
| `--constitution PATH` | Override constitution file (for `check`) |
| `--format FORMAT` | Output format: `text`, `json`, `html` |
