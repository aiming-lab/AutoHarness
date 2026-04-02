"""Speculative bash command classifier.

Runs permission classification in parallel with hook execution
to reduce user wait time for bash commands.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

class SpeculativeClassifier:
    """Runs bash command classification speculatively in parallel."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Task[str]] = {}

    async def start_check(
        self,
        command: str,
        classifier: Callable[[str], str],
        tool_id: str,
    ) -> None:
        """Start a speculative classification check in the background."""
        async def _classify() -> str:
            try:
                return classifier(command)
            except Exception:
                logger.debug("Speculative classifier failed for %s", tool_id)
                return "ask"  # Default to ask on failure

        task = asyncio.create_task(_classify())
        self._pending[tool_id] = task

    async def get_result(self, tool_id: str, timeout: float = 5.0) -> str | None:
        """Get the classification result if available."""
        task = self._pending.pop(tool_id, None)
        if task is None:
            return None
        try:
            return await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.debug("Speculative classifier timed out for %s", tool_id)
            task.cancel()
            return None

    def cancel_all(self) -> None:
        """Cancel all pending checks."""
        for task in self._pending.values():
            task.cancel()
        self._pending.clear()
