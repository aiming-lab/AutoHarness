# AutoHarness — VS Code Extension

AI Agent governance visualization and real-time monitoring for [AutoHarness](https://github.com/aiming-lab/AutoHarness).

## Features

### Audit Log Sidebar
Browse audit records grouped by session. Each record shows tool name, risk level (color-coded), and decision (allow/deny). Click any record to see full details.

### Governance Dashboard
A live dashboard showing:
- Total calls, blocked count, and block rate
- Risk level distribution (bar chart)
- Top block reasons
- Recent actions timeline

Opens via command palette or the sidebar toolbar button. Auto-refreshes every 5 seconds.

### Constitution Validation
Validates `constitution.yaml` files and shows diagnostics in the Problems panel. Uses the `autoharness` CLI when available; falls back to basic YAML structural checks.

Auto-validates on save when `autoharness.autoValidate` is enabled (default: true).

### Initialize Constitution
Scaffolds a starter `constitution.yaml` with common governance rules.

## Commands

| Command | Description |
|---------|-------------|
| `AutoHarness: Show Governance Dashboard` | Open the live dashboard panel |
| `AutoHarness: Show Audit Log` | Open the raw JSONL audit file |
| `AutoHarness: Validate Constitution` | Run validation on the active constitution file |
| `AutoHarness: Initialize Constitution File` | Create a starter constitution.yaml |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `autoharness.auditLogPath` | `audit.jsonl` | Path to the JSONL audit log (relative to workspace) |
| `autoharness.constitutionPath` | `constitution.yaml` | Path to the constitution file |
| `autoharness.autoValidate` | `true` | Validate constitution files on save |

## Getting Started

1. Install the extension
2. Open a workspace that contains an AutoHarness `audit.jsonl` file
3. The AutoHarness sidebar appears in the activity bar
4. Run "AutoHarness: Show Governance Dashboard" for the live overview

## Development

```bash
cd packages/vscode-autoharness
npm install
npm run compile
# Press F5 in VS Code to launch Extension Development Host
```
