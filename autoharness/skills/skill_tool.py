"""Skill Tool — model-callable interface for on-demand skill loading.

The model calls this tool to get the full body of a skill.
This implements the Layer 2 injection pattern.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SKILL_TOOL_SCHEMA = {
    "name": "Skill",
    "description": (
        "Execute a skill within the current conversation. "
        "Use this when the user asks to perform a task "
        "that matches an available skill."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "The skill name to invoke.",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments for the skill.",
            },
        },
        "required": ["skill"],
    },
}

class SkillTool:
    """Tool interface for skill invocation by the model."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def execute(self, skill: str, args: str = "") -> str:
        """Execute a skill by name, returning its full body.

        The model receives the skill's markdown instructions and
        should follow them to complete the task.
        """
        body = self.registry.get_skill_body(skill)

        if args:
            return (
                f"<command-name>{skill}</command-name>\n"
                f"<command-args>{args}</command-args>\n\n{body}"
            )

        return f"<command-name>{skill}</command-name>\n\n{body}"

    def to_api_schema(self) -> dict[str, Any]:
        """Return the tool schema for API registration."""
        return SKILL_TOOL_SCHEMA
