"""Worktree task isolation — git worktree per task for directory-level parallelism.

Each task can be bound to a dedicated git worktree, enabling parallel
work on separate directories without conflicts.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

@dataclass
class WorktreeEntry:
    name: str
    path: str
    branch: str
    task_id: int | None = None
    status: Literal["active", "removed", "kept"] = "active"

@dataclass
class WorktreeEvent:
    event: str  # worktree.create.before/after/failed, worktree.remove.before/after/failed
    ts: float = field(default_factory=time.time)
    worktree: str = ""
    task_id: int | None = None
    error: str | None = None

class WorktreeManager:
    """Manages git worktrees for task isolation."""

    def __init__(self, base_dir: str = ".worktrees") -> None:
        self.base_dir = Path(base_dir)
        self._index: dict[str, WorktreeEntry] = {}
        self._load_index()

    def create(self, name: str, task_id: int | None = None) -> WorktreeEntry:
        """Create a new git worktree for a task."""
        if name in self._index:
            raise ValueError(f"Worktree already exists: {name}")

        branch = f"wt/{name}"
        path = str(self.base_dir / name)

        self._log_event("worktree.create.before", name, task_id)

        try:
            subprocess.run(
                ["git", "worktree", "add", "-b", branch, path, "HEAD"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            self._log_event("worktree.create.failed", name, task_id, str(exc))
            raise RuntimeError(f"Failed to create worktree: {exc.stderr}") from exc

        entry = WorktreeEntry(name=name, path=path, branch=branch, task_id=task_id)
        self._index[name] = entry
        self._save_index()
        self._log_event("worktree.create.after", name, task_id)

        return entry

    def remove(self, name: str, complete_task: bool = False) -> None:
        """Remove a worktree."""
        entry = self._index.get(name)
        if not entry:
            raise ValueError(f"Unknown worktree: {name}")

        self._log_event("worktree.remove.before", name, entry.task_id)

        try:
            subprocess.run(
                ["git", "worktree", "remove", entry.path, "--force"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            self._log_event("worktree.remove.failed", name, entry.task_id, str(exc))
            raise RuntimeError(f"Failed to remove worktree: {exc.stderr}") from exc

        entry.status = "removed"
        self._save_index()
        self._log_event("worktree.remove.after", name, entry.task_id)

    def keep(self, name: str) -> None:
        """Mark a worktree as kept (preserved, unbound from task)."""
        entry = self._index.get(name)
        if entry:
            entry.status = "kept"
            entry.task_id = None
            self._save_index()

    def get(self, name: str) -> WorktreeEntry | None:
        return self._index.get(name)

    def list_active(self) -> list[WorktreeEntry]:
        return [e for e in self._index.values() if e.status == "active"]

    def _load_index(self) -> None:
        index_file = self.base_dir / "index.json"
        if not index_file.is_file():
            return
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            for item in data:
                entry = WorktreeEntry(**item)
                self._index[entry.name] = entry
        except (json.JSONDecodeError, OSError):
            pass

    def _save_index(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        index_file = self.base_dir / "index.json"
        data = [asdict(e) for e in self._index.values()]
        index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _log_event(
        self,
        event: str,
        worktree: str,
        task_id: int | None = None,
        error: str | None = None,
    ) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        events_file = self.base_dir / "events.jsonl"
        entry = WorktreeEvent(event=event, worktree=worktree, task_id=task_id, error=error)
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), default=str) + "\n")
