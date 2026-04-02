<p align="center">
  <img src="images/logo.png" alt="AutoHarness Logo" width="600"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>Every agent deserves an <b>aha</b> moment — the model reasons, we harness the rest.</em></h3>


<p align="center">
  <img src="images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-quickstart"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>



<p align="center">
  <a href="docs/README_CN.md">🇨🇳 简体中文</a> ·
  <a href="docs/README_JA.md">🇯🇵 日本語</a> ·
  <a href="docs/README_KO.md">🇰🇷 한국어</a> ·
  <a href="docs/README_ES.md">🇪🇸 Español</a> ·
  <a href="docs/README_FR.md">🇫🇷 Français</a> ·
  <a href="docs/README_DE.md">🇩🇪 Deutsch</a> ·
  <a href="docs/README_PT.md">🇵🇹 Português</a> ·
  <a href="docs/README_RU.md">🇷🇺 Русский</a>
</p>


---

## 🤔 Why *Aha* (**A**uto**Ha**rness)?

> In LLM training, the ***aha* moment** is when a model suddenly learns to reason.
>
> For agents, the ***aha* moment** is when they go from "demo-ready" to truly reliable.

The gap is enormous: context management, tool governance, cost control, observability, session persistence... These are the patterns that separate a toy from a system. We call this **harness engineering**.

AutoHarness is a lightweight governance framework **so every agent can have its *aha* moment.**

> **Agent = Model + Harness.** The model reasons. The harness does everything else.

---

## ⚡ Quick Install

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# That's it. Your agent just had its aha moment.
```

---

## 🔥 News

- **[04/01/2026]** [**v0.1.0 Released**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0): Three-tier pipeline modes (Core / Standard / Enhanced), 6-step governance pipeline, risk pattern matching, YAML constitution, trace-based diagnostics, multi-agent profiles, session persistence with cost tracking. **958 tests passing.**


---

## 🚀 Quickstart

```python
# Wrap any LLM client (2 lines, instant governance)
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
response = client.chat.completions.create(
    model="gpt-5.4",
    messages=[{"role": "user", "content": "Refactor auth.py"}],
    tools=[{"type": "function", "function": {"name": "Bash", "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}],
)
```

```python
# Or use the full agent loop
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[More examples →](docs/features.md#cli)**


---

## 🔧 Pipeline Modes

AutoHarness supports three pipeline modes. Choose the level of governance that fits your needs:

| Mode | Pipeline | Context | Multi-Agent | Use Case |
|:-----|:---------|:--------|:------------|:---------|
| **Core** | 6-step | Token budget + truncation | Single agent | Lightweight governance |
| **Standard** | 8-step | + Microcompact + trace store | Basic profiles | Production agents |
| **Enhanced** | 14-step | + LLM summarization + image strip | Fork / Swarm / Background | Maximum governance |

```python
# Switch modes via constitution
# constitution.yaml
mode: core      # or "standard" or "enhanced"
```

```bash
# Or via CLI
autoharness mode enhanced
```

> **Enhanced mode is the default.** Users get the strongest governance out of the box. Switch to Core for minimal overhead.

> **[Full mode comparison →](docs/features.md#pipeline-modes)**


---

## ✨ What You Get

| Without Harness | With AutoHarness |
|:----------------|:-----------------|
| Agent runs `rm -rf /`, nothing stops it | **6-step pipeline** blocks it, logs it, explains why |
| Context explodes past token limit | **Token budget** + **truncation** keeps context under control |
| No idea which tool call cost how much | **Per-call cost attribution** with model-aware pricing |
| Prompt injection sneaks through | **Layered validation**: input rails, execution, output rails |
| No audit trail for compliance | **JSONL audit** logs every decision with full provenance |
| Agents share one permission set | **Multi-agent profiles** with role-based governance |

### Core Architecture: 6-Step Governance Pipeline

Every tool call flows through a structured pipeline:

```
1. Parse & Validate  →  2. Risk Classify  →  3. Permission Check
4. Execute           →  5. Output Sanitize →  6. Audit Log
```

Built-in risk patterns detect dangerous operations, secret exposure, path traversal, and more.

### By the Numbers

```
6-step governance pipeline   ·  Risk pattern matching      ·  YAML constitution
Token budget management      ·  Multi-agent profiles       ·  JSONL audit trail
2 lines to integrate         ·  0 vendor lock-in           ·  MIT licensed
```



---

## 🖥️ CLI

```bash
autoharness init                          # Generate constitution (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # Generate with specific pipeline mode
autoharness mode                          # Show current pipeline mode
autoharness mode enhanced                 # Switch pipeline mode
autoharness validate constitution.yaml    # Validate a constitution file
autoharness check --stdin --format json   # Check a tool call against your rules
autoharness audit summary                 # View audit summary
autoharness install --target claude-code  # Install as a Claude Code hook (one command)
autoharness export --format cursor        # Export cross-harness constitution
```

---

## 📊 How We Compare

| Capability | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:-----------|:---:|:---:|:---:|:---:|
| Tool governance pipeline | ✅ 6-step (up to 14) | ❌ | ⚠️ Output-only | ❌ |
| Context management | ✅ Multi-layer | ❌ | ❌ | ⚠️ Trimming |
| Multi-agent profiles | ✅ | ✅ Graph | ❌ | ⚠️ Handoff |
| Validation (input+output) | ✅ | ❌ | ✅ Rails | ❌ |
| Trace-based diagnostics | ✅ | ❌ | ❌ | ❌ |
| Cost attribution | ✅ Per-call | ❌ | ❌ | ❌ |
| Vendor lock-in | None | LangChain | None | OpenAI |
| Setup | 2 lines | Graph DSL | RAIL XML | SDK |

---

## 🙏 Acknowledgments

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) by Anthropic: engineering patterns that inspired some of our Enhanced mode features
- [Codex](https://github.com/openai/codex) by OpenAI: context engineering practices that informed our context management design


---

## 📌 Citation

If you use AutoHarness in your research, please cite:

```bibtex
@software{autoharness2026,
  title   = {AutoHarness: The Harness Engineering Framework for AI Agents},
  author  = {{AutoHarness Team}},
  year    = {2026},
  url     = {https://github.com/aiming-lab/AutoHarness},
  license = {MIT}
}
```


---

## ⚠️ Disclaimer

Some architectural decisions in the Enhanced mode were informed by publicly available analysis and community discussion of Claude Code's design following its inadvertent publication via Anthropic's npm registry on 2026-03-31. We acknowledge that Claude Code's original source code is the intellectual property of Anthropic. AutoHarness does not contain, redistribute, or directly translate any of Anthropic's proprietary code. We respect Anthropic's IP rights and will promptly address any concerns — please contact us via [issue](https://github.com/aiming-lab/AutoHarness/issues) or [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com).


---

## 📄 License

MIT. See [LICENSE](LICENSE) for details.


