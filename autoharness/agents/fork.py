"""Fork subagent semantics — cache-sharing via byte-identical prefix.

When forking, child agents inherit the parent's full conversation context
and byte-identical system prompt to maximize prompt cache hits.

Key pattern: All fork children share identical message prefix up to
the per-child directive text, enabling 90%+ cache hit rate.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

FORK_PLACEHOLDER_RESULT = "Fork started — processing in background"
FORK_BOILERPLATE_TAG = "<fork-child>"

def is_in_fork_child(messages: list[dict[str, Any]]) -> bool:
    """Detect if we're already in a fork child (prevent recursive forking)."""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and FORK_BOILERPLATE_TAG in content:
            return True
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text", "")
                    if isinstance(text, str) and FORK_BOILERPLATE_TAG in text:
                        return True
    return False

def build_forked_messages(
    parent_messages: list[dict[str, Any]],
    directive: str,
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    """Build message list for a fork child agent.

    Strategy:
    1. Keep full parent conversation history
    2. For the last assistant message, keep all tool_use blocks
    3. Generate identical placeholder tool_results for each tool_use
    4. Append the child-specific directive as the final text block

    This ensures all fork children share byte-identical prefix,
    maximizing prompt cache hits.
    """
    if not parent_messages:
        return [{
            "role": "user",
            "content": f"{FORK_BOILERPLATE_TAG}\n{directive}",
        }]

    # Deep copy all messages except the last one
    result = [copy.deepcopy(msg) for msg in parent_messages[:-1]]

    last_msg = parent_messages[-1]
    last_role = last_msg.get("role", "")

    if last_role == "assistant":
        # Keep the assistant message as-is
        result.append(copy.deepcopy(last_msg))

        # Build tool_result blocks for each tool_use in the assistant message
        tool_results = []
        content = last_msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.get("id", ""),
                        "content": FORK_PLACEHOLDER_RESULT,
                    })

        # Append user message with placeholder results + directive
        user_content: list[dict[str, Any]] = list(tool_results)
        user_content.append({
            "type": "text",
            "text": f"{FORK_BOILERPLATE_TAG}\n{directive}",
        })
        result.append({"role": "user", "content": user_content})
    else:
        # Last message is user — just append directive
        result.append(copy.deepcopy(last_msg))
        result.append({
            "role": "assistant",
            "content": "I'll work on this task now.",
        })
        result.append({
            "role": "user",
            "content": f"{FORK_BOILERPLATE_TAG}\n{directive}",
        })

    return result
