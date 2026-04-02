"""Skill frontmatter parsing — YAML metadata extraction from skill files.

Skill files use YAML frontmatter (---\n...\n---) followed by a markdown body.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)

@dataclass
class SkillMetadata:
    """Parsed skill metadata from YAML frontmatter."""
    name: str
    description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None            # Recommended model (haiku/sonnet/opus)
    effort: str | None = None           # Expected effort (e.g., "20m")
    disabled: bool = False
    version: str | None = None
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

@dataclass
class ParsedSkill:
    """A fully parsed skill with metadata and body."""
    metadata: SkillMetadata
    body: str                           # Markdown content after frontmatter
    source_path: str = ""               # File path where loaded from

def parse_skill_file(content: str, source_path: str = "") -> ParsedSkill:
    """Parse a skill file with YAML frontmatter + markdown body.

    Format:
        ---
        name: skill-name
        description: What this skill does
        allowed-tools: [Read, Edit, Bash]
        model: haiku
        ---

        # Skill Body
        Instructions here...

    Raises ValueError if frontmatter is missing or invalid.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(
            f"Invalid skill file format: missing YAML frontmatter"
            f" in {source_path or '<string>'}"
        )

    yaml_str, body = match.group(1), match.group(2)

    try:
        data = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter in {source_path or '<string>'}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Frontmatter must be a YAML mapping, got {type(data).__name__}")

    name = data.pop("name", "")
    if not name:
        raise ValueError(
            f"Skill must have a 'name' field in frontmatter:"
            f" {source_path or '<string>'}"
        )

    metadata = SkillMetadata(
        name=name,
        description=data.pop("description", ""),
        allowed_tools=data.pop("allowed-tools", data.pop("allowed_tools", [])),
        model=data.pop("model", None),
        effort=data.pop("effort", None),
        disabled=data.pop("disabled", False),
        version=data.pop("version", None),
        tags=data.pop("tags", []),
        extra=data,  # Remaining fields
    )

    return ParsedSkill(
        metadata=metadata,
        body=body.strip(),
        source_path=source_path,
    )
