"""Progress file system — structured checkpoints for long-running tasks.

Captures task state at natural boundaries (phase completion, context
compaction, session pause) so agents can resume without losing track
of what was done, what failed, and what remains.

Usage::

    tracker = ProgressTracker(session_dir=".autoharness/sessions/")
    tracker.record_completed("Refactored auth module")
    tracker.record_failed("Tests for auth.py", reason="Import error")
    tracker.record_remaining(["Update docs", "Run integration tests"])
    tracker.save()

    # Later, resume:
    briefing = tracker.generate_briefing()
    # -> structured summary of completed/failed/remaining items
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

PROGRESS_FILE_SUFFIX = "-progress.md"


@dataclass
class ProgressEntry:
    """A single tracked item in the progress file."""

    description: str
    status: Literal["completed", "failed", "remaining", "in_progress"]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reason: str | None = None
    files_modified: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProgressTracker:
    """Manages a structured progress file for a single session.

    The progress file uses markdown with YAML frontmatter, making it
    both human-readable and machine-parseable.
    """

    def __init__(
        self,
        session_dir: str | Path,
        session_id: str | None = None,
    ) -> None:
        self._session_dir = Path(session_dir)
        self._session_id = session_id or str(uuid.uuid4())[:8]
        self._created_at = datetime.now(timezone.utc).isoformat()
        self._updated_at = self._created_at
        self._entries: list[ProgressEntry] = []

    # -- Properties ----------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def entries(self) -> list[ProgressEntry]:
        return list(self._entries)

    @property
    def completed(self) -> list[ProgressEntry]:
        return [e for e in self._entries if e.status == "completed"]

    @property
    def failed(self) -> list[ProgressEntry]:
        return [e for e in self._entries if e.status == "failed"]

    @property
    def remaining(self) -> list[ProgressEntry]:
        return [e for e in self._entries if e.status == "remaining"]

    @property
    def in_progress(self) -> list[ProgressEntry]:
        return [e for e in self._entries if e.status == "in_progress"]

    # -- Recording -----------------------------------------------------------

    def record_completed(
        self,
        description: str,
        files_modified: list[str] | None = None,
        **metadata: Any,
    ) -> ProgressEntry:
        """Record a completed task item."""
        entry = ProgressEntry(
            description=description,
            status="completed",
            files_modified=files_modified or [],
            metadata=metadata,
        )
        self._entries.append(entry)
        self._touch()
        return entry

    def record_failed(
        self,
        description: str,
        reason: str | None = None,
        files_modified: list[str] | None = None,
        **metadata: Any,
    ) -> ProgressEntry:
        """Record a failed task item with an optional reason."""
        entry = ProgressEntry(
            description=description,
            status="failed",
            reason=reason,
            files_modified=files_modified or [],
            metadata=metadata,
        )
        self._entries.append(entry)
        self._touch()
        return entry

    def record_remaining(self, descriptions: list[str]) -> list[ProgressEntry]:
        """Record one or more items that still need to be done."""
        entries = []
        for desc in descriptions:
            entry = ProgressEntry(description=desc, status="remaining")
            self._entries.append(entry)
            entries.append(entry)
        self._touch()
        return entries

    def record_in_progress(
        self,
        description: str,
        files_modified: list[str] | None = None,
        **metadata: Any,
    ) -> ProgressEntry:
        """Record an item currently being worked on."""
        entry = ProgressEntry(
            description=description,
            status="in_progress",
            files_modified=files_modified or [],
            metadata=metadata,
        )
        self._entries.append(entry)
        self._touch()
        return entry

    # -- Persistence ---------------------------------------------------------

    def save(self) -> Path:
        """Write progress file as markdown with YAML frontmatter."""
        self._session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_dir / f"{self._session_id}{PROGRESS_FILE_SUFFIX}"

        frontmatter = {
            "session_id": self._session_id,
            "created_at": self._created_at,
            "updated_at": self._updated_at,
            "total_entries": len(self._entries),
            "completed": len(self.completed),
            "failed": len(self.failed),
            "remaining": len(self.remaining),
            "in_progress": len(self.in_progress),
        }

        lines = ["---"]
        lines.append(yaml.dump(frontmatter, default_flow_style=False).strip())
        lines.append("---\n")

        if self.completed:
            lines.append("## Completed")
            for e in self.completed:
                suffix = self._format_files(e.files_modified)
                lines.append(f"- [x] {e.description}{suffix}")
            lines.append("")

        if self.in_progress:
            lines.append("## In Progress")
            for e in self.in_progress:
                suffix = self._format_files(e.files_modified)
                lines.append(f"- [ ] {e.description}{suffix}")
            lines.append("")

        if self.failed:
            lines.append("## Failed")
            for e in self.failed:
                reason_part = f" — {e.reason}" if e.reason else ""
                suffix = self._format_files(e.files_modified)
                lines.append(f"- [ ] {e.description}{reason_part}{suffix}")
            lines.append("")

        if self.remaining:
            lines.append("## Remaining")
            for e in self.remaining:
                lines.append(f"- [ ] {e.description}")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> ProgressTracker:
        """Load a progress tracker from a saved markdown file."""
        path = Path(path)
        content = path.read_text(encoding="utf-8")

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if not fm_match:
            raise ValueError(f"Invalid progress file: {path}")

        data = yaml.safe_load(fm_match.group(1)) or {}
        body = fm_match.group(2)

        tracker = cls(
            session_dir=path.parent,
            session_id=data.get("session_id", ""),
        )
        tracker._created_at = data.get("created_at", tracker._created_at)
        tracker._updated_at = data.get("updated_at", tracker._updated_at)

        # Parse body sections
        current_status: str | None = None
        section_map = {
            "## Completed": "completed",
            "## In Progress": "in_progress",
            "## Failed": "failed",
            "## Remaining": "remaining",
        }

        for line in body.split("\n"):
            stripped = line.strip()

            # Check for section header
            matched_section = False
            for header, status in section_map.items():
                if stripped.startswith(header):
                    current_status = status
                    matched_section = True
                    break
            if matched_section:
                continue

            # Parse list items
            if not stripped.startswith("- [") or current_status is None:
                continue

            # Strip checkbox prefix
            item_text = re.sub(r"^- \[[ x]\] ", "", stripped)

            # Extract files in parentheses at end
            files: list[str] = []
            files_match = re.search(r"\(([^)]+)\)$", item_text)
            if files_match:
                files = [f.strip() for f in files_match.group(1).split(",")]
                item_text = item_text[: files_match.start()].strip()

            # Extract failure reason after em-dash
            reason = None
            if current_status == "failed" and " — " in item_text:
                item_text, reason = item_text.split(" — ", 1)
                item_text = item_text.strip()
                reason = reason.strip()

            entry = ProgressEntry(
                description=item_text,
                status=current_status,  # type: ignore[arg-type]
                reason=reason,
                files_modified=files,
            )
            tracker._entries.append(entry)

        return tracker

    # -- Briefing ------------------------------------------------------------

    def generate_briefing(self) -> str:
        """Generate a structured summary for injection into agent context."""
        parts = [f"[Session Progress — {self._session_id}]"]

        if self.completed:
            descs = ", ".join(e.description for e in self.completed)
            parts.append(f"Completed ({len(self.completed)}): {descs}")

        if self.in_progress:
            descs = ", ".join(e.description for e in self.in_progress)
            parts.append(f"In Progress ({len(self.in_progress)}): {descs}")

        if self.failed:
            items = []
            for e in self.failed:
                reason_part = f" ({e.reason})" if e.reason else ""
                items.append(f"{e.description}{reason_part}")
            parts.append(f"Failed ({len(self.failed)}): {', '.join(items)}")

        if self.remaining:
            descs = ", ".join(e.description for e in self.remaining)
            parts.append(f"Remaining ({len(self.remaining)}): {descs}")

        parts.append(f"Last updated: {self._updated_at}")
        return "\n".join(parts)

    # -- Internal ------------------------------------------------------------

    def _touch(self) -> None:
        """Update the modified timestamp."""
        self._updated_at = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _format_files(files: list[str]) -> str:
        """Format file list as a parenthetical suffix."""
        if not files:
            return ""
        return f" ({', '.join(files)})"
