<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>Todo agente merece un momento <b>aha</b> — el modelo razona, nosotros nos encargamos del resto.</em></h3>

<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-inicio-rápido"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>

<p align="center">
  🇬🇧 <a href="../README.md">English</a> ·
  🇨🇳 <a href="README_CN.md">简体中文</a> ·
  🇯🇵 <a href="README_JA.md">日本語</a> ·
  🇰🇷 <a href="README_KO.md">한국어</a> ·
  🇪🇸 Español ·
  🇫🇷 <a href="README_FR.md">Français</a> ·
  🇩🇪 <a href="README_DE.md">Deutsch</a> ·
  🇵🇹 <a href="README_PT.md">Português</a> ·
  🇷🇺 <a href="README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 Documentación</b></a> ·
  <a href="#-inicio-rápido"><b>🚀 Inicio Rápido</b></a> ·
  <a href="#-modos-de-pipeline"><b>🔧 Modos de Pipeline</b></a> ·
  <a href="#-tabla-comparativa"><b>📊 Comparativa</b></a>
</p>

---

## ⚡ Instalación Rápida

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# Eso es todo. Tu agente acaba de tener su momento aha.
```

---

## 🔥 Novedades

- **[01/04/2026]** **v0.2.0 Publicada**: Tres modos de pipeline (Core / Standard / Enhanced), diagnósticos basados en trazas, puertas de validación de interfaces, gestión de contexto mejorada. **958 tests aprobados.**
- **[01/04/2026]** [**v0.1.0 Publicada**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0): Pipeline de gobernanza de 6 pasos, coincidencia de patrones de riesgo, constitución YAML, registro de auditoría, perfiles multi-agente, persistencia de sesión con seguimiento de costes.

---

## 🤔 Por qué *Aha* (**A**uto**Ha**rness)?

> En el entrenamiento de LLMs, el ***momento aha*** es cuando un modelo aprende a razonar de repente.
>
> Para los agentes, el ***momento aha*** es cuando pasan de "listo para demos" a verdaderamente fiables.

La brecha es enorme: gestión de contexto, gobernanza de herramientas, control de costes, observabilidad, persistencia de sesión... Estos son los patrones que separan un juguete de un sistema real. A esto lo llamamos **ingeniería de harness**.

AutoHarness es un framework de gobernanza ligero y por capas **para que cada agente pueda tener su *momento aha*.**

> **Agente = Modelo + Harness.** El modelo razona. El harness hace todo lo demás.

---

## 🚀 Inicio Rápido

```python
# Envuelve cualquier cliente LLM (2 líneas, gobernanza instantánea)
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
# O usa el loop de agente completo
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[Más ejemplos →](features.md#cli)**

---

## ✨ Qué Obtienes

| Sin Harness | Con AutoHarness |
|:------------|:----------------|
| El agente ejecuta `rm -rf /` y nada lo detiene | El **pipeline de 6 pasos** lo bloquea, lo registra y explica por qué |
| El contexto explota más allá del límite de tokens | **Presupuesto de tokens** + **truncamiento** mantienen el contexto bajo control |
| Sin saber cuánto cuesta cada llamada a herramienta | **Atribución de costes por llamada** con precios adaptados al modelo |
| La inyección de prompts pasa sin filtro | **Validación por capas**: validación de entrada, ejecución y salida |
| Sin registro de auditoría para cumplimiento normativo | **Auditoría JSONL** registra cada decisión con procedencia completa |
| Todos los agentes comparten los mismos permisos | **Perfiles multi-agente** con gobernanza basada en roles |

### Arquitectura Central: Pipeline de Gobernanza de 6 Pasos

Cada llamada a herramienta pasa por un pipeline estructurado:

```
1. Parseo y Validación  →  2. Clasificación de Riesgo  →  3. Verificación de Permisos
4. Ejecución             →  5. Saneamiento de Salida    →  6. Registro de Auditoría
```

Los patrones de riesgo integrados detectan operaciones peligrosas, exposición de secretos, path traversal y más.

### En Números

```
Pipeline de gobernanza de 6 pasos   ·  Coincidencia de patrones de riesgo  ·  Constitución YAML
Gestión de presupuesto de tokens     ·  Perfiles multi-agente              ·  Registro de auditoría JSONL
2 líneas para integrar               ·  0 dependencia de proveedor         ·  Licencia MIT
```

---

## 🔧 Modos de Pipeline

AutoHarness soporta tres modos de pipeline. Elige el nivel de gobernanza que se adapte a tus necesidades:

| Modo | Pipeline | Contexto | Multi-Agente | Caso de Uso |
|:-----|:---------|:---------|:-------------|:------------|
| **Core** | 6 pasos | Presupuesto de tokens + truncamiento | Agente único | Gobernanza ligera |
| **Standard** | 8 pasos | + Microcompact + almacén de trazas | Perfiles básicos | Agentes en producción |
| **Enhanced** | 14 pasos | + Resumen por LLM + eliminación de imágenes | Fork / Swarm / Background | Gobernanza máxima |

```python
# Cambiar modo vía constitución
# constitution.yaml
mode: core      # o "standard" o "enhanced"
```

```bash
# O vía CLI
autoharness mode enhanced
```

> **El modo Enhanced es el predeterminado.** Los usuarios obtienen la gobernanza más fuerte desde el inicio. Cambia a Core para un overhead mínimo.

> **[Comparación completa de modos →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # Generar constitución (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # Generar con un modo de pipeline específico
autoharness mode                          # Mostrar modo de pipeline actual
autoharness mode enhanced                 # Cambiar modo de pipeline
autoharness validate constitution.yaml    # Validar un archivo de constitución
autoharness check --stdin --format json   # Verificar una llamada a herramienta contra tus reglas
autoharness audit summary                 # Ver resumen de auditoría
autoharness install --target claude-code  # Instalar como hook de Claude Code (un comando)
autoharness export --format cursor        # Exportar constitución cross-harness
```

---

## 📊 Tabla Comparativa

| Capacidad | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:----------|:---:|:---:|:---:|:---:|
| Pipeline de gobernanza de herramientas | ✅ 6 pasos (hasta 14) | ❌ | ⚠️ Solo salida | ❌ |
| Gestión de contexto | ✅ Multi-capa | ❌ | ❌ | ⚠️ Trimming |
| Perfiles multi-agente | ✅ | ✅ Grafos | ❌ | ⚠️ Handoff |
| Validación (entrada+salida) | ✅ | ❌ | ✅ Rails | ❌ |
| Diagnósticos basados en trazas | ✅ | ❌ | ❌ | ❌ |
| Atribución de costes | ✅ Por llamada | ❌ | ❌ | ❌ |
| Dependencia de proveedor | Ninguna | LangChain | Ninguna | OpenAI |
| Configuración | 2 líneas | Graph DSL | RAIL XML | SDK |

---

## 🙏 Agradecimientos

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) de Anthropic: patrones de ingeniería que inspiraron algunas funcionalidades de nuestro modo Enhanced
- [Codex](https://github.com/openai/codex) de OpenAI: prácticas de ingeniería de contexto que informaron nuestro diseño de gestión de contexto

---

## 📌 Citación

Si usas AutoHarness en tu investigación, por favor cita:

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

## ⚠️ Aviso legal

Algunas decisiones arquitectónicas del modo Enhanced se basaron en análisis públicos y discusiones comunitarias sobre el diseño de Claude Code tras su publicación involuntaria a través del registro npm de Anthropic el 31-03-2026. Reconocemos que el código fuente original de Claude Code es propiedad intelectual de Anthropic. AutoHarness no contiene, redistribuye ni traduce directamente ningún código propietario de Anthropic. Respetamos los derechos de PI de Anthropic y atenderemos cualquier inquietud de inmediato — contáctenos vía [issue](https://github.com/aiming-lab/AutoHarness/issues) o [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com).

---

## 📄 Licencia

MIT. Consulta [LICENSE](../LICENSE) para más detalles.
