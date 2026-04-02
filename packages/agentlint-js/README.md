# autoharness

AI agent behavioral governance middleware for Node.js. TypeScript port of [AutoHarness](https://github.com/aiming-lab/AutoHarness) (Python).

Intercepts and governs AI agent tool calls (Bash, file write, etc.) using regex-based risk classification, hook-based guardrails, permission policies, and JSONL audit logging.

## Install

```bash
npm install autoharness
```

## Quick Start

### Standalone tool call linting

```ts
import { lintToolCall } from "autoharness";

// Blocked: destructive command
const result = lintToolCall("Bash", { command: "rm -rf /" });
console.log(result.status); // "blocked"
console.log(result.blockedReason); // "rm -rf / — recursive force-delete from root"

// Allowed: safe command
const safe = lintToolCall("Bash", { command: "git status" });
console.log(safe.status); // "success"
```

### Wrap an Anthropic client

```ts
import Anthropic from "@anthropic-ai/sdk";
import { AutoHarness } from "autoharness";

const client = AutoHarness.wrap(new Anthropic(), {
  constitution: "constitution.yaml", // or omit for defaults
});

// Use client.messages.create() as normal — tool calls are governed
```

### Wrap an OpenAI client

```ts
import OpenAI from "openai";
import { AutoHarness } from "autoharness";

const client = AutoHarness.wrap(new OpenAI(), {
  constitution: { rules: [{ id: "no-rm-rf", description: "No rm -rf" }] },
});
```

### Standalone pipeline

```ts
import { AutoHarness } from "autoharness";

const pipeline = AutoHarness.fromConstitution();

const decision = pipeline.evaluate({
  toolName: "Bash",
  toolInput: { command: "sudo rm -rf /" },
  metadata: {},
  timestamp: new Date(),
});

console.log(decision.action); // "deny"
pipeline.close();
```

### Custom hooks

```ts
import { hook, AutoHarness } from "autoharness";

const myScanner = hook("pre_tool_use", "my_scanner", (toolCall, risk, ctx) => {
  if (toolCall.toolInput.command?.includes("prod")) {
    return { action: "deny", reason: "No production commands", severity: "error" };
  }
  return { action: "allow" };
});
```

## Constitution (YAML)

```yaml
version: "1.0"
identity:
  name: my-project
  description: Project governance rules

rules:
  - id: no-force-push
    description: Never force-push to main
    severity: error
    enforcement: hook

permissions:
  defaults:
    unknownTool: ask
  tools:
    bash:
      policy: restricted
      denyPatterns:
        - 'git\s+push\s+.*--force\s+.*main'

risk:
  classifier: rules
  thresholds:
    low: allow
    medium: ask
    high: deny
    critical: deny

hooks:
  profile: standard

audit:
  enabled: true
  output: .autoharness/audit.jsonl
```

## Built-in Risk Rules

65 regex patterns covering:

- **Bash**: rm -rf, fork bombs, sudo, git force-push, pipe-to-shell, disk tools
- **File write**: .env, SSH keys, AWS credentials, CI configs, Dockerfiles
- **File read**: private keys, credential files
- **Secrets in content**: API keys (OpenAI, Anthropic, GitHub, AWS, Slack), JWTs, DB URLs

## Architecture

```
ToolCall -> RiskClassifier -> HookRegistry -> PermissionEngine -> AuditEngine
              (65 regex)      (5 built-in)    (8-priority cascade)  (JSONL)
```

The 8-step pipeline:
1. Parse and validate the tool call
2. Classify risk (regex pattern matching)
3. Run pre-hooks (secret scanner, path guard, risk gate, config protector)
4. Check for hook denials
5. Make permission decision (merge risk + hooks + constitution rules)
6. Execute tool (via callback)
7. Run post-hooks (output sanitizer)
8. Audit log

## API Reference

| Export | Description |
|--------|-------------|
| `AutoHarness.wrap(client, options)` | Wrap Anthropic/OpenAI client with governance |
| `AutoHarness.fromConstitution(options)` | Create standalone pipeline |
| `lintToolCall(name, input, options)` | One-shot governance check |
| `Constitution.load(path)` | Load from YAML file |
| `Constitution.default()` | Sensible defaults |
| `RiskClassifier` | Regex-based risk classifier |
| `PermissionEngine` | 3-level permission model |
| `HookRegistry` | Hook lifecycle management |
| `AuditEngine` | JSONL audit logging |
| `hook(event, name, fn)` | Register custom hooks |

## License

MIT
