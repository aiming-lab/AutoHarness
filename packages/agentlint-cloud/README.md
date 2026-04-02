# AutoHarness Cloud

Self-hostable web dashboard for AutoHarness audit visualization and team governance management.

## Quick Start

```bash
pip install autoharness-cloud
autoharness-cloud
```

Or run directly:

```bash
python -m autoharness_cloud
```

The dashboard opens at **http://localhost:8471**.

## Options

```
--host         Bind address (default: 0.0.0.0)
--port         Port (default: 8471)
--audit-path   Path to JSONL audit log (default: .autoharness/audit.jsonl)
--reload       Enable auto-reload for development
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard (HTML) |
| `/api/summary` | GET | Audit summary statistics |
| `/api/records` | GET | Paginated audit records |
| `/api/sessions` | GET | All sessions with stats |
| `/api/timeline` | GET | Hourly aggregated time-series data |
| `/api/constitution` | GET | Current constitution config |
| `/api/ingest` | POST | Accept audit records from remote agents |
| `/health` | GET | Health check |

## Team Use

Remote agents can push audit records to a central AutoHarness Cloud instance:

```python
import httpx
httpx.post("https://your-cloud:8471/api/ingest", json=audit_record_dict)
```

This enables centralized governance visibility across distributed agent deployments.
