"""Post-compact file and skill restoration.

After an auto-compact summarizes the conversation, recently-accessed
files and active skills may be lost from context.  This module
re-injects truncated file contents and skill definitions into the
compacted message list so the agent can continue seamlessly.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from autoharness.context.tokens import estimate_tokens

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Budget constants
# ---------------------------------------------------------------------------

POST_COMPACT_MAX_FILES_TO_RESTORE: int = 5
"""Maximum number of recently-accessed files to re-inject."""

POST_COMPACT_TOKEN_BUDGET: int = 50_000
"""Total token budget for all restored file content."""

POST_COMPACT_MAX_TOKENS_PER_FILE: int = 5_000
"""Max tokens to include per restored file."""

POST_COMPACT_MAX_TOKENS_PER_SKILL: int = 5_000
"""Max tokens to include per restored skill definition."""

POST_COMPACT_SKILLS_TOKEN_BUDGET: int = 25_000
"""Total token budget for all restored skill definitions."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def restore_files_after_compact(
    compacted_messages: list[dict[str, Any]],
    recent_files: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Re-inject recently-accessed files and skills after compaction.

    Inserts a system-style message (role ``"user"``) containing
    truncated file contents and skill definitions, placed right after
    the compaction summary but before the user's latest request.

    Parameters
    ----------
    compacted_messages : list[dict]
        Message list returned from :meth:`AutoCompactor.compact`.
    recent_files : list[dict] or None
        List of dicts with keys ``path`` (str) and ``content`` (str).
        Only the first :data:`POST_COMPACT_MAX_FILES_TO_RESTORE` entries
        are used.
    skills : list[dict] or None
        List of dicts with keys ``name`` (str) and ``definition`` (str).

    Returns
    -------
    list[dict]
        A new message list with restoration content injected.
    """
    if not recent_files and not skills:
        return compacted_messages

    parts: list[str] = []

    # --- File restoration ---
    if recent_files:
        file_tokens_used = 0
        files_restored = 0
        parts.append("[AutoHarness Post-Compact File Restoration]")

        for entry in recent_files[:POST_COMPACT_MAX_FILES_TO_RESTORE]:
            if file_tokens_used >= POST_COMPACT_TOKEN_BUDGET:
                break

            path = entry.get("path", "<unknown>")
            content = entry.get("content", "")

            tokens = estimate_tokens(content)
            if tokens > POST_COMPACT_MAX_TOKENS_PER_FILE:
                # Truncate to budget — rough char estimate
                max_chars = POST_COMPACT_MAX_TOKENS_PER_FILE * 4
                content = content[:max_chars] + "\n... [truncated]"
                tokens = POST_COMPACT_MAX_TOKENS_PER_FILE

            if file_tokens_used + tokens > POST_COMPACT_TOKEN_BUDGET:
                break

            parts.append(f"\n--- {path} ---\n{content}")
            file_tokens_used += tokens
            files_restored += 1

        logger.info(
            "Post-compact: restored %d files (~%d tokens)",
            files_restored,
            file_tokens_used,
        )

    # --- Skill restoration ---
    if skills:
        skill_tokens_used = 0
        skills_restored = 0
        parts.append("\n[AutoHarness Post-Compact Skill Restoration]")

        for skill in skills:
            if skill_tokens_used >= POST_COMPACT_SKILLS_TOKEN_BUDGET:
                break

            name = skill.get("name", "<unknown>")
            definition = skill.get("definition", "")

            tokens = estimate_tokens(definition)
            if tokens > POST_COMPACT_MAX_TOKENS_PER_SKILL:
                max_chars = POST_COMPACT_MAX_TOKENS_PER_SKILL * 4
                definition = definition[:max_chars] + "\n... [truncated]"
                tokens = POST_COMPACT_MAX_TOKENS_PER_SKILL

            if skill_tokens_used + tokens > POST_COMPACT_SKILLS_TOKEN_BUDGET:
                break

            parts.append(f"\n--- Skill: {name} ---\n{definition}")
            skill_tokens_used += tokens
            skills_restored += 1

        logger.info(
            "Post-compact: restored %d skills (~%d tokens)",
            skills_restored,
            skill_tokens_used,
        )

    if not parts:
        return compacted_messages

    restoration_msg: dict[str, Any] = {
        "role": "user",
        "content": "\n".join(parts),
    }

    # Insert before the last user message (if present) so that the
    # conversation flow is: summary → ack → restoration → user request
    result = [copy.deepcopy(m) for m in compacted_messages]

    # Find insertion point: before the last user message
    insert_idx = len(result)
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            # Check if this is the compaction summary (skip it)
            content = result[i].get("content", "")
            if isinstance(content, str) and "[AutoHarness Auto-Compact Summary]" in content:
                continue
            insert_idx = i
            break

    result.insert(insert_idx, restoration_msg)
    return result
