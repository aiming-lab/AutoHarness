"""System prompt architecture — section framework, caching, and context management."""

from autoharness.prompt.cache import CacheBreakDetector
from autoharness.prompt.context import ContextManager
from autoharness.prompt.mcp_delta import McpInstructionManager
from autoharness.prompt.sections import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    SystemPromptRegistry,
    SystemPromptSection,
    build_tool_prompt_section,
    system_prompt_section,
    uncached_section,
)

__all__ = [
    "SYSTEM_PROMPT_DYNAMIC_BOUNDARY",
    "CacheBreakDetector",
    "ContextManager",
    "McpInstructionManager",
    "SystemPromptRegistry",
    "SystemPromptSection",
    "build_tool_prompt_section",
    "system_prompt_section",
    "uncached_section",
]
