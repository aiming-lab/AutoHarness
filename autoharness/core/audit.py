"""Audit Engine — structured JSONL logging of all governance decisions.

Provides a thread-safe, append-only audit trail of every tool call that
passes through the AutoHarness governance pipeline: risk assessments, hook
results, permission decisions, and execution outcomes.

Records are written as newline-delimited JSON (JSONL) for easy streaming,
rotation, and ingestion by downstream analytics.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import textwrap
import threading
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autoharness.core.types import (
    AuditRecord,
    HookResult,
    PermissionDecision,
    RiskAssessment,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)


class AuditEngine:
    """Thread-safe JSONL audit logger for AutoHarness governance decisions.

    Parameters
    ----------
    output_path : str
        Path to the JSONL audit file.  Parent directories are created
        automatically.
    enabled : bool
        If ``False``, all logging methods become no-ops.
    retention_days : int
        Default number of days to retain records.  Used by ``cleanup()``.
    """

    def __init__(
        self,
        output_path: str = ".autoharness/audit.jsonl",
        enabled: bool = True,
        retention_days: int = 30,
    ) -> None:
        self._output_path = output_path
        self._enabled = enabled
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._file_handle = None
        self._closed = False

        if self._enabled:
            # Create parent directory
            parent = Path(output_path).parent
            parent.mkdir(parents=True, exist_ok=True)

            # Open for append
            try:
                self._file_handle = open(output_path, "a", encoding="utf-8")  # noqa: SIM115
            except OSError:
                logger.exception("Failed to open audit log: %s", output_path)
                self._enabled = False

        logger.debug(
            "AuditEngine initialized: path=%s, enabled=%s, retention=%d days",
            output_path,
            self._enabled,
            retention_days,
        )

    # ------------------------------------------------------------------
    # Public logging API
    # ------------------------------------------------------------------

    def log(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment | None,
        pre_hooks: list[HookResult],
        permission: PermissionDecision,
        result: ToolResult | None,
        post_hooks: list[HookResult],
        session_id: str | None = None,
    ) -> None:
        """Log a complete tool execution cycle (call -> result).

        This is the primary logging method for successful (or allowed)
        tool invocations.
        """
        if not self._enabled:
            return

        record = self._build_record(
            tool_call=tool_call,
            risk=risk,
            pre_hooks=pre_hooks,
            permission=permission,
            result=result,
            post_hooks=post_hooks,
            session_id=session_id,
            event_type="tool_call",
        )
        self._write(record)

    def log_block(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment | None,
        pre_hooks: list[HookResult],
        permission: PermissionDecision,
        session_id: str | None = None,
    ) -> None:
        """Log a blocked tool call (denied by hook or permission check)."""
        if not self._enabled:
            return

        record = self._build_record(
            tool_call=tool_call,
            risk=risk,
            pre_hooks=pre_hooks,
            permission=permission,
            result=None,
            post_hooks=[],
            session_id=session_id,
            event_type="tool_blocked",
        )
        self._write(record)

    def log_error(
        self,
        tool_call: ToolCall,
        error: str | Exception,
        session_id: str | None = None,
    ) -> None:
        """Log an error that occurred during tool governance or execution."""
        if not self._enabled:
            return

        error_str = str(error)
        # Build a minimal record for error events
        now = datetime.now(timezone.utc)
        sid = session_id or tool_call.session_id or "unknown"
        input_hash = self._hash_input(tool_call.tool_input)

        # Create a synthetic permission decision for the error case
        perm = PermissionDecision(
            action="deny",
            reason=f"Error during governance: {error_str[:200]}",
            source="error_handler",
        )

        record = AuditRecord(
            timestamp=now,
            session_id=sid,
            event_type="tool_error",
            tool_name=tool_call.tool_name,
            tool_input_hash=input_hash,
            risk=None,
            hooks_pre=[],
            hooks_post=[],
            permission=perm,
            execution={
                "status": "error",
                "duration_ms": 0,
                "output_size": 0,
                "sanitized": False,
                "error": error_str[:1000],
            },
        )
        self._write(record)

    # ------------------------------------------------------------------
    # Record construction
    # ------------------------------------------------------------------

    def _build_record(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment | None,
        pre_hooks: list[HookResult],
        permission: PermissionDecision,
        result: ToolResult | None,
        post_hooks: list[HookResult],
        session_id: str | None,
        event_type: str,
    ) -> AuditRecord:
        """Construct a complete audit record from governance pipeline data."""
        now = datetime.now(timezone.utc)
        sid = session_id or tool_call.session_id or "unknown"
        input_hash = self._hash_input(tool_call.tool_input)

        # Summarize hook results as dicts
        pre_summaries = [
            {
                "action": hr.action.value,
                "reason": hr.reason,
                "severity": hr.severity,
            }
            for hr in pre_hooks
        ]
        post_summaries = [
            {
                "action": hr.action.value,
                "reason": hr.reason,
                "severity": hr.severity,
                "sanitized": hr.sanitized_output is not None,
            }
            for hr in post_hooks
        ]

        # Build execution summary
        execution: dict[str, Any]
        if result is not None:
            output_text = str(result.output) if result.output is not None else ""
            execution = {
                "status": result.status,
                "duration_ms": result.duration_ms,
                "output_size": len(output_text),
                "sanitized": result.sanitized,
            }
            if result.error:
                execution["error"] = result.error[:1000]
        else:
            execution = {
                "status": "blocked" if event_type == "tool_blocked" else "pending",
                "duration_ms": 0,
                "output_size": 0,
                "sanitized": False,
            }

        return AuditRecord(
            timestamp=now,
            session_id=sid,
            event_type=event_type,  # type: ignore[arg-type]  # validated by callers
            tool_name=tool_call.tool_name,
            tool_input_hash=input_hash,
            risk=risk,
            hooks_pre=pre_summaries,
            hooks_post=post_summaries,
            permission=permission,
            execution=execution,
        )

    @staticmethod
    def _hash_input(tool_input: dict[str, Any]) -> str:
        """Compute SHA-256 hex digest of tool input for audit security.

        Uses deterministic JSON serialization (sorted keys, str default)
        so identical logical inputs always produce the same hash.
        """
        canonical = json.dumps(tool_input, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Thread-safe writing
    # ------------------------------------------------------------------

    def _write(self, record: AuditRecord) -> None:
        """Append a single record as a JSON line to the audit file.

        Thread-safe: acquires the internal lock before writing.
        """
        if not self._enabled or self._file_handle is None or self._closed:
            return

        line = record.to_jsonl() + "\n"

        with self._lock:
            try:
                self._file_handle.write(line)
                self._file_handle.flush()
            except OSError:
                logger.exception("Failed to write audit record")

    # ------------------------------------------------------------------
    # Query and reporting
    # ------------------------------------------------------------------

    def get_records(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """Read and return audit records from the log file.

        Parameters
        ----------
        session_id : str | None
            Filter to records from this session only.
        event_type : str | None
            Filter to this event type (e.g. ``"tool_blocked"``).
        limit : int
            Maximum number of records to return.

        Returns
        -------
        list[AuditRecord]
            Matching records, most recent first.
        """
        records: list[AuditRecord] = []

        if not os.path.exists(self._output_path):
            return records

        try:
            with open(self._output_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = AuditRecord.model_validate_json(line)
                    except Exception:
                        logger.debug("Skipping malformed audit line: %.80s...", line)
                        continue

                    if session_id and record.session_id != session_id:
                        continue
                    if event_type and record.event_type != event_type:
                        continue
                    records.append(record)
        except OSError:
            logger.exception("Failed to read audit log: %s", self._output_path)

        # Most recent first, capped at limit
        records.reverse()
        return records[:limit]

    def stream_records(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Iterator[AuditRecord]:
        """Stream audit records without loading the entire file into memory.

        Parameters
        ----------
        session_id : str | None
            Filter to records from this session only.
        event_type : str | None
            Filter to this event type.
        offset : int
            Skip the first *offset* matching records.
        limit : int | None
            Stop after yielding *limit* records.  ``None`` = unlimited.

        Yields
        ------
        AuditRecord
            Records in file order (oldest first).
        """
        if not os.path.exists(self._output_path):
            return

        matched = 0
        yielded = 0
        try:
            with open(self._output_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = AuditRecord.model_validate_json(line)
                    except Exception:
                        continue

                    if session_id and record.session_id != session_id:
                        continue
                    if event_type and record.event_type != event_type:
                        continue

                    matched += 1
                    if matched <= offset:
                        continue

                    yield record
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
        except OSError:
            logger.exception("Failed to stream audit log: %s", self._output_path)

    def rotate(self, max_size_mb: float = 50.0) -> bool:
        """Rotate the audit log if it exceeds *max_size_mb*.

        The current log is renamed with a timestamp suffix and a new
        empty log is started.

        Returns True if rotation was performed.
        """
        if not os.path.exists(self._output_path):
            return False

        try:
            size_mb = os.path.getsize(self._output_path) / (1024 * 1024)
        except OSError:
            return False

        if size_mb < max_size_mb:
            return False

        # Close current handle
        with self._lock:
            if self._file_handle and not self._closed:
                self._file_handle.close()

            # Rename with timestamp
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            rotated = f"{self._output_path}.{ts}"
            try:
                os.rename(self._output_path, rotated)
            except OSError:
                logger.exception("Failed to rotate audit log")
                return False

            # Open new file
            try:
                self._file_handle = open(self._output_path, "a", encoding="utf-8")  # noqa: SIM115
            except OSError:
                logger.exception("Failed to open new audit log after rotation")
                self._enabled = False
                return False

        logger.info("Rotated audit log: %s -> %s (%.1f MB)", self._output_path, rotated, size_mb)
        return True

    def get_summary(self, session_id: str | None = None) -> dict[str, Any]:
        """Return summary statistics from the audit log.

        Returns
        -------
        dict
            Keys: ``total_calls``, ``blocked_count``, ``error_count``,
            ``risk_distribution``, ``top_blocked_reasons``,
            ``tools_used``, ``session_duration``.
        """
        records = self.get_records(session_id=session_id, limit=100_000)

        total = len(records)
        blocked = 0
        errors = 0
        risk_dist: Counter[str] = Counter()
        blocked_reasons: Counter[str] = Counter()
        tools_used: Counter[str] = Counter()
        timestamps: list[datetime] = []

        for rec in records:
            tools_used[rec.tool_name] += 1
            timestamps.append(rec.timestamp)

            if rec.event_type == "tool_blocked":
                blocked += 1
                blocked_reasons[rec.permission.reason] += 1
            elif rec.event_type == "tool_error":
                errors += 1

            if rec.risk is not None:
                risk_dist[rec.risk.level.value] += 1
            else:
                risk_dist["unassessed"] += 1

        # Compute session duration
        session_duration_s = 0.0
        if len(timestamps) >= 2:
            sorted_ts = sorted(timestamps)
            delta = sorted_ts[-1] - sorted_ts[0]
            session_duration_s = delta.total_seconds()

        return {
            "total_calls": total,
            "blocked_count": blocked,
            "error_count": errors,
            "risk_distribution": dict(risk_dist),
            "top_blocked_reasons": dict(blocked_reasons.most_common(10)),
            "tools_used": dict(tools_used.most_common(20)),
            "session_duration_seconds": session_duration_s,
        }

    def generate_report(
        self,
        format: str = "text",
        output: str | None = None,
    ) -> str:
        """Generate a human-readable audit report.

        Parameters
        ----------
        format : str
            ``"text"`` for terminal output, ``"html"`` for a standalone
            HTML page, ``"json"`` for machine-readable JSON.
        output : str | None
            If provided, write the report to this file path.

        Returns
        -------
        str
            The generated report content.
        """
        summary = self.get_summary()

        if format == "json":
            report = json.dumps(summary, indent=2, default=str)
        elif format == "html":
            report = self._generate_html_report(summary)
        else:
            report = self._generate_text_report(summary)

        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                f.write(report)
            logger.info("Audit report written to: %s", output)

        return report

    def _generate_text_report(self, summary: dict[str, Any]) -> str:
        """Produce a terminal-friendly text report."""
        total = summary["total_calls"]
        blocked = summary["blocked_count"]
        errors = summary["error_count"]
        allowed = total - blocked - errors
        duration = summary["session_duration_seconds"]

        lines = [
            "",
            "=" * 60,
            "  AutoHarness Audit Report",
            "=" * 60,
            "",
            f"  Total tool calls:    {total}",
            f"  Allowed:             {allowed}",
            f"  Blocked:             {blocked}",
            f"  Errors:              {errors}",
            f"  Session duration:    {duration:.1f}s",
            "",
            "-" * 60,
            "  Risk Distribution",
            "-" * 60,
        ]

        risk_dist = summary["risk_distribution"]
        for level in ("critical", "high", "medium", "low", "unassessed"):
            count = risk_dist.get(level, 0)
            if count > 0:
                bar = "#" * min(count, 40)
                lines.append(f"  {level:<12s}  {count:>5d}  {bar}")

        if summary["top_blocked_reasons"]:
            lines.extend([
                "",
                "-" * 60,
                "  Top Blocked Reasons",
                "-" * 60,
            ])
            for reason, count in summary["top_blocked_reasons"].items():
                # Truncate long reasons
                short = textwrap.shorten(reason, width=45, placeholder="...")
                lines.append(f"  {count:>4d}x  {short}")

        if summary["tools_used"]:
            lines.extend([
                "",
                "-" * 60,
                "  Tools Used",
                "-" * 60,
            ])
            for tool, count in summary["tools_used"].items():
                lines.append(f"  {count:>5d}  {tool}")

        lines.extend(["", "=" * 60, ""])
        return "\n".join(lines)

    def _generate_html_report(self, summary: dict[str, Any]) -> str:
        """Produce a standalone HTML report with inline CSS charts."""
        total = summary["total_calls"]
        blocked = summary["blocked_count"]
        errors = summary["error_count"]
        allowed = total - blocked - errors
        duration = summary["session_duration_seconds"]
        risk_dist = summary["risk_distribution"]

        # Build risk bars
        max_risk = max(risk_dist.values()) if risk_dist else 1
        risk_colors = {
            "critical": "#dc3545",
            "high": "#fd7e14",
            "medium": "#ffc107",
            "low": "#28a745",
            "unassessed": "#6c757d",
        }
        risk_rows = []
        for level in ("critical", "high", "medium", "low", "unassessed"):
            count = risk_dist.get(level, 0)
            if count > 0:
                pct = (count / max_risk) * 100
                color = risk_colors.get(level, "#6c757d")
                risk_rows.append(
                    f'<tr><td>{level}</td><td>{count}</td>'
                    f'<td><div style="background:{color};width:{pct:.0f}%;'
                    f'height:20px;border-radius:3px"></div></td></tr>'
                )

        # Build tools table
        tools_rows = []
        for tool, count in summary["tools_used"].items():
            tools_rows.append(f"<tr><td>{tool}</td><td>{count}</td></tr>")

        # Build blocked reasons
        blocked_rows = []
        for reason, count in summary["top_blocked_reasons"].items():
            escaped = reason.replace("&", "&amp;").replace("<", "&lt;")
            blocked_rows.append(f"<tr><td>{count}</td><td>{escaped}</td></tr>")

        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AutoHarness Audit Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 800px; margin: 40px auto; padding: 0 20px; color: #222; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 10px; }}
  h2 {{ color: #555; margin-top: 30px; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px; margin: 20px 0; }}
  .stat {{ background: #f8f9fa; border-radius: 8px; padding: 15px; text-align: center; }}
  .stat .value {{ font-size: 2em; font-weight: bold; }}
  .stat .label {{ font-size: 0.85em; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  td, th {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
  th {{ background: #f0f0f0; }}
  .blocked {{ color: #dc3545; font-weight: bold; }}
  .error {{ color: #fd7e14; font-weight: bold; }}
</style>
</head>
<body>
<h1>AutoHarness Audit Report</h1>

<div class="stats">
  <div class="stat"><div class="value">{total}</div><div class="label">Total Calls</div></div>
  <div class="stat"><div class="value">{allowed}</div><div class="label">Allowed</div></div>
  <div class="stat"><div class="value blocked">{blocked}</div><div class="label">Blocked</div></div>
  <div class="stat"><div class="value error">{errors}</div><div class="label">Errors</div></div>
  <div class="stat"><div class="value">{duration:.0f}s</div><div class="label">Duration</div></div>
</div>

<h2>Risk Distribution</h2>
<table>
<tr><th>Level</th><th>Count</th><th>Distribution</th></tr>
{"".join(risk_rows)}
</table>

<h2>Tools Used</h2>
<table>
<tr><th>Tool</th><th>Count</th></tr>
{"".join(tools_rows)}
</table>

{"<h2>Top Blocked Reasons</h2>" if blocked_rows else ""}
{"<table><tr><th>Count</th><th>Reason</th></tr>"
+ "".join(blocked_rows) + "</table>"
if blocked_rows else ""}

<p style="color:#999;font-size:0.8em;margin-top:40px">
  Generated by AutoHarness AuditEngine at {datetime.now(timezone.utc).isoformat()}
</p>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self, retention_days: int | None = None) -> int:
        """Remove audit records older than the retention period.

        Parameters
        ----------
        retention_days : int | None
            Override the default retention period.

        Returns
        -------
        int
            Number of records removed.
        """
        days = retention_days if retention_days is not None else self._retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        if not os.path.exists(self._output_path):
            return 0

        kept_lines: list[str] = []
        removed = 0

        try:
            with open(self._output_path, encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = AuditRecord.model_validate_json(stripped)
                        if record.timestamp < cutoff:
                            removed += 1
                            continue
                    except Exception:
                        # Keep malformed lines to avoid data loss
                        pass
                    kept_lines.append(line)
        except OSError:
            logger.exception("Failed to read audit log for cleanup")
            return 0

        if removed > 0:
            with self._lock:
                try:
                    # Close current handle, rewrite, reopen
                    if self._file_handle and not self._closed:
                        self._file_handle.close()

                    with open(self._output_path, "w", encoding="utf-8") as f:
                        f.writelines(kept_lines)

                    if not self._closed:
                        self._file_handle = open(  # noqa: SIM115
                            self._output_path, "a", encoding="utf-8"
                        )

                    logger.info(
                        "Audit cleanup: removed %d records older than %d days",
                        removed,
                        days,
                    )
                except OSError:
                    logger.exception("Failed to rewrite audit log during cleanup")

        return removed

    def close(self) -> None:
        """Flush and close the audit file handle."""
        with self._lock:
            if self._file_handle and not self._closed:
                try:
                    self._file_handle.flush()
                    self._file_handle.close()
                except OSError:
                    logger.exception("Error closing audit log")
                finally:
                    self._closed = True
                    self._file_handle = None

        logger.debug("AuditEngine closed: %s", self._output_path)

    def __enter__(self) -> AuditEngine:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if not self._closed and self._file_handle is not None:
            with contextlib.suppress(Exception):
                self.close()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether audit logging is active."""
        return self._enabled

    @property
    def output_path(self) -> str:
        """Path to the JSONL audit file."""
        return self._output_path

    def __repr__(self) -> str:
        return (
            f"<AuditEngine path={self._output_path!r} "
            f"enabled={self._enabled} closed={self._closed}>"
        )
