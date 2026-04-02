"""Auto-compact and reactive compact for context window management.

Provides LLM-based summarization compaction (AutoCompactor) and
emergency recovery from prompt-too-long errors (reactive_compact).
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from typing import Any

from autoharness.context.tokens import TokenBudget, estimate_message_tokens
from autoharness.core.types import CompactionMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CONSECUTIVE_FAILURES = 3

AUTOCOMPACT_BUFFER_TOKENS: int = 13_000
"""Safety buffer subtracted from the context window when computing the
auto-compact threshold."""

WARNING_THRESHOLD_BUFFER_TOKENS: int = 20_000
"""Additional buffer for the "nearing limit" warning threshold."""

MAX_OUTPUT_TOKENS_FOR_SUMMARY: int = 20_000
"""Max output tokens reserved for the compaction summarization call."""

MAX_COMPACT_STREAMING_RETRIES: int = 2
"""Number of retries when streaming a compaction summary fails."""

_COMPACT_PROMPT_TEMPLATE = """\
You are a conversation summarizer for an AI coding assistant.
Summarize the following conversation history into a concise summary that
preserves all essential context: key decisions, file paths, code changes,
errors encountered, and the current task state.

Do NOT include greetings, pleasantries, or redundant back-and-forth.
Focus on actionable information the assistant needs to continue working.

Conversation to summarize:
---
{conversation}
---

Provide a structured summary with sections:
- **Current Task**: What is being worked on
- **Key Decisions**: Important choices made
- **Files Modified**: Paths and what changed
- **Current State**: Where things stand now
"""


# ---------------------------------------------------------------------------
# AutoCompactor
# ---------------------------------------------------------------------------


class AutoCompactor:
    """LLM-based conversation compaction with circuit breaker.

    Parameters
    ----------
    token_budget : TokenBudget
        The token budget tracker to consult for compaction decisions.
    max_consecutive_failures : int
        Number of consecutive failures before the circuit breaker trips
        and compaction attempts stop. Default is 3.
    model : str or None
        Optional model identifier. When provided, the compaction
        threshold is derived from the model's context window via
        :func:`~autoharness.context.models.get_context_window`.
    mode : CompactionMode or str
        The compaction operating mode. Controls which compaction layers
        are active. Default is ``CompactionMode.enhanced``.

        - ``core``: Simple truncation only; LLM-based compaction is
          disabled (``should_compact`` always returns False).
        - ``standard``: Token-budget check only (no circuit breaker).
        - ``enhanced``: Full circuit breaker + token budget (default).
    """

    def __init__(
        self,
        token_budget: TokenBudget,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
        model: str | None = None,
        mode: CompactionMode | str = CompactionMode.enhanced,
    ) -> None:
        self.token_budget = token_budget
        self.max_consecutive_failures = max_consecutive_failures
        self.model = model
        self._mode = CompactionMode(mode) if isinstance(mode, str) else mode
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False

    @property
    def compact_threshold(self) -> int:
        """Token count at which auto-compact should trigger.

        When *model* is set the threshold equals::

            get_context_window(model) - MAX_OUTPUT_TOKENS_FOR_SUMMARY
                                      - AUTOCOMPACT_BUFFER_TOKENS

        Otherwise falls back to the ``token_budget.effective_window``.
        """
        if self.model is not None:
            from autoharness.context.models import get_context_window

            return (
                get_context_window(self.model)
                - MAX_OUTPUT_TOKENS_FOR_SUMMARY
                - AUTOCOMPACT_BUFFER_TOKENS
            )
        return self.token_budget.effective_window

    @property
    def warning_threshold(self) -> int:
        """Token count at which a nearing-limit warning is emitted."""
        return self.compact_threshold - WARNING_THRESHOLD_BUFFER_TOKENS

    @property
    def circuit_open(self) -> bool:
        """True if the circuit breaker has tripped (too many failures)."""
        return self._circuit_open

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Check if auto-compact should trigger.

        Behaviour varies by mode:

        - **core**: Always returns ``False`` (core uses simple truncation,
          not LLM-based compaction).
        - **standard**: Returns ``True`` when the token budget says we
          should compact (no circuit breaker logic).
        - **enhanced**: Returns ``True`` when the token budget says we
          should compact AND the circuit breaker is not open.

        Parameters
        ----------
        messages : list[dict]
            Current conversation messages (used for estimation).

        Returns
        -------
        bool
            Whether compaction should be attempted.
        """
        if self._mode is CompactionMode.core:
            return False

        if self._mode is CompactionMode.standard:
            return self.token_budget.should_compact

        # enhanced mode: full circuit breaker + token budget
        if self._circuit_open:
            logger.debug("AutoCompactor: circuit breaker open, skipping compaction")
            return False
        return self.token_budget.should_compact

    def generate_compact_prompt(self, messages: list[dict[str, Any]]) -> str:
        """Generate the summarization prompt from conversation messages.

        Parameters
        ----------
        messages : list[dict]
            The conversation messages to summarize.

        Returns
        -------
        str
            A prompt string to send to an LLM for summarization.
        """
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Extract text from structured content blocks
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text", "")
                        if text:
                            parts.append(text)
                    elif isinstance(block, str):
                        parts.append(block)
                content = "\n".join(parts)
            lines.append(f"[{role}]: {content}")

        conversation = "\n\n".join(lines)
        return _COMPACT_PROMPT_TEMPLATE.format(conversation=conversation)

    def compact(
        self,
        messages: list[dict[str, Any]],
        summarizer: Callable[[str], str],
    ) -> tuple[list[dict[str, Any]], str]:
        """Compact messages using an LLM summarizer.

        Parameters
        ----------
        messages : list[dict]
            The conversation messages to compact.
        summarizer : Callable[[str], str]
            A callback that takes a prompt string and returns an LLM
            summary. The caller provides this (e.g., wrapping their
            LLM client).

        Returns
        -------
        tuple[list[dict], str]
            A tuple of (compacted_messages, summary_text). The compacted
            messages list starts with a system-like summary message
            followed by the most recent messages.

        Raises
        ------
        RuntimeError
            If the mode is ``core`` (compaction not available) or the
            circuit breaker is open.
        """
        if self._mode is CompactionMode.core:
            raise RuntimeError(
                "LLM-based compaction is not available in core mode. "
                "Core mode uses simple truncation only."
            )

        if self._circuit_open:
            raise RuntimeError(
                "AutoCompactor circuit breaker is open after "
                f"{self.max_consecutive_failures} consecutive failures. "
                "Compaction is disabled."
            )

        prompt = self.generate_compact_prompt(messages)

        try:
            summary = summarizer(prompt)
        except Exception as exc:
            self._consecutive_failures += 1
            logger.warning(
                "AutoCompactor: summarization failed (%d/%d): %s",
                self._consecutive_failures,
                self.max_consecutive_failures,
                exc,
            )
            if self._consecutive_failures >= self.max_consecutive_failures:
                self._circuit_open = True
                logger.error(
                    "AutoCompactor: circuit breaker OPEN after %d consecutive failures",
                    self._consecutive_failures,
                )
            raise

        # Success — reset failure counter
        self._consecutive_failures = 0

        # Build compacted message list: summary + last few messages
        compacted: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"[AutoHarness Auto-Compact Summary]\n\n{summary}\n\n"
                    "The above is a summary of our previous conversation. "
                    "Continue from where we left off."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Understood. I have the context from our previous conversation. "
                    "Let me continue from where we left off."
                ),
            },
        ]

        # Append the last message if it's from the user (the current request)
        recent_messages_preserved = False
        if messages and messages[-1].get("role") == "user":
            compacted.append(copy.deepcopy(messages[-1]))
            recent_messages_preserved = True

        # Build continuation metadata
        _continuation: dict[str, Any] = {
            "suppress_follow_up_questions": True,
            "recent_messages_preserved": recent_messages_preserved,
        }

        logger.info(
            "AutoCompactor: compacted %d messages into summary (%d tokens -> ~%d tokens)",
            len(messages),
            estimate_message_tokens(messages),
            estimate_message_tokens(compacted),
        )

        return compacted, summary

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker."""
        self._consecutive_failures = 0
        self._circuit_open = False
        logger.info("AutoCompactor: circuit breaker reset")


# ---------------------------------------------------------------------------
# Reactive Compact (F.1)
# ---------------------------------------------------------------------------


def reactive_compact(
    messages: list[dict[str, Any]],
    error_message: str,
) -> list[dict[str, Any]]:
    """Emergency compaction when a prompt-too-long error is received.

    Parses the error message to determine how many tokens need to be
    removed, then removes message groups from the beginning of the
    conversation until the prompt fits. Preserves tool_use/tool_result
    pair integrity.

    Parameters
    ----------
    messages : list[dict]
        The conversation messages that caused the error.
    error_message : str
        The error message from the API (e.g., "prompt is too long:
        150000 tokens > 128000 token limit").

    Returns
    -------
    list[dict]
        A trimmed message list that should fit within the token limit.
    """
    if not messages:
        return []

    # Parse token counts from error message
    actual, limit = _parse_token_counts(error_message)

    if actual is None or limit is None:
        # Can't parse — fall back to removing 30% of messages
        logger.warning(
            "reactive_compact: could not parse token counts from error, "
            "removing ~30%% of messages"
        )
        remove_count = max(1, len(messages) // 3)
    else:
        # Estimate how much we need to remove
        excess_ratio = (actual - limit) / actual if actual > 0 else 0.3
        # Add 10% safety margin
        remove_ratio = min(0.8, excess_ratio + 0.10)
        remove_count = max(1, int(len(messages) * remove_ratio))

    # Build a set of tool_use IDs that exist in messages we're keeping
    # so we can preserve pair integrity
    result = _remove_messages_preserving_pairs(messages, remove_count)

    logger.info(
        "reactive_compact: removed %d messages (kept %d) to fit token limit",
        len(messages) - len(result),
        len(result),
    )

    return result


def _parse_token_counts(error_message: str) -> tuple[int | None, int | None]:
    """Extract actual and limit token counts from an error message.

    Handles patterns like:
    - "150000 tokens > 128000 token limit"
    - "prompt is too long: 150000 > 128000"
    - "max_tokens: 150000 exceeds limit 128000"

    Returns
    -------
    tuple[int | None, int | None]
        (actual_tokens, limit_tokens) or (None, None) if parsing fails.
    """
    # Pattern: NUMBER tokens > NUMBER
    match = re.search(r"(\d[\d,]*)\s*tokens?\s*>\s*(\d[\d,]*)", error_message)
    if match:
        actual = int(match.group(1).replace(",", ""))
        limit = int(match.group(2).replace(",", ""))
        return actual, limit

    # Pattern: NUMBER > NUMBER
    match = re.search(r"(\d[\d,]*)\s*>\s*(\d[\d,]*)", error_message)
    if match:
        actual = int(match.group(1).replace(",", ""))
        limit = int(match.group(2).replace(",", ""))
        return actual, limit

    # Pattern: exceeds limit NUMBER
    match = re.search(r"(\d[\d,]*)\s*exceeds?\s*limit\s*(\d[\d,]*)", error_message)
    if match:
        actual = int(match.group(1).replace(",", ""))
        limit = int(match.group(2).replace(",", ""))
        return actual, limit

    return None, None


def _remove_messages_preserving_pairs(
    messages: list[dict[str, Any]],
    remove_count: int,
) -> list[dict[str, Any]]:
    """Remove messages from the front while preserving tool_use/tool_result pairs.

    If removing a message would orphan its paired tool_use or tool_result,
    the pair partner is also removed.

    Parameters
    ----------
    messages : list[dict]
        Original message list.
    remove_count : int
        Target number of messages to remove.

    Returns
    -------
    list[dict]
        Messages with the first ``remove_count`` (approximately) removed,
        adjusted for pair integrity.
    """
    if remove_count >= len(messages):
        # Keep at least the last message
        return [copy.deepcopy(messages[-1])] if messages else []

    # Collect tool_use IDs from messages we plan to keep vs remove
    keep_start = remove_count

    # Find all tool_use_ids in the removed section
    removed_tool_ids: set[str] = set()
    kept_tool_ids: set[str] = set()

    for i, msg in enumerate(messages):
        ids = _extract_tool_ids(msg)
        if i < keep_start:
            removed_tool_ids.update(ids)
        else:
            kept_tool_ids.update(ids)

    # If a tool_id appears in both removed and kept sections,
    # we need to also remove it from the kept section to maintain integrity.
    # Actually the opposite: if we remove a tool_use, we must also remove
    # its tool_result (and vice versa). So expand the removal set.
    orphaned_ids = removed_tool_ids & kept_tool_ids

    result: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if i < keep_start:
            continue  # Skip removed messages

        # Check if this message contains an orphaned tool ID
        msg_ids = _extract_tool_ids(msg)
        if msg_ids and msg_ids.issubset(orphaned_ids):
            # This message only has orphaned IDs — remove it too
            continue

        result.append(copy.deepcopy(msg))

    # Safety: always keep at least one message
    if not result and messages:
        result = [copy.deepcopy(messages[-1])]

    return result


def _extract_tool_ids(msg: dict[str, Any]) -> set[str]:
    """Extract tool_use_id values from a message."""
    ids: set[str] = set()

    # Check for tool_use_id at top level (tool role messages)
    if "tool_use_id" in msg:
        ids.add(msg["tool_use_id"])

    # Check structured content blocks
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if "tool_use_id" in block:
                    ids.add(block["tool_use_id"])
                # tool_use blocks have "id" field
                if block.get("type") == "tool_use" and "id" in block:
                    ids.add(block["id"])

    return ids


# ---------------------------------------------------------------------------
# Image stripping (A.5)
# ---------------------------------------------------------------------------

_IMAGE_TYPES = frozenset({"image", "document"})


def strip_images_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace image/document blocks with text markers before compaction.

    Creates a deep copy of *messages* where every content block whose
    ``type`` is ``"image"`` or ``"document"`` is replaced with a text
    block noting ``[Image removed for compaction]``.

    Parameters
    ----------
    messages : list[dict]
        The conversation message list. Not mutated.

    Returns
    -------
    list[dict]
        A new message list with image/document blocks replaced.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        msg = copy.deepcopy(msg)
        content = msg.get("content")
        if isinstance(content, list):
            new_content: list[Any] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") in _IMAGE_TYPES:
                    new_content.append({
                        "type": "text",
                        "text": (
                            f"[{block.get('type', 'image').capitalize()}"
                            " removed for compaction]"
                        ),
                    })
                else:
                    new_content.append(block)
            msg["content"] = new_content
        result.append(msg)
    return result
