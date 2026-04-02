"""Tool output budget management.

Each tool has a configurable max output size. When exceeded, output is
persisted to disk and a file path reference is returned instead.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULT_SIZE = 50_000  # chars

class OutputBudgetManager:
    """Manages tool output truncation and persistence."""

    def __init__(self, storage_dir: str = ".autoharness/tool_outputs") -> None:
        self.storage_dir = Path(storage_dir)

    def apply_budget(
        self,
        tool_name: str,
        tool_id: str,
        output: str,
        max_size: int = DEFAULT_MAX_RESULT_SIZE,
    ) -> str:
        """Apply output budget to tool result.

        If output exceeds max_size, persist to disk and return truncated
        version with file path reference.
        """
        if len(output) <= max_size:
            return output

        # Persist full output to disk
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.storage_dir / f"{tool_id}.txt"
        output_path.write_text(output, encoding="utf-8")

        truncated = output[:max_size]
        footer = (
            f"\n\n... [Output truncated: {len(output)} chars total. "
            f"Full output saved to: {output_path}]"
        )

        logger.info(
            "Output budget: %s output truncated from %d to %d chars",
            tool_name, len(output), max_size,
        )

        return truncated + footer
