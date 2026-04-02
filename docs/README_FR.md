<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>Chaque agent mérite son moment <b>aha</b> — le modèle raisonne, nous gérons tout le reste.</em></h3>


<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-démarrage-rapide"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
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
  🇫🇷 Français ·
  🇩🇪 <a href="README_DE.md">Deutsch</a> ·
  🇵🇹 <a href="README_PT.md">Português</a> ·
  🇷🇺 <a href="README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 Documentation</b></a> ·
  <a href="#-démarrage-rapide"><b>🚀 Démarrage rapide</b></a> ·
  <a href="#-modes-de-pipeline"><b>🔧 Modes</b></a> ·
  <a href="#-comparatif"><b>📊 Comparatif</b></a>
</p>

---

## ⚡ Installation rapide

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# C'est tout. Votre agent vient d'avoir son moment aha.
```

---

## 🔥 Actualités

- **[01/04/2026]** **v0.2.0 Publiée** : Modes de pipeline à trois niveaux (Core / Standard / Enhanced), diagnostics basés sur les traces, portes de validation d'interface, gestion de contexte améliorée. **958 tests réussis.**
- **[01/04/2026]** [**v0.1.0 Publiée**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0) : Pipeline de gouvernance en 6 étapes, correspondance de motifs de risque, constitution YAML, piste d'audit, profils multi-agents, persistance de session avec suivi des coûts.

---

## 🤔 Pourquoi *Aha* (**A**uto**Ha**rness) ?

> Dans l'entraînement des LLM, le ***moment aha*** est celui où le modèle apprend soudainement à raisonner.
>
> Pour les agents, le ***moment aha*** est celui où ils passent de "prêts pour la démo" à véritablement fiables.

L'écart est énorme : gestion du contexte, gouvernance des outils, contrôle des coûts, observabilité, persistance de session... Ce sont les patterns qui séparent un jouet d'un système. Nous appelons cela le **harness engineering**.

AutoHarness est un framework de gouvernance léger et multicouche **pour que chaque agent puisse avoir son *moment aha*.**

> **Agent = Modèle + Harnais.** Le modèle raisonne. Le harnais fait tout le reste.

---

## 🚀 Démarrage rapide

```python
# Encapsulez n'importe quel client LLM (2 lignes, gouvernance instantanée)
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
# Ou utilisez la boucle agent complète
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[Plus d'exemples →](features.md#cli)**

---

## ✨ Ce que vous obtenez

| Sans harnais | Avec AutoHarness |
|:-------------|:-----------------|
| L'agent exécute `rm -rf /`, rien ne l'arrête | Le **pipeline en 6 étapes** le bloque, l'enregistre et explique pourquoi |
| Le contexte explose au-delà de la limite de tokens | **Budget de tokens** + **troncature** gardent le contexte sous contrôle |
| Impossible de savoir quel appel d'outil a coûté combien | **Attribution des coûts par appel** avec tarification adaptée au modèle |
| L'injection de prompts passe à travers | **Validation en couches** : rails d'entrée, exécution, rails de sortie |
| Aucune piste d'audit pour la conformité | **Audit JSONL** enregistre chaque décision avec provenance complète |
| Les agents partagent un seul jeu de permissions | **Profils multi-agents** avec gouvernance basée sur les rôles |

### Architecture centrale : Pipeline de gouvernance en 6 étapes

Chaque appel d'outil traverse un pipeline structuré :

```
1. Analyser & Valider  →  2. Classifier le risque  →  3. Vérifier les permissions
4. Exécuter             →  5. Assainir la sortie    →  6. Journaliser l'audit
```

Les motifs de risque intégrés détectent les opérations dangereuses, l'exposition de secrets, la traversée de chemins, et plus encore.

### En chiffres

```
Pipeline de gouvernance en 6 étapes  ·  Correspondance de motifs de risque  ·  Constitution YAML
Gestion du budget de tokens           ·  Profils multi-agents               ·  Piste d'audit JSONL
2 lignes pour intégrer                ·  0 verrouillage fournisseur         ·  Licence MIT
```

---

## 🔧 Modes de pipeline

AutoHarness propose trois modes de pipeline. Choisissez le niveau de gouvernance adapté à vos besoins :

| Mode | Pipeline | Contexte | Multi-Agent | Cas d'utilisation |
|:-----|:---------|:---------|:------------|:------------------|
| **Core** | 6 étapes | Budget de tokens + troncature | Agent unique | Gouvernance légère |
| **Standard** | 8 étapes | + Microcompact + magasin de traces | Profils de base | Agents en production |
| **Enhanced** | 14 étapes | + Résumé par LLM + suppression d'images | Fork / Swarm / Arrière-plan | Gouvernance maximale |

```python
# Changer de mode via la constitution
# constitution.yaml
mode: core      # ou "standard" ou "enhanced"
```

```bash
# Ou via le CLI
autoharness mode enhanced
```

> **Le mode Enhanced est le mode par défaut.** Les utilisateurs bénéficient de la gouvernance la plus forte dès le départ. Passez en mode Core pour un overhead minimal.

> **[Comparaison complète des modes →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # Générer une constitution (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # Générer avec un mode de pipeline spécifique
autoharness mode                          # Afficher le mode de pipeline actuel
autoharness mode enhanced                 # Changer de mode de pipeline
autoharness validate constitution.yaml    # Valider un fichier de constitution
autoharness check --stdin --format json   # Vérifier un appel d'outil par rapport à vos règles
autoharness audit summary                 # Voir le résumé d'audit
autoharness install --target claude-code  # Installer comme hook Claude Code (une commande)
autoharness export --format cursor        # Exporter une constitution cross-harness
```

---

## 📊 Comparatif

| Capacité | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:---------|:---:|:---:|:---:|:---:|
| Pipeline de gouvernance d'outils | ✅ 6 étapes (jusqu'à 14) | ❌ | ⚠️ Sortie uniquement | ❌ |
| Gestion du contexte | ✅ Multicouche | ❌ | ❌ | ⚠️ Troncature |
| Profils multi-agents | ✅ | ✅ Graphe | ❌ | ⚠️ Handoff |
| Validation (entrée+sortie) | ✅ | ❌ | ✅ Rails | ❌ |
| Diagnostics basés sur les traces | ✅ | ❌ | ❌ | ❌ |
| Attribution des coûts | ✅ Par appel | ❌ | ❌ | ❌ |
| Verrouillage fournisseur | Aucun | LangChain | Aucun | OpenAI |
| Mise en place | 2 lignes | Graph DSL | RAIL XML | SDK |

---

## 🙏 Remerciements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) par Anthropic : patterns d'ingénierie qui ont inspiré certaines fonctionnalités de notre mode Enhanced
- [Codex](https://github.com/openai/codex) par OpenAI : pratiques d'ingénierie de contexte qui ont éclairé la conception de notre gestion de contexte

---

## 📌 Citation

Si vous utilisez AutoHarness dans vos recherches, veuillez citer :

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

## ⚠️ Avertissement

Certaines décisions architecturales du mode Enhanced ont été éclairées par des analyses publiques et des discussions communautaires sur la conception de Claude Code suite à sa publication involontaire via le registre npm d'Anthropic le 31-03-2026. Nous reconnaissons que le code source original de Claude Code est la propriété intellectuelle d'Anthropic. AutoHarness ne contient, ne redistribue ni ne traduit directement aucun code propriétaire d'Anthropic. Nous respectons les droits de PI d'Anthropic et répondrons rapidement à toute préoccupation — contactez-nous via [issue](https://github.com/aiming-lab/AutoHarness/issues) ou [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com).

---

## 📄 Licence

MIT. Voir [LICENSE](../LICENSE) pour les détails.
