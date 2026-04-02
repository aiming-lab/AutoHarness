"""Tool Registration and Registry.

Central registry for all tools with JSON Schema validation, concurrency flags,
and deferred loading support.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class ToolDefinition:
    """Complete definition of a registered tool."""
    name: str
    description: str
    input_schema: dict[str, Any]     # JSON Schema
    aliases: list[str] = field(default_factory=list)
    search_hint: str = ""            # 3-10 word capability phrase for ToolSearch
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    is_destructive: bool = False
    should_defer: bool = False       # Deferred loading flag
    always_load: bool = False        # Force include in initial prompt
    max_result_size_chars: int = 50_000
    source: str = "builtin"          # builtin | conditional | mcp | skill
    enabled: bool = True

    # Optional callbacks
    execute: Callable[..., Any] | None = None
    validate_input: Callable[[dict[str, Any]], bool] | None = None
    prompt_fn: Callable[[], str | None] | None = None

    def prompt(self) -> str | None:
        """Return this tool's system prompt contribution."""
        if self.prompt_fn:
            return self.prompt_fn()
        return None

    def to_api_schema(self) -> dict[str, Any]:
        """Convert to Anthropic API tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._aliases: dict[str, str] = {}  # alias -> canonical name

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._aliases[alias] = tool.name

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        tool = self._tools.pop(name, None)
        if tool:
            for alias in tool.aliases:
                self._aliases.pop(alias, None)

    def get(self, name: str) -> ToolDefinition | None:
        """Get tool by name or alias."""
        if name in self._tools:
            return self._tools[name]
        canonical = self._aliases.get(name)
        if canonical:
            return self._tools.get(canonical)
        return None

    def list_all(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_enabled(self) -> list[ToolDefinition]:
        """List only enabled tools."""
        return [t for t in self._tools.values() if t.enabled]

    def list_deferred(self) -> list[ToolDefinition]:
        """List tools marked for deferred loading."""
        return [t for t in self._tools.values() if t.should_defer and t.enabled]

    def list_immediate(self) -> list[ToolDefinition]:
        """List tools that should be loaded immediately (not deferred)."""
        return [
            t for t in self._tools.values()
            if (not t.should_defer or t.always_load) and t.enabled
        ]

    def to_api_schemas(self, include_deferred: bool = False) -> list[dict[str, Any]]:
        """Convert all enabled tools to API schema format."""
        tools = self.list_enabled() if include_deferred else self.list_immediate()
        return [t.to_api_schema() for t in tools]

    def get_tool_prompts(self) -> dict[str, str]:
        """Collect all tool prompt contributions."""
        prompts = {}
        for tool in self.list_enabled():
            p = tool.prompt()
            if p:
                prompts[tool.name] = p
        return prompts

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools or name in self._aliases
