# AutoHarness — Feature Deep Dive

This document contains the detailed technical breakdown of every AutoHarness subsystem. For a high-level overview, see the [README](../README.md).

---

## Pipeline Modes

AutoHarness supports three governance modes. The mode controls which pipeline steps are active, which context layers are enabled, and which multi-agent features are available.

### Core Mode (6-step)

The foundational governance pipeline designed from scratch for lightweight, low-overhead governance:

| Step | Name | Description |
|:----:|:-----|:------------|
| 1 | **Parse & Validate** | Extract and validate tool name, input schema |
| 2 | **Risk Classify** | Pattern-based risk assessment (low / medium / high / critical) |
| 3 | **Permission Check** | Evaluate against constitution rules and deny/ask patterns |
| 4 | **Execute** | Run the tool |
| 5 | **Output Sanitize** | Strip secrets and sensitive data from output |
| 6 | **Audit** | Log decision chain to JSONL |

**Context**: Token budget tracking + oldest-first truncation.
**Multi-agent**: Single agent only.

### Standard Mode (8-step)

Adds hook-based extensibility and trace diagnostics:

| Step | Name | Description |
|:----:|:-----|:------------|
| 1 | **Parse & Validate** | Extract and validate tool call structure |
| 2 | **Interface Check** | Validate tool call conforms to declared schema |
| 3 | **Risk Classify** | Pattern-based risk assessment |
| 4 | **Pre-hooks** | Run registered pre-execution hooks (secret scanner, path guard) |
| 5 | **Permission Check** | Merge risk thresholds + hook results + constitution rules |
| 6 | **Execute** | Run the tool |
| 7 | **Post-hooks & Sanitize** | Output sanitization and post-execution hooks |
| 8 | **Audit + Trace** | JSONL audit + filesystem-based execution trace store |

**Context**: Token budget + truncation + microcompact (tool result clearing).
**Multi-agent**: Basic agent profiles (coder / reviewer / planner / executor).
**Trace store**: Full execution traces persisted to filesystem for diagnostics. Raw traces preserve critical diagnostic signal that summaries destroy.

### Enhanced Mode (14-step, default)

The full governance pipeline with all advanced features:

| Step | Name | Description |
|:----:|:-----|:------------|
| 1 | **Turn Governor** | Per-turn rate/budget limits, rejection spiral detection |
| 2 | **Parse & Validate** | Structure and required field validation |
| 3 | **Alias Resolution** | Map tool aliases to canonical names |
| 4 | **Abort Check** | Bail out if pipeline.abort() was called |
| 5 | **Risk Classify** | Regex-based risk assessment |
| 6 | **Pre-hooks** | Secret scanner, path guard, custom hooks |
| 7 | **Hook Denial** | Short-circuit if any hook denies |
| 8 | **Hook Modify** | Apply input rewrites from modify-hooks |
| 9 | **Permission Decision** | Merge risk thresholds + hooks + rules |
| 10 | **Progressive Trust** | Session-level trust escalation with user confirmation |
| 11 | **Execute** | Run the tool via callback |
| 12 | **Post-hooks** | Output sanitization, custom post-processing |
| 13 | **Failure Hooks** | Error handling and cleanup hooks |
| 14 | **Audit** | Full lifecycle logging to JSONL |

**Context**: 5-layer compaction (token budget, microcompact, LLM summarization with circuit breaker, image stripping, post-compact file restoration).
**Multi-agent**: Fork (shared prompt cache, 95% cost reduction), Background (async), Swarm (JSONL mailbox), Coordinator (delegated execution).
**Additional**: Anti-distillation protection, frustration detection, model routing.

### Switching Modes

```yaml
# constitution.yaml
version: "1.0"
mode: enhanced    # core | standard | enhanced (default)
```

```bash
# CLI
autoharness mode                    # Show current mode
autoharness mode core               # Switch to core
autoharness init --mode standard    # Generate constitution with specific mode
```

```python
# Programmatic
from autoharness import ToolGovernancePipeline, Constitution

# Via constitution
c = Constitution.from_yaml("mode: core\n")
pipeline = ToolGovernancePipeline(c)

# Or explicit override
pipeline = ToolGovernancePipeline(mode="core")
```

---

## Built-in Risk Patterns

Risk patterns are available in all modes. They detect dangerous operations across categories:

- **Dangerous shell commands** — `rm -rf`, `mkfs`, `dd if=`, fork bombs, etc.
- **Secret detection (9 families)** — API keys, tokens, passwords, private keys, connection strings, cloud credentials, JWT secrets, webhook URLs, OAuth secrets
- **Path traversal** — `../`, symlink attacks, TOCTOU protection
- **Network exfiltration** — `curl | bash`, reverse shells, encoded payloads
- **Privilege escalation** — `sudo`, `chmod 777`, `chown root`
- **Configuration tampering** — `.eslintrc`, `.gitignore`, CI config modification
- **Data destruction** — `DROP TABLE`, `TRUNCATE`, mass deletes
- **Credential file access** — `~/.ssh/*`, `~/.aws/*`, `.env` files
- **Code injection** — `eval()`, `exec()`, dynamic imports from untrusted sources

---

## Context Engine

Multi-layer compaction system with mode-dependent activation:

| Layer | Strategy | Mode | Description |
|:-----:|:---------|:----:|:------------|
| 1 | **Token Budget** | All | Model-aware tracking (200K / 1M context windows) |
| 2 | **Truncation** | All | Oldest-first message removal when budget exceeded |
| 3 | **Microcompact** | Standard+ | Prune old tool outputs while preserving recent context |
| 4 | **AutoCompact** | Enhanced | LLM-based summarization with circuit breaker |
| 5 | **Image Stripping** | Enhanced | Remove images before compaction |
| 6 | **File Restoration** | Enhanced | Re-inject recently modified files after compression |

---

## Tool System

| Feature | Description |
|:--------|:------------|
| **Registry** | Schema validation, aliases, and deferred loading |
| **Orchestrator** | Read-only tools run in parallel; writes serialize |
| **Output Budgets** | Per-tool output limits, overflow persisted to disk |
| **ToolSearch** | Lazy schema discovery for large tool sets (20+ tools) |

---

## Agent Orchestration

Multi-agent patterns with mode-dependent availability:

| Pattern | Description | Mode | Use Case |
|:--------|:------------|:----:|:---------|
| Profiles | Role-based tool/risk restrictions (coder/reviewer/planner/executor) | Standard+ | Team governance |
| Fork | Sub-agents inherit parent context + share prompt cache | Enhanced | Parallel exploration |
| Background | Async execution with progress tracking and notifications | Enhanced | Long-running tasks |
| Swarm | Parallel agents communicating via JSONL mailbox files | Enhanced | Distributed work |
| Coordinator | Orchestrator delegates all tool use to worker agents | Enhanced | Complex pipelines |

**Built-in agent types:** Explore (read-only/fast), Plan (architecture), Verification (adversarial), General

---

## Trace Store (Standard+)

Filesystem-based execution trace persistence for governance diagnostics:

```
.autoharness/traces/
  {session_id}/
    trace_{timestamp}_{tool_name}.json
```

Each trace records the full tool call lifecycle: input, risk assessment, permission decision, execution result, and timing. Traces are queryable for pattern analysis and policy improvement.

---

## Skill System

Two-layer injection for context efficiency:

```
Layer 1 (always in prompt):  skill name + description  (~100 tokens each)
Layer 2 (loaded on demand):  full skill body            (only when model requests it)
```

- **YAML frontmatter** for skill metadata (allowed tools, model hints, effort estimates)
- **Discovery** from project-level and global skill directories

---

## Configuration

Define your agent's behavioral contract in a YAML constitution:

```yaml
version: "1.0"
mode: enhanced          # core | standard | enhanced

identity:
  name: my-agent
  boundaries:
    - "Only modify files within the project directory"
    - "Never access credentials or secret files"

permissions:
  defaults:
    unknown_tool: ask
    unknown_path: deny
    on_error: deny        # Never fail open
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

Generate a starter constitution:

```bash
autoharness init                     # Interactive wizard
autoharness init --mode core         # Core mode constitution
autoharness init --template default  # Legacy template mode
```

---

## CLI

```bash
# Initialize a constitution
autoharness init                          # Interactive wizard
autoharness init --mode core              # With specific pipeline mode

# Pipeline mode management
autoharness mode                          # Show current mode
autoharness mode enhanced                 # Switch mode

# Validate and check
autoharness validate constitution.yaml
echo '{"tool_name": "Bash", "tool_input": {"command": "rm -rf ~"}}' \
    | autoharness check --stdin --format json

# Audit
autoharness audit summary

# Integrations
autoharness install --target claude-code  # Install as a Claude Code hook
autoharness export --format cursor        # Export for Cursor IDE
```

---

## Comparison with Other Frameworks

| Capability | AutoHarness | LangGraph | Pydantic AI | Guardrails AI | OpenAI SDK |
|:-----------|:------------:|:---------:|:-----------:|:-------------:|:----------:|
| **Tool governance pipeline** | ✅ 6/8/14-step | ❌ | ❌ | ⚠️ Output-only | ❌ |
| **Declarative YAML rules** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Risk pattern matching** | ✅ | ❌ | ❌ | ⚠️ Hub validators | ❌ |
| **Multi-layer context** | ✅ | ❌ | ❌ | ❌ | ⚠️ Trimming |
| **Trace-based diagnostics** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Layered validation** | ✅ Input+Exec+Output | ❌ | ⚠️ Output only | ✅ Rails | ❌ |
| **Cost attribution** | ✅ Per-tool/agent | ❌ | ❌ | ❌ | ❌ |
| **Multi-agent profiles** | ✅ | ✅ Graph-based | ❌ | ❌ | ⚠️ Handoff |
| **Audit trail (JSONL)** | ✅ | ❌ | ⚠️ Logfire | ❌ | ✅ Tracing |
| **Vendor lock-in** | ✅ None | ⚠️ LangChain | ✅ None | ✅ None | 🔒 OpenAI |
| **Setup** | ✅ 2 lines | ⚠️ Graph DSL | ⚠️ Agent class | ⚠️ RAIL XML | ⚠️ SDK |
