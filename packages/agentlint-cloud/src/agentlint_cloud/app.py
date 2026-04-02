"""AutoHarness Cloud — FastAPI application for audit visualization and governance."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autoharness.core.audit import AuditEngine
from autoharness.core.types import AuditRecord, ConstitutionConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AutoHarness Cloud",
    description="Audit visualization and team governance dashboard",
    version="0.1.0",
)

_BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=_BASE_DIR / "static"), name="static")
_templates = Jinja2Templates(directory=_BASE_DIR / "templates")

# In-memory store for ingested records (from remote agents)
_ingested_records: list[dict[str, Any]] = []


def _get_audit_engine() -> AuditEngine:
    """Create an AuditEngine pointing at the configured audit log."""
    audit_path = os.environ.get("AUTOHARNESS_AUDIT_PATH", ".autoharness/audit.jsonl")
    return AuditEngine(output_path=audit_path, enabled=True)


def _load_all_records(
    session_id: str | None = None,
    limit: int = 100_000,
) -> list[AuditRecord]:
    """Load records from both the local audit file and ingested records."""
    engine = _get_audit_engine()
    records = engine.get_records(session_id=session_id, limit=limit)
    engine.close()

    # Parse ingested records
    for raw in _ingested_records:
        try:
            rec = AuditRecord.model_validate(raw)
            if session_id and rec.session_id != session_id:
                continue
            records.append(rec)
        except Exception:
            continue

    # Sort by timestamp descending
    records.sort(key=lambda r: r.timestamp, reverse=True)
    return records[:limit]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Serve the main dashboard page."""
    return _templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/summary")
async def api_summary(session: str | None = Query(None)) -> JSONResponse:
    """Return audit summary statistics."""
    records = _load_all_records(session_id=session)

    total = len(records)
    blocked = 0
    errors = 0
    risk_dist: Counter[str] = Counter()
    blocked_reasons: Counter[str] = Counter()
    tools_used: Counter[str] = Counter()
    sessions: set[str] = set()

    for rec in records:
        tools_used[rec.tool_name] += 1
        sessions.add(rec.session_id)

        if rec.event_type == "tool_blocked":
            blocked += 1
            blocked_reasons[rec.permission.reason] += 1
        elif rec.event_type == "tool_error":
            errors += 1

        if rec.risk is not None:
            risk_dist[rec.risk.level.value] += 1
        else:
            risk_dist["unassessed"] += 1

    block_rate = (blocked / total * 100) if total > 0 else 0.0
    high_risk = risk_dist.get("high", 0) + risk_dist.get("critical", 0)

    return JSONResponse({
        "total_calls": total,
        "blocked_count": blocked,
        "error_count": errors,
        "block_rate": round(block_rate, 1),
        "high_risk_count": high_risk,
        "active_sessions": len(sessions),
        "risk_distribution": dict(risk_dist),
        "top_blocked_reasons": dict(blocked_reasons.most_common(10)),
        "tools_used": dict(tools_used.most_common(20)),
    })


@app.get("/api/records")
async def api_records(
    session: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """Return paginated audit records."""
    all_records = _load_all_records(session_id=session)
    page = all_records[offset : offset + limit]

    items = []
    for rec in page:
        items.append({
            "timestamp": rec.timestamp.isoformat(),
            "session_id": rec.session_id,
            "event_type": rec.event_type,
            "tool_name": rec.tool_name,
            "risk_level": rec.risk.level.value if rec.risk else None,
            "risk_reason": rec.risk.reason if rec.risk else None,
            "decision": rec.permission.action,
            "decision_reason": rec.permission.reason,
            "decision_source": rec.permission.source,
            "execution_status": rec.execution.get("status"),
            "duration_ms": rec.execution.get("duration_ms", 0),
        })

    return JSONResponse({
        "total": len(all_records),
        "offset": offset,
        "limit": limit,
        "records": items,
    })


@app.get("/api/sessions")
async def api_sessions() -> JSONResponse:
    """List all sessions with per-session stats."""
    records = _load_all_records()

    sessions: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0,
        "blocked": 0,
        "errors": 0,
        "first_seen": None,
        "last_seen": None,
        "tools": Counter(),
    })

    for rec in records:
        s = sessions[rec.session_id]
        s["total"] += 1
        if rec.event_type == "tool_blocked":
            s["blocked"] += 1
        elif rec.event_type == "tool_error":
            s["errors"] += 1

        ts = rec.timestamp.isoformat()
        if s["first_seen"] is None or ts < s["first_seen"]:
            s["first_seen"] = ts
        if s["last_seen"] is None or ts > s["last_seen"]:
            s["last_seen"] = ts
        s["tools"][rec.tool_name] += 1

    result = []
    for sid, stats in sessions.items():
        result.append({
            "session_id": sid,
            "total": stats["total"],
            "blocked": stats["blocked"],
            "errors": stats["errors"],
            "first_seen": stats["first_seen"],
            "last_seen": stats["last_seen"],
            "top_tools": dict(stats["tools"].most_common(5)),
        })

    result.sort(key=lambda x: x["last_seen"] or "", reverse=True)
    return JSONResponse(result)


@app.get("/api/timeline")
async def api_timeline(session: str | None = Query(None)) -> JSONResponse:
    """Return hourly aggregated time-series data for charting."""
    records = _load_all_records(session_id=session)

    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "blocked": 0, "errors": 0, "high_risk": 0}
    )

    for rec in records:
        # Truncate to hour
        hour_key = rec.timestamp.strftime("%Y-%m-%dT%H:00:00Z")
        b = buckets[hour_key]
        b["total"] += 1
        if rec.event_type == "tool_blocked":
            b["blocked"] += 1
        elif rec.event_type == "tool_error":
            b["errors"] += 1
        if rec.risk and rec.risk.level.value in ("high", "critical"):
            b["high_risk"] += 1

    # Sort by time
    timeline = [
        {"hour": k, **v}
        for k, v in sorted(buckets.items())
    ]

    return JSONResponse(timeline)


@app.post("/api/ingest")
async def api_ingest(request: Request) -> JSONResponse:
    """Accept audit records from remote agents for centralized visibility."""
    body = await request.json()

    if isinstance(body, list):
        records = body
    else:
        records = [body]

    accepted = 0
    for raw in records:
        try:
            # Validate the record can parse
            AuditRecord.model_validate(raw)
            _ingested_records.append(raw)
            accepted += 1
        except Exception as e:
            logger.debug("Rejected ingested record: %s", e)

    return JSONResponse({"accepted": accepted, "total_ingested": len(_ingested_records)})


@app.get("/api/constitution")
async def api_constitution() -> JSONResponse:
    """Return the current constitution configuration."""
    # Try to find a constitution file
    search_paths = [
        "autoharness.yml",
        "autoharness.yaml",
        ".autoharness/constitution.yml",
        ".autoharness/constitution.yaml",
    ]

    for path in search_paths:
        if os.path.exists(path):
            try:
                import yaml  # noqa: F811
                with open(path) as f:
                    data = yaml.safe_load(f)
                return JSONResponse(data)
            except ImportError:
                # Fall back to reading raw content
                with open(path) as f:
                    content = f.read()
                return JSONResponse({"raw": content, "format": "yaml"})
            except Exception:
                pass

    # Return default constitution
    config = ConstitutionConfig()
    return JSONResponse(json.loads(config.model_dump_json()))


@app.get("/health")
async def health() -> JSONResponse:
    """Health check endpoint."""
    audit_path = os.environ.get("AUTOHARNESS_AUDIT_PATH", ".autoharness/audit.jsonl")
    audit_exists = os.path.exists(audit_path)

    return JSONResponse({
        "status": "ok",
        "version": "0.1.0",
        "audit_path": audit_path,
        "audit_file_exists": audit_exists,
        "ingested_records": len(_ingested_records),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
