<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>Jeder Agent verdient seinen <b>aha</b>-Moment — das Modell denkt, wir kümmern uns um den Rest.</em></h3>


<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-schnellstart"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>



<p align="center">
  🇬🇧 <a href="../README.md">English</a> ·
  🇨🇳 <a href="README_CN.md">简体中文</a> ·
  🇯🇵 <a href="README_JA.md">日本語</a> ·
  🇰🇷 <a href="README_KO.md">한국어</a> ·
  🇪🇸 <a href="README_ES.md">Español</a> ·
  🇫🇷 <a href="README_FR.md">Français</a> ·
  🇩🇪 Deutsch ·
  🇵🇹 <a href="README_PT.md">Português</a> ·
  🇷🇺 <a href="README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 Dokumentation</b></a> ·
  <a href="#-schnellstart"><b>🚀 Schnellstart</b></a> ·
  <a href="#-pipeline-modi"><b>🔧 Modi</b></a> ·
  <a href="#-vergleich"><b>📊 Vergleich</b></a>
</p>

---

## ⚡ Schnellinstallation

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# Das war's. Ihr Agent hat gerade seinen Aha-Moment erlebt.
```

---

## 🔥 Neuigkeiten

- **[01.04.2026]** **v0.2.0 Veröffentlicht**: Dreistufige Pipeline-Modi (Core / Standard / Enhanced), Trace-basierte Diagnostik, Interface-Validierungsschranken, verbesserte Kontextverwaltung. **958 Tests bestanden.**
- **[01.04.2026]** [**v0.1.0 Veröffentlicht**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0): 6-Schritte-Governance-Pipeline, Risikomuster-Erkennung, YAML-Konstitution, Audit-Trail, Multi-Agenten-Profile, Sitzungspersistenz mit Kostenverfolgung.

---

## 🤔 Warum *Aha* (**A**uto**Ha**rness)?

> Beim LLM-Training ist der ***Aha*-Moment** der Augenblick, in dem ein Modell plötzlich lernt zu denken.
>
> Für Agenten ist der ***Aha*-Moment** der Übergang von "demo-tauglich" zu wirklich zuverlässig.

Die Lücke ist enorm: Kontextverwaltung, Tool-Governance, Kostenkontrolle, Beobachtbarkeit, Sitzungspersistenz... Das sind die Muster, die ein Spielzeug von einem System unterscheiden. Wir nennen das **Harness Engineering**.

AutoHarness ist ein leichtgewichtiges, mehrschichtiges Governance-Framework, **damit jeder Agent seinen *Aha*-Moment haben kann.**

> **Agent = Modell + Harness.** Das Modell denkt. Der Harness erledigt alles andere.

---

## 🚀 Schnellstart

```python
# Beliebigen LLM-Client wrappen (2 Zeilen, sofortige Governance)
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
# Oder die vollständige Agentenschleife verwenden
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[Weitere Beispiele →](features.md#cli)**

---

## ✨ Was Sie bekommen

| Ohne Harness | Mit AutoHarness |
|:-------------|:----------------|
| Agent führt `rm -rf /` aus, nichts hält ihn auf | **6-Schritte-Pipeline** blockiert es, protokolliert es, erklärt warum |
| Kontext sprengt das Token-Limit | **Token-Budget** + **Trunkierung** halten den Kontext unter Kontrolle |
| Unklar, welcher Tool-Aufruf wie viel gekostet hat | **Kostenzuordnung pro Aufruf** mit modellbewusster Preisgestaltung |
| Prompt-Injection schleicht sich durch | **Schichtvalidierung**: Eingangs-Rails, Ausführung, Ausgangs-Rails |
| Kein Audit-Trail für Compliance | **JSONL-Audit** protokolliert jede Entscheidung mit vollständiger Herkunft |
| Agenten teilen einen einzigen Berechtigungssatz | **Multi-Agenten-Profile** mit rollenbasierter Governance |

### Kernarchitektur: 6-Schritte-Governance-Pipeline

Jeder Tool-Aufruf durchläuft eine strukturierte Pipeline:

```
1. Parsen & Validieren  →  2. Risiko klassifizieren  →  3. Berechtigungen prüfen
4. Ausführen             →  5. Ausgabe bereinigen     →  6. Audit protokollieren
```

Integrierte Risikomuster erkennen gefährliche Operationen, Geheimnis-Exposition, Pfad-Traversierung und mehr.

### In Zahlen

```
6-Schritte-Governance-Pipeline  ·  Risikomuster-Erkennung         ·  YAML-Konstitution
Token-Budget-Verwaltung          ·  Multi-Agenten-Profile           ·  JSONL-Audit-Trail
2 Zeilen zur Integration         ·  0 Herstellerbindung             ·  MIT-Lizenz
```

---

## 🔧 Pipeline-Modi

AutoHarness unterstützt drei Pipeline-Modi. Wählen Sie die Governance-Stufe, die zu Ihren Anforderungen passt:

| Modus | Pipeline | Kontext | Multi-Agent | Anwendungsfall |
|:------|:---------|:--------|:------------|:---------------|
| **Core** | 6 Schritte | Token-Budget + Trunkierung | Einzelner Agent | Leichtgewichtige Governance |
| **Standard** | 8 Schritte | + Microcompact + Trace-Speicher | Basis-Profile | Produktionsagenten |
| **Enhanced** | 14 Schritte | + LLM-Zusammenfassung + Bildentfernung | Fork / Swarm / Hintergrund | Maximale Governance |

```python
# Modus über Konstitution wechseln
# constitution.yaml
mode: core      # oder "standard" oder "enhanced"
```

```bash
# Oder über CLI
autoharness mode enhanced
```

> **Enhanced ist der Standardmodus.** Nutzer erhalten sofort die stärkste Governance. Wechseln Sie zu Core für minimalen Overhead.

> **[Vollständiger Modusvergleich →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # Konstitution generieren (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # Mit spezifischem Pipeline-Modus generieren
autoharness mode                          # Aktuellen Pipeline-Modus anzeigen
autoharness mode enhanced                 # Pipeline-Modus wechseln
autoharness validate constitution.yaml    # Konstitutionsdatei validieren
autoharness check --stdin --format json   # Tool-Aufruf gegen Ihre Regeln prüfen
autoharness audit summary                 # Audit-Zusammenfassung anzeigen
autoharness install --target claude-code  # Als Claude Code Hook installieren (ein Befehl)
autoharness export --format cursor        # Cross-Harness-Konstitution exportieren
```

---

## 📊 Vergleich

| Fähigkeit | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:-----------|:---:|:---:|:---:|:---:|
| Tool-Governance-Pipeline | ✅ 6 Schritte (bis 14) | ❌ | ⚠️ Nur Ausgabe | ❌ |
| Kontextverwaltung | ✅ Mehrschichtig | ❌ | ❌ | ⚠️ Trimmung |
| Multi-Agenten-Profile | ✅ | ✅ Graph | ❌ | ⚠️ Handoff |
| Validierung (Eingang+Ausgang) | ✅ | ❌ | ✅ Rails | ❌ |
| Trace-basierte Diagnostik | ✅ | ❌ | ❌ | ❌ |
| Kostenzuordnung | ✅ Pro Aufruf | ❌ | ❌ | ❌ |
| Herstellerbindung | Keine | LangChain | Keine | OpenAI |
| Einrichtung | 2 Zeilen | Graph DSL | RAIL XML | SDK |

---

## 🙏 Danksagungen

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) von Anthropic: Engineering-Muster, die einige Funktionen unseres Enhanced-Modus inspiriert haben
- [Codex](https://github.com/openai/codex) von OpenAI: Context-Engineering-Praktiken, die das Design unserer Kontextverwaltung informiert haben

---

## 📌 Zitation

Wenn Sie AutoHarness in Ihrer Forschung verwenden, zitieren Sie bitte:

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

## ⚠️ Haftungsausschluss

Einige architektonische Entscheidungen im Enhanced-Modus wurden durch öffentlich verfügbare Analysen und Community-Diskussionen über das Design von Claude Code nach dessen unbeabsichtigter Veröffentlichung über Anthropics npm-Registry am 31.03.2026 beeinflusst. Wir erkennen an, dass der Originalquellcode von Claude Code geistiges Eigentum von Anthropic ist. AutoHarness enthält, verbreitet oder übersetzt keinen proprietären Code von Anthropic. Wir respektieren Anthropics IP-Rechte und werden Bedenken umgehend behandeln — kontaktieren Sie uns über [Issue](https://github.com/aiming-lab/AutoHarness/issues) oder [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com).

---

## 📄 Lizenz

MIT. Siehe [LICENSE](../LICENSE) für Details.
