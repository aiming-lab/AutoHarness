# Installation

## Requirements

- Python 3.10 or later
- An LLM API key (Anthropic recommended, OpenAI supported)

## Install from PyPI

```bash
pip install autoharness
```

## Install with extras

```bash
# Include OpenAI wrapper support
pip install autoharness[openai]

# Include development tools
pip install autoharness[dev]

# Everything
pip install autoharness[all]
```

## Install from source

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd autoharness
pip install -e ".[dev]"
```

## Verify installation

```bash
autoharness version
```

```
AutoHarness v0.1.0
```

## Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or pass it directly:

```python
from autoharness import AgentLoop

loop = AgentLoop(model="claude-sonnet-4-6", api_key="sk-ant-...")
```

!!! tip
    Store your API key in a `.env` file (gitignored) rather than exporting it in your shell profile.

## What's next?

Head to the [Quickstart](quickstart.md) to build your first governed agent in under 5 minutes.
