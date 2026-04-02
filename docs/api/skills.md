# API Reference: Skill System

## `ParsedSkill`

```python
from autoharness import ParsedSkill
```

A fully parsed skill with metadata and body.

```python
@dataclass
class ParsedSkill:
    metadata: SkillMetadata
    body: str               # Markdown content after frontmatter
    source_path: str = ""   # File path where loaded from
```

## `SkillMetadata`

```python
from autoharness.skills.frontmatter import SkillMetadata
```

```python
@dataclass
class SkillMetadata:
    name: str
    description: str = ""
    allowed_tools: list[str] = []
    model: str | None = None
    effort: str | None = None
    disabled: bool = False
    version: str | None = None
    tags: list[str] = []
    extra: dict[str, Any] = {}
```

## `SkillRegistry`

```python
from autoharness import SkillRegistry
```

Registry for discovered and loaded skills.

### Methods

#### `register(skill: ParsedSkill) -> None`

Register a parsed skill.

#### `get(name: str) -> ParsedSkill | None`

Get a skill by name.

#### `get_prompt_descriptions() -> str | None`

Get Layer 1 descriptions for all registered skills (for system prompt injection). Returns `None` if no skills are registered.

## `parse_skill_file`

```python
from autoharness.skills.frontmatter import parse_skill_file

skill = parse_skill_file(content: str, source_path: str = "") -> ParsedSkill
```

Parse a skill file with YAML frontmatter + markdown body. Raises `ValueError` if frontmatter is missing or invalid.

### Example

```python
content = """---
name: deploy
description: Deploy to staging
allowed-tools: [Bash]
---

Run `./deploy.sh staging` and verify the health check.
"""

skill = parse_skill_file(content, source_path="skills/deploy.md")
print(skill.metadata.name)           # "deploy"
print(skill.metadata.allowed_tools)  # ["Bash"]
print(skill.body)                    # "Run `./deploy.sh staging`..."
```
