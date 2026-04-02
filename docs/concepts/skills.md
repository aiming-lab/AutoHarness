# Skill System

Skills are reusable instructions that the model can load on demand. They use a **two-layer injection** pattern to minimize context usage while keeping capabilities discoverable.

## Two-layer injection

| Layer | What's loaded | Token cost | When |
|-------|--------------|------------|------|
| **Layer 1 (prompt)** | Skill name + description | ~100 tokens each | Always in system prompt |
| **Layer 2 (on-demand)** | Full skill body | ~2,000 tokens | Only when model invokes the skill |

This means 50 skills cost only ~5,000 tokens in the prompt, while the full instructions (~100,000 tokens) are loaded only when needed.

## Skill file format

Skills are markdown files with YAML frontmatter:

```yaml
---
name: review-pr
description: "Review a pull request for code quality and security"
allowed-tools: [Read, Grep, Glob, Bash]
model: sonnet
effort: 15m
---

# PR Review Skill

When reviewing a pull request:

1. Read the diff with `git diff main...HEAD`
2. Check for security issues (secrets, SQL injection, XSS)
3. Verify test coverage for changed files
4. Check code style consistency
5. Write a summary with actionable feedback
```

## Frontmatter fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `str` | Yes | Skill identifier (used in `/skill-name`) |
| `description` | `str` | Yes | One-line description shown in prompt |
| `allowed-tools` | `list[str]` | No | Tools this skill can use |
| `model` | `str` | No | Recommended model (`haiku`, `sonnet`, `opus`) |
| `effort` | `str` | No | Expected duration (e.g., `"20m"`) |
| `disabled` | `bool` | No | Set `true` to disable without deleting |

## Discovery directories

Skills are discovered from two locations:

| Directory | Scope |
|-----------|-------|
| `.autoharness/skills/` | Project-level (per-repo) |
| `~/.autoharness/skills/` | Global (all projects) |

Project-level skills take priority over global skills with the same name.

## Using skills in AgentLoop

```python
from autoharness import AgentLoop

loop = AgentLoop(
    model="claude-sonnet-4-6",
    skills_dir=".autoharness/skills/",
)
# Skills are auto-discovered and injected into the prompt.
# The model can invoke them via the Skill tool.
result = loop.run("Review the latest PR")
```

## Programmatic skill registration

```python
from autoharness import SkillRegistry, ParsedSkill
from autoharness.skills.frontmatter import SkillMetadata

registry = SkillRegistry()
registry.register(ParsedSkill(
    metadata=SkillMetadata(
        name="deploy",
        description="Deploy to staging environment",
        allowed_tools=["Bash"],
    ),
    body="Run `./deploy.sh staging` and verify health checks pass.",
))
```

## Related pages

- [Tool System](tools.md) -- skills interact with the tool registry
- [Agent Loop](agent-loop.md) -- how skills are injected into the prompt
- [Skill API Reference](../api/skills.md) -- full API details
