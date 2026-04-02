# API Reference: Prompt System

## `SystemPromptRegistry`

```python
from autoharness import SystemPromptRegistry
```

Registry for composable, cacheable system prompt sections.

### Methods

#### `register_static(section: SystemPromptSection) -> None`

Register a static (cacheable) section. Static sections are computed once and cached.

#### `register_dynamic(section: SystemPromptSection) -> None`

Register a dynamic section. Dynamic sections are recomputed every time the prompt is built.

#### `build_system_prompt() -> str`

Assemble all sections into the final system prompt string. Static sections come first (cache-stable prefix), followed by dynamic sections.

### Example

```python
from autoharness import SystemPromptRegistry, system_prompt_section
from autoharness.prompt.sections import uncached_section

registry = SystemPromptRegistry()

# Static section -- cached across turns
registry.register_static(
    system_prompt_section(
        "identity",
        lambda: "You are a helpful AI assistant.",
    )
)

# Dynamic section -- recomputed each turn
registry.register_dynamic(
    uncached_section(
        "context",
        lambda: f"Current time: {datetime.now().isoformat()}",
        reason="Time changes each turn",
    )
)

prompt = registry.build_system_prompt()
```

## `system_prompt_section`

```python
from autoharness import system_prompt_section
```

```python
system_prompt_section(name: str, compute: Callable[[], str]) -> SystemPromptSection
```

Create a cacheable prompt section.

## `uncached_section`

```python
from autoharness.prompt.sections import uncached_section
```

```python
uncached_section(name: str, compute: Callable[[], str | None], reason: str) -> SystemPromptSection
```

Create a dynamic prompt section that is recomputed each turn. The `reason` documents why caching is not possible.

## Cache boundary

The system prompt is divided into two zones:

1. **Static prefix** -- identity, governance rules, tool instructions. Cached across turns.
2. **Dynamic suffix** -- skills, environment info, session context. Recomputed each turn.

This boundary enables prompt cache hits when only dynamic content changes between turns.
