"""Agent definition format — YAML frontmatter + Markdown prompt.
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
class AgentDefinition:
    """Complete definition of an agent type."""
    name: str
    description: str = ""
    tools: list[str] = field(default_factory=list)
    model: str | None = None
    permission_mode: str = "default"
    max_iterations: int = 30
    is_read_only: bool = False
    prompt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

def parse_agent_file(content: str, source_path: str = "") -> AgentDefinition:
    """Parse an agent definition file (YAML frontmatter + markdown prompt)."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(
            f"Invalid agent file format: missing YAML frontmatter"
            f" in {source_path or '<string>'}"
        )

    yaml_str, body = match.group(1), match.group(2)

    try:
        data = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in agent file {source_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Agent frontmatter must be a mapping, got {type(data).__name__}")

    name = data.pop("name", "")
    if not name:
        raise ValueError(f"Agent must have a 'name' field: {source_path}")

    return AgentDefinition(
        name=name,
        description=data.pop("description", ""),
        tools=data.pop("tools", []),
        model=data.pop("model", None),
        permission_mode=data.pop("permission_mode", data.pop("mode", "default")),
        max_iterations=data.pop("max_iterations", 30),
        is_read_only=data.pop("is_read_only", data.pop("read_only", False)),
        prompt=body.strip(),
        extra=data,
    )
