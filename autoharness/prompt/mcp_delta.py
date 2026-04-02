"""MCP instruction delta injection.

Instead of recomputing MCP instructions every turn (which breaks prompt cache),
only inject delta when MCP servers connect/disconnect.
"""

from __future__ import annotations


class McpInstructionManager:
    """Manages MCP server instructions with delta injection."""

    def __init__(self) -> None:
        self._known_servers: set[str] = set()
        self._instructions: dict[str, str] = {}

    def update_servers(self, current_servers: dict[str, str]) -> str | None:
        """Update known servers and return delta instruction if changed.

        Parameters
        ----------
        current_servers
            Mapping of server name to its instruction string.

        Returns
        -------
        str | None
            A delta instruction string if servers changed, None otherwise.
        """
        current_set = set(current_servers.keys())
        if current_set == self._known_servers:
            return None

        added = current_set - self._known_servers
        removed = self._known_servers - current_set
        self._known_servers = current_set
        self._instructions = dict(current_servers)

        parts: list[str] = []
        if added:
            parts.append(f"MCP servers connected: {', '.join(sorted(added))}")
            for name in sorted(added):
                if current_servers[name]:
                    parts.append(f"  {name}: {current_servers[name]}")
        if removed:
            parts.append(f"MCP servers disconnected: {', '.join(sorted(removed))}")

        return "\n".join(parts) if parts else None

    def get_full_instructions(self) -> str:
        """Get full MCP instructions (for initial prompt or post-compact)."""
        if not self._instructions:
            return ""
        lines: list[str] = ["# MCP Server Instructions"]
        for name, instruction in sorted(self._instructions.items()):
            lines.append(f"## {name}")
            if instruction:
                lines.append(instruction)
        return "\n\n".join(lines)
