<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>每个 Agent 都值得一个 <b>aha</b> 时刻 — 模型负责推理，我们驾驭其余一切。</em></h3>

<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-快速开始"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>

<p align="center">
  <a href="../README.md">🇬🇧 English</a> ·
  🇨🇳 简体中文 ·
  <a href="README_JA.md">🇯🇵 日本語</a> ·
  <a href="README_KO.md">🇰🇷 한국어</a> ·
  <a href="README_ES.md">🇪🇸 Español</a> ·
  <a href="README_FR.md">🇫🇷 Français</a> ·
  <a href="README_DE.md">🇩🇪 Deutsch</a> ·
  <a href="README_PT.md">🇵🇹 Português</a> ·
  <a href="README_RU.md">🇷🇺 Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 文档</b></a> ·
  <a href="#-快速开始"><b>🚀 快速开始</b></a> ·
  <a href="#-快速上手"><b>💡 快速上手</b></a> ·
  <a href="#-致谢"><b>🤝 致谢</b></a>
</p>

---

## ⚡ 快速安装

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# 就这样。你的 Agent 刚刚迎来了它的 aha 时刻。
```

---

## 🔥 最新动态

- **[04/01/2026]** **v0.2.0 发布**：三级管线模式（Core / Standard / Enhanced）、基于 trace 的诊断、接口验证门控、改进的上下文管理。**958 项测试全部通过。**
- **[04/01/2026]** [**v0.1.0 发布**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0)：6 步治理管线、风险模式匹配、YAML constitution、审计追踪、多 Agent 配置、带成本跟踪的会话持久化。

---

## 🤔 为什么叫 *Aha*（**A**uto**Ha**rness）？

> 在 LLM 训练中，***aha* 时刻**是模型突然学会推理的那一刻。
>
> 对于 Agent 而言，***aha* 时刻**是它从"能跑个 Demo"进化为真正可靠的那一刻。

两者之间的鸿沟巨大：上下文管理、工具治理、成本控制、可观测性、会话持久化……这些正是将玩具与生产系统区分开来的工程模式。我们称之为**治理工程（harness engineering）**。

AutoHarness 是一套轻量的、分层的治理框架，**让每个 Agent 都能拥有它的 *aha* 时刻。**

> **Agent = Model + Harness。** 模型负责推理，治理层负责其余一切。

---

## 🚀 快速上手

```python
# 包装任意 LLM 客户端（2 行代码，即时治理）
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
# 或使用完整的 Agent 循环
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[更多示例 →](features.md#cli)**

---

## ✨ 你将获得什么

| 没有治理层 | 使用 AutoHarness |
|:-----------|:-----------------|
| Agent 执行 `rm -rf /`，无人阻拦 | **6 步管线**拦截、记录、并说明原因 |
| 上下文超出 token 上限后爆炸 | **Token 预算** + **截断策略**确保上下文受控 |
| 完全不知道哪次工具调用花了多少钱 | **逐次调用成本归因**，支持模型感知定价 |
| Prompt 注入畅通无阻 | **分层验证**：输入护栏 → 执行 → 输出护栏 |
| 没有审计追踪，合规无从谈起 | **JSONL 审计日志**记录每一次决策，含完整溯源 |
| 所有 Agent 共享同一套权限 | **多 Agent 配置**，基于角色的差异化治理 |

### 核心架构：6 步治理管线

每次工具调用都流经结构化管线：

```
1. 解析与验证  →  2. 风险分级  →  3. 权限检查
4. 执行        →  5. 输出脱敏  →  6. 审计日志
```

内置风险模式可检测危险命令、密钥泄露、路径穿越等安全威胁。

### 数据一览

```
6 步治理管线              ·  风险模式匹配          ·  YAML constitution
Token 预算管理            ·  多 Agent 配置         ·  JSONL 审计追踪
2 行代码集成              ·  0 厂商锁定            ·  MIT 开源协议
```

---

## 🔧 管线模式

AutoHarness 支持三种管线模式，按需选择适合的治理级别：

| 模式 | 管线 | 上下文 | 多 Agent | 适用场景 |
|:-----|:-----|:-------|:---------|:---------|
| **Core** | 6 步 | Token 预算 + 截断 | 单 Agent | 轻量治理 |
| **Standard** | 8 步 | + Microcompact + trace 存储 | 基础配置 | 生产级 Agent |
| **Enhanced** | 14 步 | + LLM 摘要 + 图片剥离 | Fork / Swarm / Background | 最高治理级别 |

```python
# 通过 constitution 切换模式
# constitution.yaml
mode: core      # 或 "standard" 或 "enhanced"
```

```bash
# 或通过 CLI
autoharness mode enhanced
```

> **Enhanced 为默认模式。** 开箱即用获得最强治理保障。如需最小开销，切换至 Core 模式。

> **[完整模式对比 →](features.md#pipeline-modes)**

---

## 🖥️ 命令行工具

```bash
autoharness init                          # 生成 constitution（default/strict/soc2/hipaa/financial）
autoharness init --mode core              # 指定管线模式生成
autoharness mode                          # 查看当前管线模式
autoharness mode enhanced                 # 切换管线模式
autoharness validate constitution.yaml    # 验证 constitution 文件
autoharness check --stdin --format json   # 根据规则检查工具调用
autoharness audit summary                 # 查看审计摘要
autoharness install --target claude-code  # 一键安装为 Claude Code Hook
autoharness export --format cursor        # 导出跨治理层 constitution
```

---

## 📊 对比表

| 能力 | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:-----------|:---:|:---:|:---:|:---:|
| 工具治理管线 | ✅ 6 步（最高 14 步） | ❌ | ⚠️ 仅输出 | ❌ |
| 上下文管理 | ✅ 多层 | ❌ | ❌ | ⚠️ 截断 |
| 多 Agent 配置 | ✅ | ✅ 基于图 | ❌ | ⚠️ Handoff |
| 验证（输入+输出） | ✅ | ❌ | ✅ Rails | ❌ |
| 基于 trace 的诊断 | ✅ | ❌ | ❌ | ❌ |
| 成本归因 | ✅ 逐次调用 | ❌ | ❌ | ❌ |
| 厂商锁定 | 无 | LangChain | 无 | OpenAI |
| 上手难度 | 2 行代码 | Graph DSL | RAIL XML | SDK |

---

## 🙏 致谢

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)（Anthropic）：部分工程模式启发了我们 Enhanced 模式的功能特性
- [Codex](https://github.com/openai/codex)（OpenAI）：上下文工程实践为我们的上下文管理设计提供了参考

---

## 📌 引用

如果你在研究中使用了 AutoHarness，请引用：

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

## ⚠️ 免责声明

Enhanced 模式中的部分架构决策参考了 Claude Code 设计的公开分析和社区讨论，Claude Code 源码于 2026-03-31 通过 Anthropic 的 npm 仓库意外发布。我们承认 Claude Code 的原始源代码是 Anthropic 的知识产权。AutoHarness 不包含、不再分发、也不直接翻译 Anthropic 的任何专有代码。我们尊重 Anthropic 的知识产权，并将及时回应任何相关问题 — 请通过 [issue](https://github.com/aiming-lab/AutoHarness/issues) 或 [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com) 联系我们。

---

## 📄 许可证

MIT — 详见 [LICENSE](../LICENSE)。
