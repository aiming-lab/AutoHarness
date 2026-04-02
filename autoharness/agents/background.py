"""Background agent management — async launch, tracking, and notification.

Agents can run in background with notification on completion.
Supports auto-backgrounding after configurable timeout.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

AUTO_BACKGROUND_MS = 120_000
PROGRESS_THRESHOLD_MS = 2_000
BG_OUTPUT_TRUNCATION = 500
BG_FULL_OUTPUT_LIMIT = 50_000

@dataclass
class AgentTask:
    """A tracked background agent task."""
    agent_id: str
    description: str
    status: Literal["running", "completed", "failed", "timeout"] = "running"
    output: str = ""
    output_file: str = ""
    error: str | None = None

class BackgroundAgentManager:
    """Manages background agent lifecycle and notifications."""

    def __init__(self, output_dir: str = ".autoharness/agent_outputs") -> None:
        self._tasks: dict[str, AgentTask] = {}
        self._notifications: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.output_dir = Path(output_dir)

    def register(self, description: str) -> AgentTask:
        """Register a new background agent task."""
        agent_id = str(uuid.uuid4())[:8]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = str(self.output_dir / f"{agent_id}.output")

        task = AgentTask(
            agent_id=agent_id,
            description=description,
            output_file=output_file,
        )

        with self._lock:
            self._tasks[agent_id] = task

        return task

    def complete(self, agent_id: str, output: str) -> None:
        """Mark a task as completed with output."""
        with self._lock:
            task = self._tasks.get(agent_id)
            if task:
                task.status = "completed"
                task.output = output[:BG_FULL_OUTPUT_LIMIT]
                # Write to output file
                Path(task.output_file).write_text(output, encoding="utf-8")
                # Queue notification
                summary = output[:BG_OUTPUT_TRUNCATION]
                self._notifications.append({
                    "agent_id": agent_id,
                    "description": task.description,
                    "status": "completed",
                    "summary": summary,
                })

    def fail(self, agent_id: str, error: str) -> None:
        """Mark a task as failed."""
        with self._lock:
            task = self._tasks.get(agent_id)
            if task:
                task.status = "failed"
                task.error = error
                self._notifications.append({
                    "agent_id": agent_id,
                    "description": task.description,
                    "status": "failed",
                    "error": error,
                })

    def drain_notifications(self) -> list[dict[str, Any]]:
        """Drain and return all pending notifications."""
        with self._lock:
            notifications = list(self._notifications)
            self._notifications.clear()
        return notifications

    def get_task(self, agent_id: str) -> AgentTask | None:
        """Get a task by ID."""
        return self._tasks.get(agent_id)

    def get_output(self, agent_id: str) -> str | None:
        """Get the output of a completed task."""
        task = self._tasks.get(agent_id)
        if task and task.status == "completed":
            # Try to read from file for full output
            try:
                return Path(task.output_file).read_text(encoding="utf-8")
            except OSError:
                return task.output
        return None

    def list_running(self) -> list[AgentTask]:
        """List all currently running tasks."""
        return [t for t in self._tasks.values() if t.status == "running"]

    def list_all(self) -> list[AgentTask]:
        """List all tasks."""
        return list(self._tasks.values())
