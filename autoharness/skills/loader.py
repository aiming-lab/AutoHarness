"""Skill loading and registration — directory scanning with two-layer injection.

Layer 1 (System Prompt): Skill name + description (~100 tokens each)
Layer 2 (Tool Result): Full body injected on-demand (~2000 tokens each)

Discovery directories:
- .autoharness/skills/ — project-level
- ~/.autoharness/skills/ — global-level
"""
from __future__ import annotations

import logging
from pathlib import Path

from autoharness.skills.frontmatter import ParsedSkill, parse_skill_file

logger = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"

class SkillRegistry:
    """Registry of loaded skills with two-layer injection support."""

    def __init__(self) -> None:
        self._skills: dict[str, ParsedSkill] = {}

    def register(self, skill: ParsedSkill) -> None:
        """Register a parsed skill."""
        self._skills[skill.metadata.name] = skill

    def get(self, name: str) -> ParsedSkill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_all(self) -> list[ParsedSkill]:
        """List all registered skills."""
        return list(self._skills.values())

    def list_enabled(self) -> list[ParsedSkill]:
        """List only non-disabled skills."""
        return [s for s in self._skills.values() if not s.metadata.disabled]

    def get_prompt_descriptions(self) -> str:
        """Layer 1: Generate skill descriptions for system prompt injection.

        Returns a formatted string listing all enabled skills with their
        descriptions, suitable for inclusion in the system prompt.
        """
        enabled = self.list_enabled()
        if not enabled:
            return ""

        lines = ["The following skills are available for use with the Skill tool:\n"]
        for skill in sorted(enabled, key=lambda s: s.metadata.name):
            desc = skill.metadata.description or "No description"
            lines.append(f"- {skill.metadata.name}: {desc}")

        return "\n".join(lines)

    def get_skill_body(self, name: str) -> str:
        """Layer 2: Get the full skill body for on-demand injection.

        Returns the markdown body content, or an error message if not found.
        """
        skill = self._skills.get(name)
        if skill is None:
            return f"Error: Unknown skill '{name}'"
        if skill.metadata.disabled:
            return f"Error: Skill '{name}' is currently disabled"
        return skill.body

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


def discover_skills(*search_dirs: str | Path) -> list[ParsedSkill]:
    """Discover skill files from multiple directories.

    Scans each directory for subdirectories containing SKILL.md files.
    Later directories override earlier ones (for project > global precedence).

    Directory structure:
        skills/
          skill-name/
            SKILL.md
    """
    skills: dict[str, ParsedSkill] = {}

    for search_dir in search_dirs:
        dir_path = Path(search_dir)
        if not dir_path.is_dir():
            continue

        for skill_dir in sorted(dir_path.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / SKILL_FILENAME
            if not skill_file.is_file():
                continue

            try:
                content = skill_file.read_text(encoding="utf-8")
                skill = parse_skill_file(content, str(skill_file))
                skills[skill.metadata.name] = skill
                logger.debug("Discovered skill: %s from %s", skill.metadata.name, skill_file)
            except (ValueError, OSError) as exc:
                logger.warning("Failed to load skill from %s: %s", skill_file, exc)

    return list(skills.values())


def load_skills_into_registry(
    registry: SkillRegistry,
    project_dir: str | Path | None = None,
    global_dir: str | Path | None = None,
) -> int:
    """Discover and load skills into a registry.

    Returns the number of skills loaded.
    """
    search_dirs: list[str | Path] = []

    if global_dir:
        search_dirs.append(global_dir)
    else:
        default_global = Path.home() / ".autoharness" / "skills"
        if default_global.is_dir():
            search_dirs.append(default_global)

    if project_dir:
        search_dirs.append(project_dir)
    else:
        default_project = Path(".autoharness") / "skills"
        if default_project.is_dir():
            search_dirs.append(default_project)

    skills = discover_skills(*search_dirs)
    for skill in skills:
        registry.register(skill)

    return len(skills)
