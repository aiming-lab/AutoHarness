"""Filesystem-based execution trace store for governance diagnostics.

Inspired by Meta-Harness (Stanford, 2026), which demonstrated that
preserving full execution traces on the filesystem (rather than
compressing them into summaries) preserves critical diagnostic signal
for improving agent performance.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceStore:
    """Stores and retrieves per-session execution traces as individual JSON files.

    Each tool invocation is recorded as a separate file under
    ``{base_dir}/{session_id}/trace_{timestamp}_{tool_name}.json``,
    preserving the full execution context for later analysis.
    """

    def __init__(self, base_dir: str = ".autoharness/traces") -> None:
        self.base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def record_trace(
        self,
        session_id: str,
        tool_call_data: dict[str, Any],
        result_data: dict[str, Any],
        risk_data: dict[str, Any],
    ) -> Path:
        """Persist a single execution trace entry to disk.

        Parameters
        ----------
        session_id:
            Unique identifier for the agent session.
        tool_call_data:
            Raw tool call payload (name, arguments, etc.).
        result_data:
            Outcome of the tool invocation (output, status, etc.).
        risk_data:
            Governance risk assessment (level, flags, blocked, etc.).

        Returns
        -------
        Path
            The path to the written trace file.
        """
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        tool_name = tool_call_data.get("name", "unknown")
        # Sanitise tool name so it is safe as a filename component.
        safe_tool_name = "".join(
            c if c.isalnum() or c in ("_", "-") else "_" for c in tool_name
        )

        filename = f"trace_{timestamp}_{safe_tool_name}.json"
        trace_path = session_dir / filename

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "tool_call": tool_call_data,
            "result": result_data,
            "risk": risk_data,
        }

        trace_path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")
        return trace_path

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_traces(self, session_id: str) -> list[dict[str, Any]]:
        """Return *all* traces for a session, sorted chronologically."""
        session_dir = self.base_dir / session_id
        if not session_dir.is_dir():
            return []

        traces: list[dict[str, Any]] = []
        for path in sorted(session_dir.glob("trace_*.json")):
            try:
                traces.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return traces

    def get_recent_traces(
        self, session_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return the most recent *limit* traces for a session."""
        session_dir = self.base_dir / session_id
        if not session_dir.is_dir():
            return []

        paths = sorted(session_dir.glob("trace_*.json"))
        recent_paths = paths[-limit:] if limit < len(paths) else paths

        traces: list[dict[str, Any]] = []
        for path in recent_paths:
            try:
                traces.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return traces

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze_patterns(self, session_id: str) -> dict[str, Any]:
        """Compute basic statistics over a session's traces.

        Returns a dict with:
        - ``total``: total number of traces
        - ``tool_counts``: ``{tool_name: count}``
        - ``risk_distribution``: ``{risk_level: count}``
        - ``blocked_count``: number of traces where ``risk.blocked`` is truthy
        """
        traces = self.get_traces(session_id)

        tool_counts: Counter[str] = Counter()
        risk_distribution: Counter[str] = Counter()
        blocked_count = 0

        for trace in traces:
            tool_call = trace.get("tool_call", {})
            tool_counts[tool_call.get("name", "unknown")] += 1

            risk = trace.get("risk", {})
            risk_level = risk.get("level", "unknown")
            risk_distribution[risk_level] += 1

            if risk.get("blocked"):
                blocked_count += 1

        return {
            "total": len(traces),
            "tool_counts": dict(tool_counts),
            "risk_distribution": dict(risk_distribution),
            "blocked_count": blocked_count,
        }
