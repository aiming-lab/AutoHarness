# Contributing to AutoHarness

Thank you for your interest in contributing to AutoHarness! This document covers the development setup, coding standards, and contribution process.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/aiming-lab/AutoHarness.git
cd autoharness

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

**Python version**: 3.10 or higher is required.

## Running Tests

```bash
# Quick run
make test

# Verbose output
make test-verbose

# Run a specific test file
python -m pytest tests/test_risk.py -v

# Run with coverage
python -m pytest tests/ --cov=autoharness --cov-report=term-missing
```

## Code Style

We use **ruff** for both linting and formatting.

```bash
# Lint
make lint

# Auto-format
make format

# Type checking
make typecheck
```

**Key rules:**

- Line length: 100 characters
- Target: Python 3.10+
- Ruff rule sets: E, F, W, I, N, UP, B, SIM, RUF
- Type annotations are required for all public APIs
- Strict mypy is enabled (`strict = true` in pyproject.toml)

## Architecture Overview

```
autoharness/
├── core/            # Governance engine, permission engine, risk classifier,
│                    #   audit engine, constitution system, hook system,
│                    #   anti-distillation, sentiment analysis, feature flags
├── agent_loop.py    # Main agent execution loop integrating all subsystems
├── context/         # Context engine with 5-layer compaction
├── prompt/          # Prompt architecture and section framework
├── tools/           # Tool registry, concurrent orchestration, output budgets
├── skills/          # Skill system with two-layer injection
├── agents/          # Agent orchestration (fork, swarm, background, worktree),
│                    #   intelligent model routing (FAST/STANDARD/PREMIUM)
├── session/         # Session persistence, resume, cost tracking
├── tasks/           # Task system with dependency graph
├── rules/           # Hook profiles, 4-axis risk scoring
├── compiler/        # System prompt compilation
├── observability/   # Metrics and tracing
├── integrations/    # Anthropic, OpenAI, LangChain wrappers
├── templates/       # Built-in constitution and profile templates
├── marketplace/     # Skill/tool marketplace
├── cli/             # CLI commands (run, tools, skills, session, context)
└── wrap.py          # High-level wrapper API
```

## Areas for Contribution

We welcome contributions in any area, but these are particularly impactful:

- **Anti-distillation** (`core/anti_distillation.py`) -- improve decoy tool strategies and detection heuristics
- **Sentiment analysis** (`core/sentiment.py`) -- expand frustration detection patterns and add support for additional languages
- **Model routing** (`agents/model_router.py`) -- add new routing tiers, improve task complexity estimation
- **Feature flags** (`core/feature_flags.py`) -- add persistent flag storage backends, admin UI integration
- **Context management** (`context/`) -- improve compaction quality, add new compaction strategies
- **Constitution templates** -- new industry-specific templates (e.g., healthcare, education)
- **Integration wrappers** -- support for additional LLM providers (e.g., Gemini, Mistral)
- **Test coverage** -- we currently have 920 tests; help us expand edge case coverage

## Pull Request Process

1. **Fork** the repository and create a feature branch from `main`.
2. **Write tests** for any new functionality or bug fixes.
3. **Ensure all checks pass** before submitting:
   ```bash
   make lint format typecheck test
   ```
4. **Open a PR** against `main` with a clear description of:
   - What the change does
   - Why it is needed
   - How it was tested
5. A maintainer will review your PR. Address any feedback, then it will be merged.

## Commit Messages

Use clear, imperative-mood commit messages:

- `Add session resume briefing support`
- `Fix risk scoring for nested tool calls`
- `Update context compaction thresholds`

## Reporting Issues

Open an issue on GitHub with:

- Steps to reproduce
- Expected vs. actual behavior
- Python version and OS
- Relevant logs or tracebacks

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
