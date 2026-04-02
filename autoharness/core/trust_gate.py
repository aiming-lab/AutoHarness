"""Workspace trust gate — prevents untrusted project hooks from executing.

Requires workspace trust before any hook can execute.
This prevents malicious .autoharness.yaml hooks from running automatically.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_TRUST_FILE = Path.home() / ".autoharness" / "trusted_workspaces.json"


def is_workspace_trusted(workspace_dir: str) -> bool:
    """Check if a workspace directory has been marked as trusted."""
    workspace = os.path.realpath(workspace_dir)
    trusted = _load_trusted()
    return workspace in trusted


def trust_workspace(workspace_dir: str) -> None:
    """Mark a workspace as trusted."""
    workspace = os.path.realpath(workspace_dir)
    trusted = _load_trusted()
    trusted.add(workspace)
    _save_trusted(trusted)
    logger.info("Trusted workspace: %s", workspace)


def untrust_workspace(workspace_dir: str) -> None:
    """Remove trust from a workspace."""
    workspace = os.path.realpath(workspace_dir)
    trusted = _load_trusted()
    trusted.discard(workspace)
    _save_trusted(trusted)


def _load_trusted() -> set[str]:
    if not _TRUST_FILE.exists():
        return set()
    try:
        data = json.loads(_TRUST_FILE.read_text())
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def _save_trusted(trusted: set[str]) -> None:
    _TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TRUST_FILE.write_text(json.dumps(sorted(trusted), indent=2))
