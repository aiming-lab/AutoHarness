"""Persistent task system with dependency graph.

Tasks stored as JSON files in .autoharness/tasks/task_{id}.json.
Supports dependencies (blocked_by), owner assignment, and status tracking.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

@dataclass
class Task:
    id: int = 0
    subject: str = ""
    description: str = ""
    status: Literal[
        "pending", "in_progress", "completed", "deleted"
    ] = "pending"
    owner: str | None = None
    blocked_by: list[int] = field(default_factory=list)

class TaskSystem:
    """File-based persistent task system."""

    def __init__(self, base_dir: str | Path = ".autoharness/tasks") -> None:
        self.base_dir = Path(base_dir)
        self._next_id = 1
        self._load_next_id()

    def create(
        self,
        subject: str,
        description: str = "",
        blocked_by: list[int] | None = None,
    ) -> Task:
        task = Task(id=self._next_id, subject=subject, description=description,
                    blocked_by=blocked_by or [])
        self._next_id += 1
        self._save_task(task)
        return task

    def get(self, task_id: int) -> Task | None:
        path = self._task_path(task_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Task(**data)

    def update_status(self, task_id: int, status: str) -> Task | None:
        task = self.get(task_id)
        if task is None:
            return None
        task.status = status  # type: ignore
        if status == "completed":
            self._unblock_dependents(task_id)
        self._save_task(task)
        return task

    def assign(self, task_id: int, owner: str) -> Task | None:
        task = self.get(task_id)
        if task is None:
            return None
        task.owner = owner
        self._save_task(task)
        return task

    def list_all(self) -> list[Task]:
        tasks: list[Task] = []
        if not self.base_dir.is_dir():
            return tasks
        for f in sorted(self.base_dir.glob("task_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                tasks.append(Task(**data))
            except (json.JSONDecodeError, OSError):
                pass
        return tasks

    def list_ready(self) -> list[Task]:
        """Tasks that are pending, unblocked, and unassigned."""
        return [t for t in self.list_all()
                if t.status == "pending" and not t.blocked_by and t.owner is None]

    def _unblock_dependents(self, completed_id: int) -> None:
        for task in self.list_all():
            if completed_id in task.blocked_by:
                task.blocked_by.remove(completed_id)
                self._save_task(task)

    def _save_task(self, task: Task) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._task_path(task.id)
        path.write_text(json.dumps(asdict(task), indent=2), encoding="utf-8")

    def _task_path(self, task_id: int) -> Path:
        return self.base_dir / f"task_{task_id}.json"

    def _load_next_id(self) -> None:
        if not self.base_dir.is_dir():
            return
        max_id = 0
        for f in self.base_dir.glob("task_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                max_id = max(max_id, data.get("id", 0))
            except (json.JSONDecodeError, OSError):
                pass
        self._next_id = max_id + 1
