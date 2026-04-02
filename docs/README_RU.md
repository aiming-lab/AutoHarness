<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>Каждый агент заслуживает момента <b>aha</b> — модель рассуждает, мы берём на себя всё остальное.</em></h3>

<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-быстрый-старт"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
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
  <a href="README_PT.md">🇵🇹 Português</a> ·
  🇷🇺 Русский
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 Документация</b></a> ·
  <a href="#-быстрая-установка"><b>⚡ Быстрая установка</b></a> ·
  <a href="#-быстрый-старт"><b>🚀 Быстрый старт</b></a> ·
  <a href="#-что-вы-получаете"><b>✨ Возможности</b></a> ·
  <a href="#-сравнение"><b>📊 Сравнение</b></a>
</p>

---

## ⚡ Быстрая установка

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# Вот и всё. У вашего агента только что наступил момент aha.
```

---

## 🔥 Новости

- **[01.04.2026]** **Выпуск v0.2.0**: Три режима конвейера (Core / Standard / Enhanced), диагностика на основе трейсов, валидационные шлюзы интерфейсов, улучшенное управление контекстом. **958 тестов пройдено.**
- **[01.04.2026]** [**Выпуск v0.1.0**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0): 6-шаговый конвейер управления, сопоставление паттернов риска, YAML-конституция, аудит-трасса, мульти-агентные профили, персистентность сессий с отслеживанием затрат.

---

## 🤔 Почему *Aha* (**A**uto**Ha**rness)?

> В обучении LLM ***момент aha*** — это когда модель внезапно учится рассуждать.
>
> Для агентов ***момент aha*** — это когда они переходят от «готов к демо» к по-настоящему надёжным.

Разрыв огромен: управление контекстом, управление инструментами, контроль затрат, наблюдаемость, персистентность сессий... Это паттерны, которые отделяют игрушку от системы. Мы называем это **harness-инженерия**.

AutoHarness — это легковесный, многоуровневый фреймворк управления, **чтобы каждый агент мог пережить свой *момент aha*.**

> **Агент = Модель + Harness.** Модель рассуждает. Harness делает всё остальное.

---

## 🚀 Быстрый старт

```python
# Оберните любой LLM-клиент (2 строки, мгновенное управление)
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
# Или используйте полный цикл агента
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[Больше примеров →](features.md#cli)**

---

## ✨ Что вы получаете

| Без Harness | С AutoHarness |
|:------------|:--------------|
| Агент выполняет `rm -rf /`, ничто его не останавливает | **6-шаговый конвейер** блокирует, логирует и объясняет почему |
| Контекст превышает лимит токенов | **Бюджет токенов** + **усечение** держат контекст под контролем |
| Непонятно, какой вызов инструмента сколько стоил | **Атрибуция затрат по вызову** с учётом цен модели |
| Инъекция промптов проходит незамеченной | **Многоуровневая валидация**: входные рельсы, выполнение, выходные рельсы |
| Нет аудит-трассы для соответствия требованиям | **JSONL-аудит** фиксирует каждое решение с полной историей |
| Агенты используют один набор разрешений | **Мульти-агентные профили** с управлением на основе ролей |

### Центральная архитектура: 6-шаговый конвейер управления

Каждый вызов инструмента проходит через структурированный конвейер:

```
1. Parse & Validate  →  2. Risk Classify  →  3. Permission Check
4. Execute           →  5. Output Sanitize →  6. Audit Log
```

Встроенные паттерны риска обнаруживают опасные операции, утечку секретов, обход путей и многое другое.

### В цифрах

```
6-шаговый конвейер управления      ·  Сопоставление паттернов риска  ·  YAML-конституция
Управление бюджетом токенов        ·  Мульти-агентные профили         ·  JSONL аудит-трасса
2 строки для интеграции             ·  0 привязки к поставщику         ·  Лицензия MIT
```

---

## 🔧 Режимы конвейера

AutoHarness поддерживает три режима конвейера. Выберите уровень управления, подходящий для ваших задач:

| Режим | Конвейер | Контекст | Мульти-агент | Применение |
|:------|:---------|:---------|:-------------|:-----------|
| **Core** | 6 шагов | Бюджет токенов + усечение | Один агент | Легковесное управление |
| **Standard** | 8 шагов | + Microcompact + хранилище трейсов | Базовые профили | Продакшн-агенты |
| **Enhanced** | 14 шагов | + LLM-суммаризация + удаление изображений | Fork / Swarm / Background | Максимальное управление |

```python
# Переключение режимов через конституцию
# constitution.yaml
mode: core      # или "standard" или "enhanced"
```

```bash
# Или через CLI
autoharness mode enhanced
```

> **Режим Enhanced установлен по умолчанию.** Пользователи получают максимальное управление из коробки. Переключитесь на Core для минимальной нагрузки.

> **[Полное сравнение режимов →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # Сгенерировать конституцию (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # Сгенерировать с определённым режимом конвейера
autoharness mode                          # Показать текущий режим конвейера
autoharness mode enhanced                 # Переключить режим конвейера
autoharness validate constitution.yaml    # Валидировать файл конституции
autoharness check --stdin --format json   # Проверить вызов инструмента по вашим правилам
autoharness audit summary                 # Просмотр сводки аудита
autoharness install --target claude-code  # Установить как хук Claude Code (одна команда)
autoharness export --format cursor        # Экспортировать кросс-harness конституцию
```

---

## 📊 Сравнение

| Возможность | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:------------|:---:|:---:|:---:|:---:|
| Конвейер управления инструментами | ✅ 6 шагов (до 14) | ❌ | ⚠️ Только выход | ❌ |
| Управление контекстом | ✅ Многоуровневое | ❌ | ❌ | ⚠️ Усечение |
| Мульти-агентные профили | ✅ | ✅ Графы | ❌ | ⚠️ Handoff |
| Валидация (вход+выход) | ✅ | ❌ | ✅ Rails | ❌ |
| Диагностика на основе трейсов | ✅ | ❌ | ❌ | ❌ |
| Атрибуция затрат | ✅ По вызову | ❌ | ❌ | ❌ |
| Привязка к поставщику | Нет | LangChain | Нет | OpenAI |
| Настройка | 2 строки | Graph DSL | RAIL XML | SDK |

---

## 🙏 Благодарности

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) от Anthropic: инженерные паттерны, вдохновившие некоторые возможности нашего режима Enhanced
- [Codex](https://github.com/openai/codex) от OpenAI: практики контекстной инженерии, повлиявшие на архитектуру нашего управления контекстом

---

## 📌 Цитирование

Если вы используете AutoHarness в своих исследованиях, пожалуйста, укажите:

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

## ⚠️ Отказ от ответственности

Некоторые архитектурные решения в режиме Enhanced были основаны на публично доступном анализе и обсуждениях сообщества относительно дизайна Claude Code после его непреднамеренной публикации через npm-реестр Anthropic 31.03.2026. Мы признаём, что оригинальный исходный код Claude Code является интеллектуальной собственностью Anthropic. AutoHarness не содержит, не распространяет и не переводит напрямую какой-либо проприетарный код Anthropic. Мы уважаем права ИС Anthropic и оперативно рассмотрим любые вопросы — свяжитесь с нами через [issue](https://github.com/aiming-lab/AutoHarness/issues) или [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com).

---

## 📄 Лицензия

MIT — подробности в [LICENSE](../LICENSE).
