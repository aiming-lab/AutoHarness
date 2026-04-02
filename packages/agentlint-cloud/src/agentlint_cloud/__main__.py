"""Entry point for ``python -m autoharness_cloud``."""

import argparse
import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AutoHarness Cloud — governance dashboard server"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8471, help="Port (default: 8471)"
    )
    parser.add_argument(
        "--audit-path",
        default=".autoharness/audit.jsonl",
        help="Path to JSONL audit log (default: .autoharness/audit.jsonl)",
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )
    args = parser.parse_args()

    import os
    os.environ.setdefault("AUTOHARNESS_AUDIT_PATH", args.audit_path)

    uvicorn.run(
        "autoharness_cloud.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
