# Configuration

AutoHarness is configured through a YAML **constitution** file. The constitution defines your agent's identity, behavioral rules, permissions, risk thresholds, and audit settings.

## Constitution structure

```yaml
version: "1.0"

identity:
  name: my-agent
  boundaries:
    - "Only modify files within the project directory"
    - "Never access credentials or secret files"

permissions:
  defaults:
    unknown_tool: ask     # ask | allow | deny
    unknown_path: deny
    on_error: deny        # Never fail open
  tools:
    bash:
      policy: restricted  # open | restricted | locked
      deny_patterns: ["rm -rf /", "curl.*| bash"]
      ask_patterns: ["git push --force", "DROP TABLE"]
    file_write:
      policy: restricted
      deny_paths: ["~/.ssh/*", "**/.env"]
      scope: "${PROJECT_DIR}"

risk:
  thresholds:
    low: allow
    medium: log
    high: ask
    critical: deny

audit:
  enabled: true
  format: jsonl
  output: .autoharness/audit.jsonl
```

## Loading a constitution

```python
from autoharness import Constitution

# From a YAML file
const = Constitution.load("constitution.yaml")

# From a Python dict
const = Constitution.from_dict({
    "version": "1.0",
    "permissions": {"defaults": {"on_error": "deny"}},
})

# Auto-discover (searches cwd, then ~/.autoharness/)
const = Constitution.default()
```

## Constitution discovery

AutoHarness searches for a constitution in this order:

1. Explicit path passed to `AgentLoop(constitution=...)` or `AutoHarness.wrap(..., constitution=...)`
2. `constitution.yaml` in the current working directory
3. `.autoharness/constitution.yaml` in the project directory
4. `~/.autoharness/constitution.yaml` (global)
5. Built-in defaults

## Templates

Generate a constitution from built-in templates:

```bash
# Interactive template selection
autoharness init

# Specific template
autoharness init --template strict
```

Available templates:

| Template | Description |
|----------|-------------|
| `default` | Essential safety rules with sensible defaults |
| `minimal` | Bare essentials -- fastest path to governance |
| `strict` | Maximum enforcement -- all rules block, all tools audited |
| `soc2` | SOC 2 compliance: audit everything, restrict destructive ops |
| `hipaa` | HIPAA-aware: PHI path protection, strict access controls |
| `financial` | Financial services: PCI-DSS patterns, transaction safety |

## Validate a constitution

```bash
autoharness validate constitution.yaml
```

## Key configuration sections

### Identity

Defines your agent's name and behavioral boundaries. Boundaries are compiled into the system prompt to guide the LLM.

### Permissions

Controls what each tool can do:

- **`policy: open`** -- tool can do anything
- **`policy: restricted`** -- tool is checked against deny/ask patterns
- **`policy: locked`** -- tool is completely disabled

`deny_patterns` and `ask_patterns` are regular expressions matched against tool inputs.

### Risk thresholds

Maps risk levels to actions. Every tool call is risk-classified by the 79 built-in regex patterns before the permission check runs.

### Audit

Controls the JSONL audit trail. Every governance decision (allow, deny, ask) is logged with the full decision chain, matched rules, and risk classification.

!!! warning
    Setting `on_error: allow` in permissions defaults is strongly discouraged. The fail-open posture means any parsing error silently allows tool execution.

## Feature flags

The feature flag system (`core/feature_flags.py`) provides runtime toggles for experimental or optional features. Flags can be set programmatically or overridden via environment variables.

```python
from autoharness.core.feature_flags import FeatureFlags

flags = FeatureFlags()
flags.set("anti_distillation", True)
flags.set("frustration_detection", True)

# Check a flag
if flags.is_enabled("anti_distillation"):
    # Enable decoy tool injection
    ...
```

Environment variable overrides use the prefix `AUTOHARNESS_FF_`:

```bash
# Enable anti-distillation via env var
export AUTOHARNESS_FF_ANTI_DISTILLATION=true

# Disable frustration detection
export AUTOHARNESS_FF_FRUSTRATION_DETECTION=false
```

Environment variables take precedence over programmatic settings, making it easy to toggle features per deployment without code changes.

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | API key for Anthropic models |
| `AUTOHARNESS_HOOK_PROFILE` | Hook profile: `minimal`, `standard`, `strict` |
| `AUTOHARNESS_DISABLED_HOOKS` | Comma-separated hook IDs to disable |
| `AUTOHARNESS_FF_*` | Feature flag overrides (e.g., `AUTOHARNESS_FF_ANTI_DISTILLATION=true`) |
| `AUTOHARNESS_MODEL_TIER` | Override default model routing tier: `FAST`, `STANDARD`, `PREMIUM` |

## Next steps

- [Governance Pipeline](../concepts/governance.md) -- how rules are enforced at runtime
- [Tool System](../concepts/tools.md) -- register custom tools with governance
