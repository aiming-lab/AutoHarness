"""Session persistence — Markdown + YAML frontmatter format.

Each session saved as a structured markdown file with YAML frontmatter
containing metadata (date, project, branch, status, session_id).
Storage: ~/.autoharness/sessions/*-session.md
7-day cleanup window for old sessions.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SESSION_DIR_NAME = "sessions"
SESSION_CLEANUP_DAYS = 7

@dataclass
class SessionState:
    """Structured session state."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project: str = ""
    branch: str = ""
    status: str = "in-progress"
    working: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    not_started: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_step: str = ""

def save_session(state: SessionState, base_dir: str | Path | None = None) -> Path:
    """Save session state to a markdown file with YAML frontmatter."""
    if base_dir is None:
        base_dir = Path.home() / ".autoharness" / SESSION_DIR_NAME
    else:
        base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{state.session_id}-session.md"
    path = base_dir / filename

    frontmatter = {
        "date": state.date,
        "project": state.project,
        "branch": state.branch,
        "status": state.status,
        "session_id": state.session_id,
    }

    lines = ["---"]
    lines.append(yaml.dump(frontmatter, default_flow_style=False).strip())
    lines.append("---\n")

    if state.working:
        lines.append("## Working")
        for item in state.working:
            lines.append(f"- {item}")
        lines.append("")

    if state.in_progress:
        lines.append("## In Progress")
        for item in state.in_progress:
            lines.append(f"- {item}")
        lines.append("")

    if state.not_started:
        lines.append("## Not Started")
        for item in state.not_started:
            lines.append(f"- {item}")
        lines.append("")

    if state.failed:
        lines.append("## What Has Failed")
        for item in state.failed:
            lines.append(f"- {item}")
        lines.append("")

    if state.open_questions:
        lines.append("## Open Questions")
        for item in state.open_questions:
            lines.append(f"- {item}")
        lines.append("")

    if state.next_step:
        lines.append("## Next Step")
        lines.append(state.next_step)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path

def load_session(path: str | Path) -> SessionState:
    """Load session state from a markdown file."""
    import re
    path = Path(path)
    content = path.read_text(encoding="utf-8")

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not fm_match:
        raise ValueError(f"Invalid session file: {path}")

    data = yaml.safe_load(fm_match.group(1)) or {}
    body = fm_match.group(2)

    state = SessionState(
        session_id=data.get("session_id", ""),
        date=data.get("date", ""),
        project=data.get("project", ""),
        branch=data.get("branch", ""),
        status=data.get("status", "unknown"),
    )

    # Parse sections from body
    current_section = None
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("## Working"):
            current_section = "working"
        elif line.startswith("## In Progress"):
            current_section = "in_progress"
        elif line.startswith("## Not Started"):
            current_section = "not_started"
        elif line.startswith("## What Has Failed"):
            current_section = "failed"
        elif line.startswith("## Open Questions"):
            current_section = "open_questions"
        elif line.startswith("## Next Step"):
            current_section = "next_step"
        elif line.startswith("- ") and current_section:
            item = line[2:]
            if current_section == "next_step":
                state.next_step = item
            else:
                getattr(state, current_section).append(item)
        elif line and current_section == "next_step":
            state.next_step = line

    return state

def list_recent_sessions(
    base_dir: str | Path | None = None,
    days: int = SESSION_CLEANUP_DAYS,
) -> list[Path]:
    """List session files from the last N days, newest first."""
    if base_dir is None:
        base_dir = Path.home() / ".autoharness" / SESSION_DIR_NAME
    else:
        base_dir = Path(base_dir)

    if not base_dir.is_dir():
        return []

    cutoff = time.time() - days * 86400
    sessions = []
    for f in base_dir.glob("*-session.md"):
        if f.stat().st_mtime >= cutoff:
            sessions.append(f)

    sessions.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return sessions

def cleanup_old_sessions(
    base_dir: str | Path | None = None,
    days: int = SESSION_CLEANUP_DAYS,
) -> int:
    """Remove session files older than N days. Returns count removed."""
    if base_dir is None:
        base_dir = Path.home() / ".autoharness" / SESSION_DIR_NAME
    else:
        base_dir = Path(base_dir)

    if not base_dir.is_dir():
        return 0

    cutoff = time.time() - days * 86400
    removed = 0
    for f in base_dir.glob("*-session.md"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed
