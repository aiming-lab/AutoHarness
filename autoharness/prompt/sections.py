"""System prompt section framework with caching and cache boundary support.

Separates static (globally cacheable) prompt sections from dynamic
(per-session) sections using a boundary marker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"


@dataclass
class SystemPromptSection:
    """A named section of the system prompt."""

    name: str
    compute: Callable[[], str | None]
    cache_break: bool = False
    _reason: str = ""  # Why this section breaks cache (for uncached sections)


def system_prompt_section(
    name: str, compute: Callable[[], str | None]
) -> SystemPromptSection:
    """Create a cacheable system prompt section."""
    return SystemPromptSection(name=name, compute=compute)


def uncached_section(
    name: str, compute: Callable[[], str | None], reason: str
) -> SystemPromptSection:
    """Create a non-cacheable section (recomputed every turn)."""
    return SystemPromptSection(name=name, compute=compute, cache_break=True, _reason=reason)


class SystemPromptRegistry:
    """Registry of system prompt sections with caching.

    Sections registered before the dynamic boundary are static/cacheable.
    Sections registered after are dynamic/per-session.
    """

    def __init__(self) -> None:
        self._static_sections: list[SystemPromptSection] = []
        self._dynamic_sections: list[SystemPromptSection] = []
        self._cache: dict[str, str | None] = {}
        self._names: set[str] = set()

    def register_static(self, section: SystemPromptSection) -> None:
        """Register a section in the static (cacheable) prefix."""
        if section.name in self._names:
            raise ValueError(f"Duplicate section name: {section.name}")
        self._names.add(section.name)
        self._static_sections.append(section)

    def register_dynamic(self, section: SystemPromptSection) -> None:
        """Register a section in the dynamic (per-session) suffix."""
        if section.name in self._names:
            raise ValueError(f"Duplicate section name: {section.name}")
        self._names.add(section.name)
        self._dynamic_sections.append(section)

    def resolve_all(self) -> list[str]:
        """Resolve all sections into a list of strings.

        Static sections are cached; dynamic sections recomputed each time.
        Returns list with boundary marker between static and dynamic parts.
        """
        parts: list[str] = []

        # Static sections (cached)
        for section in self._static_sections:
            value = self._resolve_section(section, use_cache=True)
            if value:
                parts.append(value)

        # Boundary marker
        parts.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)

        # Dynamic sections (always recomputed)
        for section in self._dynamic_sections:
            value = self._resolve_section(section, use_cache=False)
            if value:
                parts.append(value)

        return parts

    def resolve_static_prefix(self) -> list[str]:
        """Resolve only the static cacheable prefix."""
        parts: list[str] = []
        for section in self._static_sections:
            value = self._resolve_section(section, use_cache=True)
            if value:
                parts.append(value)
        return parts

    def resolve_dynamic_suffix(self) -> list[str]:
        """Resolve only the dynamic per-session suffix."""
        parts: list[str] = []
        for section in self._dynamic_sections:
            value = self._resolve_section(section, use_cache=False)
            if value:
                parts.append(value)
        return parts

    def build_system_prompt(self) -> str:
        """Build the complete system prompt as a single string."""
        parts = self.resolve_all()
        # Remove the boundary marker from the final string
        return "\n\n".join(p for p in parts if p != SYSTEM_PROMPT_DYNAMIC_BOUNDARY)

    def clear_cache(self) -> None:
        """Clear all cached section values. Called on /clear and /compact."""
        self._cache.clear()

    def _resolve_section(
        self, section: SystemPromptSection, use_cache: bool
    ) -> str | None:
        if use_cache and not section.cache_break and section.name in self._cache:
            return self._cache[section.name]
        try:
            value = section.compute()
        except Exception:
            logger.exception("Failed to compute section %s", section.name)
            value = None
        if use_cache and not section.cache_break:
            self._cache[section.name] = value
        return value


def build_tool_prompt_section(tool_prompts: dict[str, str]) -> str:
    """Combine tool-contributed prompt sections into one block.

    Each tool can contribute a short instruction block to the system prompt.
    This function merges them into a single section with per-tool headers.

    Parameters
    ----------
    tool_prompts
        Mapping of tool name to its prompt contribution.

    Returns
    -------
    str
        A combined prompt section, or empty string if no tools contribute.
    """
    if not tool_prompts:
        return ""
    lines: list[str] = ["# Tool Instructions"]
    for name, prompt in sorted(tool_prompts.items()):
        if prompt:
            lines.append(f"## {name}")
            lines.append(prompt)
    return "\n\n".join(lines) if len(lines) > 1 else ""
