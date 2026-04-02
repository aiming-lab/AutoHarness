"""Tool execution orchestration with concurrency control.

Read-only concurrent-safe tools execute in parallel.
Non-concurrent tools execute serially with exclusive access.
Results are buffered and emitted in submission order.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

MAX_CONCURRENT_TOOLS = 10

@dataclass
class TrackedTool:
    id: str
    name: str
    input_data: dict[str, Any]
    status: Literal["queued", "executing", "completed", "failed"] = "queued"
    is_concurrency_safe: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None

class ToolOrchestrator:
    """Orchestrates tool execution with concurrency rules."""

    def __init__(self, registry: Any = None, max_concurrent: int = MAX_CONCURRENT_TOOLS) -> None:
        self.registry = registry
        self.max_concurrent = max_concurrent

    async def execute_batch(
        self,
        tool_calls: list[dict[str, Any]],
        executor: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Execute a batch of tool calls respecting concurrency rules.

        Returns results in the same order as input tool_calls.
        """
        if not tool_calls:
            return []

        tracked = []
        for call in tool_calls:
            tool_name = call.get("name", "")
            tool_id = call.get("id", "")
            tool_input = call.get("input", {})

            is_safe = False
            if self.registry:
                tool_def = self.registry.get(tool_name)
                if tool_def:
                    is_safe = tool_def.is_concurrency_safe

            tracked.append(TrackedTool(
                id=tool_id,
                name=tool_name,
                input_data=tool_input,
                is_concurrency_safe=is_safe,
            ))

        # Separate concurrent-safe and non-concurrent tools
        safe_tools = [t for t in tracked if t.is_concurrency_safe]
        unsafe_tools = [t for t in tracked if not t.is_concurrency_safe]

        # Execute concurrent-safe tools in parallel
        if safe_tools:
            sem = asyncio.Semaphore(self.max_concurrent)
            async def run_safe(t: TrackedTool) -> None:
                async with sem:
                    t.status = "executing"
                    try:
                        t.result = await executor(t.name, t.input_data)
                        t.status = "completed"
                    except Exception as e:
                        t.error = str(e)
                        t.status = "failed"

            await asyncio.gather(*(run_safe(t) for t in safe_tools))

        # Execute non-concurrent tools serially
        for t in unsafe_tools:
            t.status = "executing"
            try:
                t.result = await executor(t.name, t.input_data)
                t.status = "completed"
            except Exception as e:
                t.error = str(e)
                t.status = "failed"

        # Return results in original order
        results = []
        for t in tracked:
            if t.result is not None:
                results.append(t.result)
            else:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": t.id,
                    "content": f"Error: {t.error or 'Unknown error'}",
                    "is_error": True,
                })

        return results

    def execute_batch_sync(
        self,
        tool_calls: list[dict[str, Any]],
        executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Synchronous version of execute_batch."""
        if not tool_calls:
            return []

        results = []
        for call in tool_calls:
            tool_name = call.get("name", "")
            tool_id = call.get("id", "")
            tool_input = call.get("input", {})

            try:
                result = executor(tool_name, tool_input)
                results.append(result)
            except Exception as e:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        return results
