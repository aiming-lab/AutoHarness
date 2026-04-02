#!/usr/bin/env python3
"""Skill System Demo — two-layer skill injection.

Shows how to:
  1. Create skill files in a temp directory
  2. Load skills into a SkillRegistry
  3. Use get_prompt_descriptions() for Layer 1 (system prompt)
  4. Use get_skill_body() for Layer 2 (on-demand injection)
  5. Invoke skills via SkillTool

Run:
    python examples/skill_system_demo.py
"""

import tempfile
from pathlib import Path

from autoharness.skills import (
    SkillRegistry,
    SkillTool,
    discover_skills,
    parse_skill_file,
)


def main() -> None:
    print("=" * 60)
    print("AutoHarness Skill System Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Create skill files in a temporary directory.
    #
    # Each skill lives in its own directory with a SKILL.md file
    # containing YAML frontmatter + markdown body.
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)

        # Skill 1: commit
        commit_dir = skills_dir / "commit"
        commit_dir.mkdir()
        (commit_dir / "SKILL.md").write_text("""\
---
name: commit
description: Create a well-formatted git commit with conventional commit style
allowed-tools: [Bash, Read, Grep]
model: haiku
tags: [git, workflow]
---

# Git Commit Skill

When the user asks you to commit changes, follow these steps:

1. Run `git status` to see all changes
2. Run `git diff --staged` to review staged changes
3. Analyze the changes and determine the commit type (feat/fix/refactor/docs/test)
4. Draft a commit message following Conventional Commits:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `refactor:` for code restructuring
5. Create the commit with `git commit -m "..."`
""", encoding="utf-8")

        # Skill 2: review-pr
        review_dir = skills_dir / "review-pr"
        review_dir.mkdir()
        (review_dir / "SKILL.md").write_text("""\
---
name: review-pr
description: Review a GitHub pull request for code quality and correctness
allowed-tools: [Bash, Read, Grep, Glob]
model: sonnet
tags: [github, code-review]
version: "1.0"
---

# PR Review Skill

Review the specified pull request thoroughly:

1. Fetch PR details with `gh pr view <number>`
2. Read the diff with `gh pr diff <number>`
3. Check for:
   - Logic errors
   - Missing error handling
   - Security issues
   - Test coverage gaps
4. Post your review with `gh pr review`
""", encoding="utf-8")

        # Skill 3: disabled skill (should not appear in Layer 1)
        disabled_dir = skills_dir / "deprecated-tool"
        disabled_dir.mkdir()
        (disabled_dir / "SKILL.md").write_text("""\
---
name: deprecated-tool
description: This skill is disabled
disabled: true
---

This skill should not be loaded.
""", encoding="utf-8")

        print(f"\n1. Created 3 skill files in {skills_dir}")

        # ------------------------------------------------------------------
        # 2. Discover and load skills into a SkillRegistry.
        # ------------------------------------------------------------------
        skills = discover_skills(skills_dir)
        print(f"\n2. Discovered {len(skills)} skills:")
        for skill in skills:
            status = "DISABLED" if skill.metadata.disabled else "enabled"
            print(f"   {skill.metadata.name} ({status}): {skill.metadata.description}")

        registry = SkillRegistry()
        for skill in skills:
            registry.register(skill)

        print(f"\n   Registry: {len(registry)} total, {len(registry.list_enabled())} enabled")

        # ------------------------------------------------------------------
        # 3. Layer 1: get_prompt_descriptions() for system prompt injection.
        #
        # This is a lightweight summary (~100 tokens per skill) included
        # in every API call's system prompt so the model knows what skills
        # are available.
        # ------------------------------------------------------------------
        print("\n3. Layer 1 — System prompt descriptions:")
        print("-" * 40)
        descriptions = registry.get_prompt_descriptions()
        print(descriptions)
        print("-" * 40)

        # ------------------------------------------------------------------
        # 4. Layer 2: get_skill_body() for on-demand full content.
        #
        # When the model decides to invoke a skill, the full markdown body
        # is injected as a tool result. This is the "two-layer" pattern:
        # Layer 1 is always present, Layer 2 only when needed.
        # ------------------------------------------------------------------
        print("\n4. Layer 2 — On-demand skill body:")
        body = registry.get_skill_body("commit")
        print("   get_skill_body('commit'):")
        for line in body.split("\n")[:5]:
            print(f"     {line}")
        print(f"     ... ({len(body)} chars total)")

        # Error cases
        print(f"\n   get_skill_body('nonexistent'): {registry.get_skill_body('nonexistent')}")
        print(f"   get_skill_body('deprecated-tool'): {registry.get_skill_body('deprecated-tool')}")

        # ------------------------------------------------------------------
        # 5. SkillTool — the model-callable interface.
        #
        # The model calls SkillTool.execute(skill="commit") and receives
        # the full body wrapped in XML tags for structured injection.
        # ------------------------------------------------------------------
        print("\n5. SkillTool usage:")
        skill_tool = SkillTool(registry)

        # Show the tool's API schema
        schema = skill_tool.to_api_schema()
        print(f"   Tool schema: name={schema['name']}")

        # Execute a skill (what the model would call)
        result = skill_tool.execute("commit")
        print("\n   skill_tool.execute('commit'):")
        for line in result.split("\n")[:4]:
            print(f"     {line}")

        # Execute with arguments
        result = skill_tool.execute("review-pr", args="123")
        print("\n   skill_tool.execute('review-pr', args='123'):")
        for line in result.split("\n")[:4]:
            print(f"     {line}")

        # ------------------------------------------------------------------
        # 6. Parse a skill file directly (for programmatic skill creation).
        # ------------------------------------------------------------------
        print("\n6. Direct skill file parsing:")
        custom_content = """\
---
name: custom-lint
description: Run project-specific linting rules
allowed-tools: [Bash]
model: haiku
effort: 5m
tags: [lint, quality]
---

Run `npm run lint` and report any issues.
"""
        parsed = parse_skill_file(custom_content, source_path="<inline>")
        meta = parsed.metadata
        print(f"   Name: {meta.name}")
        print(f"   Description: {meta.description}")
        print(f"   Allowed tools: {meta.allowed_tools}")
        print(f"   Model: {meta.model}")
        print(f"   Tags: {meta.tags}")
        print(f"   Body: {parsed.body}")

    print("\nDone.")


if __name__ == "__main__":
    main()
