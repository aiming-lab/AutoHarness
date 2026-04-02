<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>Todo agente merece um momento <b>aha</b> — o modelo raciocina, nós cuidamos do resto.</em></h3>

<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-inicio-rapido"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>

<p align="center">
  <a href="../README.md">🇬🇧 English</a> ·
  <a href="README_CN.md">🇨🇳 简体中文</a> ·
  <a href="README_JA.md">🇯🇵 日本語</a> ·
  <a href="README_KO.md">🇰🇷 한국어</a> ·
  <a href="README_ES.md">🇪🇸 Español</a> ·
  <a href="README_FR.md">🇫🇷 Français</a> ·
  <a href="README_DE.md">🇩🇪 Deutsch</a> ·
  🇵🇹 Português ·
  <a href="README_RU.md">🇷🇺 Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 Documentação</b></a> ·
  <a href="#-instalacao-rapida"><b>⚡ Instalação rápida</b></a> ·
  <a href="#-inicio-rapido"><b>🚀 Início rápido</b></a> ·
  <a href="#-o-que-voce-ganha"><b>✨ Funcionalidades</b></a> ·
  <a href="#-como-nos-comparamos"><b>📊 Comparação</b></a>
</p>

---

## ⚡ Instalacao rapida

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# E so isso. Seu agente acabou de ter o momento aha.
```

---

## 🔥 Novidades

- **[01/04/2026]** **v0.2.0 Lancada**: Tres modos de pipeline (Core / Standard / Enhanced), diagnosticos baseados em traces, gates de validacao de interface, gerenciamento de contexto aprimorado. **958 testes aprovados.**
- **[01/04/2026]** [**v0.1.0 Lancada**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0): Pipeline de governanca em 6 etapas, correspondencia de padroes de risco, constituicao YAML, trilha de auditoria, perfis multi-agente, persistencia de sessao com rastreamento de custos.

---

## 🤔 Por que *Aha* (**A**uto**Ha**rness)?

> No treinamento de LLMs, o ***momento aha*** e quando um modelo aprende de repente a raciocinar.
>
> Para agentes, o ***momento aha*** e quando eles passam de "pronto para demo" a verdadeiramente confiaveis.

A distancia e enorme: gerenciamento de contexto, governanca de ferramentas, controle de custos, observabilidade, persistencia de sessao... Esses sao os padroes que separam um brinquedo de um sistema. Chamamos isso de **engenharia de harness**.

AutoHarness é um framework de governança leve e em camadas **para que todo agente possa ter seu *momento aha*.**

> **Agente = Modelo + Harness.** O modelo raciocina. O harness faz todo o resto.

---

## 🚀 Inicio rapido

```python
# Encapsule qualquer cliente LLM (2 linhas, governanca instantanea)
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
# Ou use o loop de agente completo
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[Mais exemplos →](features.md#cli)**

---

## ✨ O que voce ganha

| Sem Harness | Com AutoHarness |
|:------------|:----------------|
| O agente executa `rm -rf /`, nada o impede | **Pipeline de 6 etapas** bloqueia, registra e explica por que |
| O contexto estoura o limite de tokens | **Orcamento de tokens** + **truncamento** mantem o contexto sob controle |
| Sem saber qual chamada de ferramenta custou quanto | **Atribuicao de custos por chamada** com precificacao adaptada ao modelo |
| Injecao de prompts passa despercebida | **Validacao em camadas**: rails de entrada, execucao, rails de saida |
| Sem trilha de auditoria para conformidade | **Auditoria JSONL** registra cada decisao com proveniencia completa |
| Agentes compartilham um unico conjunto de permissoes | **Perfis multi-agente** com governanca baseada em papeis |

### Arquitetura central: Pipeline de governanca em 6 etapas

Cada chamada de ferramenta passa por um pipeline estruturado:

```
1. Parse & Validate  →  2. Risk Classify  →  3. Permission Check
4. Execute           →  5. Output Sanitize →  6. Audit Log
```

Padroes de risco integrados detectam operacoes perigosas, exposicao de segredos, travessia de caminhos e muito mais.

### Em numeros

```
Pipeline de governanca em 6 etapas  ·  Correspondencia de padroes de risco  ·  Constituicao YAML
Gerenciamento de orcamento de tokens ·  Perfis multi-agente                 ·  Trilha de auditoria JSONL
2 linhas para integrar               ·  0 dependencia de fornecedor         ·  Licenca MIT
```

---

## 🔧 Modos de pipeline

O AutoHarness suporta tres modos de pipeline. Escolha o nivel de governanca que se adapta as suas necessidades:

| Modo | Pipeline | Contexto | Multi-agente | Caso de uso |
|:-----|:---------|:---------|:-------------|:------------|
| **Core** | 6 etapas | Orcamento de tokens + truncamento | Agente unico | Governanca leve |
| **Standard** | 8 etapas | + Microcompact + armazenamento de traces | Perfis basicos | Agentes em producao |
| **Enhanced** | 14 etapas | + Sumarizacao por LLM + remocao de imagens | Fork / Swarm / Background | Governanca maxima |

```python
# Troque de modo via constituicao
# constitution.yaml
mode: core      # ou "standard" ou "enhanced"
```

```bash
# Ou via CLI
autoharness mode enhanced
```

> **O modo Enhanced e o padrao.** Os usuarios recebem a governanca mais forte por padrao. Troque para Core para sobrecarga minima.

> **[Comparacao completa de modos →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # Gerar constituicao (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # Gerar com modo de pipeline especifico
autoharness mode                          # Mostrar modo de pipeline atual
autoharness mode enhanced                 # Trocar modo de pipeline
autoharness validate constitution.yaml    # Validar um arquivo de constituicao
autoharness check --stdin --format json   # Verificar uma chamada de ferramenta contra suas regras
autoharness audit summary                 # Ver resumo de auditoria
autoharness install --target claude-code  # Instalar como hook do Claude Code (um comando)
autoharness export --format cursor        # Exportar constituicao cross-harness
```

---

## 📊 Como nos comparamos

| Capacidade | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:-----------|:---:|:---:|:---:|:---:|
| Pipeline de governanca de ferramentas | ✅ 6 etapas (ate 14) | ❌ | ⚠️ Somente saida | ❌ |
| Gerenciamento de contexto | ✅ Multicamada | ❌ | ❌ | ⚠️ Truncamento |
| Perfis multi-agente | ✅ | ✅ Grafos | ❌ | ⚠️ Handoff |
| Validacao (entrada+saida) | ✅ | ❌ | ✅ Rails | ❌ |
| Diagnosticos baseados em traces | ✅ | ❌ | ❌ | ❌ |
| Atribuicao de custos | ✅ Por chamada | ❌ | ❌ | ❌ |
| Dependencia de fornecedor | Nenhuma | LangChain | Nenhuma | OpenAI |
| Configuracao | 2 linhas | Graph DSL | RAIL XML | SDK |

---

## 🙏 Agradecimentos

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) da Anthropic: padroes de engenharia que inspiraram algumas funcionalidades do nosso modo Enhanced
- [Codex](https://github.com/openai/codex) da OpenAI: praticas de engenharia de contexto que informaram o design do nosso gerenciamento de contexto

---

## 📌 Citacao

Se voce usar o AutoHarness em sua pesquisa, por favor cite:

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

## ⚠️ Aviso

Algumas decisões arquiteturais do modo Enhanced foram baseadas em análises públicas e discussões da comunidade sobre o design do Claude Code após sua publicação involuntária pelo registro npm da Anthropic em 31-03-2026. Reconhecemos que o código-fonte original do Claude Code é propriedade intelectual da Anthropic. AutoHarness não contém, redistribui ou traduz diretamente nenhum código proprietário da Anthropic. Respeitamos os direitos de PI da Anthropic e responderemos prontamente a quaisquer preocupações — entre em contato via [issue](https://github.com/aiming-lab/AutoHarness/issues) ou [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com).

---

## 📄 Licenca

MIT — veja [LICENSE](../LICENSE) para detalhes.
