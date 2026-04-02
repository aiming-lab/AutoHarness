"""Microcompact — tool result clearing for context window management.

Replaces old tool_result content with a placeholder to free up context
space while preserving message structure and tool_use_id integrity.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from autoharness.context.tokens import estimate_tokens

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

COMPACTABLE_TOOLS: frozenset[str] = frozenset({
    "bash",
    "read_file",
    "grep",
    "glob",
    "web_search",
    "web_fetch",
    "edit_file",
    "write_file",
    # Common variants / aliases
    "Bash",
    "Read",
    "Grep",
    "Glob",
    "WebSearch",
    "WebFetch",
    "Edit",
    "Write",
})
"""Tool names whose results may be compacted (cleared)."""

PRESERVE_RESULT_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "Read",
})
"""Tool names whose results should **never** be compacted."""

MIN_CONTENT_SIZE: int = 100
"""Minimum content length (chars) to bother compacting."""

_CLEARED_PLACEHOLDER = (
    "[Previous tool result cleared by AutoHarness context management]"
)


def microcompact(
    messages: list[dict[str, Any]],
    keep_recent: int = 3,
) -> list[dict[str, Any]]:
    """Clear old tool_result content to reduce context window usage.

    Iterates through messages and replaces tool_result content blocks
    that are older than ``keep_recent`` turns from the end. A "turn"
    is defined as a user or assistant message.

    Parameters
    ----------
    messages : list[dict]
        The conversation message list. Not mutated.
    keep_recent : int
        Number of recent turns (user/assistant messages) whose
        tool_results should be preserved. Default is 3.

    Returns
    -------
    list[dict]
        A new message list with old tool_result content replaced.
        The returned list has a ``tokens_saved`` attribute with the
        estimated tokens freed.
    """
    if not messages:
        return []

    # Count turns (user or assistant messages) to find the cutoff
    turn_indices: list[int] = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        if role in ("user", "assistant"):
            turn_indices.append(i)

    # Determine the cutoff index: messages at or after this index are "recent"
    cutoff_index = 0 if len(turn_indices) <= keep_recent else turn_indices[-keep_recent]

    result: list[dict[str, Any]] = []
    tokens_saved = 0

    for i, msg in enumerate(messages):
        if i < cutoff_index:
            msg = _clear_tool_results(msg)
            saved = msg.pop("_tokens_saved", 0)
            tokens_saved += saved
            result.append(msg)
        else:
            result.append(copy.deepcopy(msg))

    # Attach metadata to the result list
    # Using a wrapper class to carry the extra attribute
    logger.info("Microcompact: cleared old tool results, ~%d tokens saved", tokens_saved)
    # Store tokens_saved as an attribute on the list
    result = _CompactedMessages(result)
    result.tokens_saved = tokens_saved
    return result


class _CompactedMessages(list[dict[str, Any]]):
    """List subclass that carries a ``tokens_saved`` attribute."""

    tokens_saved: int = 0


def _clear_tool_results(msg: dict[str, Any]) -> dict[str, Any]:
    """Replace tool_result content in a message with placeholder.

    Only compacts results from tools listed in :data:`COMPACTABLE_TOOLS`
    (unless the tool is in :data:`PRESERVE_RESULT_TOOLS`).  Content
    shorter than :data:`MIN_CONTENT_SIZE` characters is left intact.

    Returns a deep-copied message with ``_tokens_saved`` key indicating
    how many tokens were freed.
    """
    msg = copy.deepcopy(msg)
    tokens_saved = 0

    content = msg.get("content")

    # Handle Anthropic-style structured content blocks
    if isinstance(content, list):
        new_content = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_name = block.get("tool_name", block.get("name", ""))
                # Skip if tool is not compactable or is explicitly preserved
                if tool_name and (
                    tool_name not in COMPACTABLE_TOOLS
                    or tool_name in PRESERVE_RESULT_TOOLS
                ):
                    new_content.append(block)
                    continue

                old_content = block.get("content", "")
                if isinstance(old_content, str) and old_content != _CLEARED_PLACEHOLDER:
                    if len(old_content) < MIN_CONTENT_SIZE:
                        new_content.append(block)
                        continue
                    tokens_saved += (
                        estimate_tokens(old_content)
                        - estimate_tokens(_CLEARED_PLACEHOLDER)
                    )
                    block = {**block, "content": _CLEARED_PLACEHOLDER}
                elif isinstance(old_content, list):
                    total_len = sum(
                        len(sub.get("text", ""))
                        for sub in old_content
                        if isinstance(sub, dict)
                    )
                    if total_len < MIN_CONTENT_SIZE:
                        new_content.append(block)
                        continue
                    # Content can be a list of content blocks
                    for sub in old_content:
                        if isinstance(sub, dict):
                            tokens_saved += estimate_tokens(sub.get("text", ""))
                    block = {**block, "content": _CLEARED_PLACEHOLDER}
                new_content.append(block)
            else:
                new_content.append(block)
        msg["content"] = new_content

    # Handle simple string content for tool role messages
    elif isinstance(content, str) and msg.get("role") == "tool":
        if content != _CLEARED_PLACEHOLDER and len(content) >= MIN_CONTENT_SIZE:
            tokens_saved += estimate_tokens(content) - estimate_tokens(_CLEARED_PLACEHOLDER)
            msg["content"] = _CLEARED_PLACEHOLDER

    msg["_tokens_saved"] = max(0, tokens_saved)
    return msg
