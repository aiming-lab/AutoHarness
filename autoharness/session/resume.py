"""Session resume — structured briefing from saved session state."""
from __future__ import annotations

from pathlib import Path

from autoharness.session.persistence import SessionState, list_recent_sessions, load_session


def resume_session(path: str | Path | None = None, base_dir: str | Path | None = None) -> str:
    """Generate a structured resume briefing.

    If no path given, uses most recent session file.
    Returns formatted briefing string.
    """
    if path is None:
        recent = list_recent_sessions(base_dir)
        if not recent:
            return "No recent sessions found."
        path = recent[0]

    state = load_session(path)
    return format_briefing(state)

def format_briefing(state: SessionState) -> str:
    """Format a session state into a structured briefing."""
    lines = ["# Session Resume Briefing\n"]

    lines.append(f"**PROJECT**: {state.project or 'Unknown'}")
    lines.append(f"**BRANCH**: {state.branch or 'Unknown'}")
    lines.append(f"**STATUS**: {state.status}")
    lines.append(f"**DATE**: {state.date}\n")

    if state.working:
        lines.append("## COMPLETED")
        for item in state.working:
            lines.append(f"- \u2705 {item}")
        lines.append("")

    if state.in_progress:
        lines.append("## IN PROGRESS")
        for item in state.in_progress:
            lines.append(f"- \U0001f504 {item}")
        lines.append("")

    if state.not_started:
        lines.append("## NOT STARTED")
        for item in state.not_started:
            lines.append(f"- \u2b1c {item}")
        lines.append("")

    if state.failed:
        lines.append("## WHAT NOT TO RETRY")
        for item in state.failed:
            lines.append(f"- \u274c {item}")
        lines.append("")

    if state.open_questions:
        lines.append("## OPEN QUESTIONS")
        for item in state.open_questions:
            lines.append(f"- \u2753 {item}")
        lines.append("")

    if state.next_step:
        lines.append("## NEXT STEP")
        lines.append(state.next_step)

    return "\n".join(lines)
