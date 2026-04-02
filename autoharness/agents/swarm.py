"""Agent team/swarm mode — multi-agent parallel execution with JSONL mailboxes.

Agents communicate via append-only JSONL inbox files.
Supports team protocols: message, broadcast, shutdown, plan approval.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5       # seconds
IDLE_TIMEOUT = 60       # seconds before auto-shutdown
MAX_TEAMMATE_ITERATIONS = 50

@dataclass
class TeamMember:
    name: str
    role: str
    status: Literal["working", "idle", "shutdown"] = "idle"

@dataclass
class TeamConfig:
    team_name: str = "default"
    members: list[TeamMember] = field(default_factory=list)

@dataclass
class TeamMessage:
    type: Literal["message", "broadcast", "shutdown_request",
                  "shutdown_response", "plan_approval_response"]
    from_agent: str
    content: str
    timestamp: float = field(default_factory=time.time)
    request_id: str | None = None
    approve: bool | None = None  # For response messages

VALID_MESSAGE_TYPES = {
    "message", "broadcast", "shutdown_request",
    "shutdown_response", "plan_approval_response",
}

class TeamMailbox:
    """File-based append-only JSONL mailbox for inter-agent communication."""

    def __init__(self, base_dir: str = ".autoharness/team") -> None:
        self.base_dir = Path(base_dir)
        self._lock = threading.Lock()

    def send(self, to: str, message: TeamMessage) -> None:
        """Send a message to an agent's inbox."""
        inbox_dir = self.base_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        inbox_file = inbox_dir / f"{to}.jsonl"

        line = json.dumps(asdict(message), ensure_ascii=False, default=str)
        with self._lock, open(inbox_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def broadcast(self, from_agent: str, content: str, members: list[str]) -> None:
        """Broadcast a message to all team members."""
        msg = TeamMessage(
            type="broadcast",
            from_agent=from_agent,
            content=content,
        )
        for member in members:
            if member != from_agent:
                self.send(member, msg)

    def read_inbox(self, agent_name: str) -> list[TeamMessage]:
        """Read and drain an agent's inbox (returns all messages, clears file)."""
        inbox_file = self.base_dir / "inbox" / f"{agent_name}.jsonl"
        if not inbox_file.is_file():
            return []

        messages = []
        with self._lock:
            try:
                lines = inbox_file.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    if line.strip():
                        data = json.loads(line)
                        messages.append(TeamMessage(**data))
                # Drain inbox
                inbox_file.write_text("", encoding="utf-8")
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Error reading inbox for %s: %s", agent_name, exc)

        return messages

    def save_config(self, config: TeamConfig) -> None:
        """Save team configuration."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        config_file = self.base_dir / "config.json"
        data = {
            "team_name": config.team_name,
            "members": [asdict(m) for m in config.members],
        }
        config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_config(self) -> TeamConfig | None:
        """Load team configuration."""
        config_file = self.base_dir / "config.json"
        if not config_file.is_file():
            return None
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            members = [TeamMember(**m) for m in data.get("members", [])]
            return TeamConfig(team_name=data.get("team_name", "default"), members=members)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Error loading team config: %s", exc)
            return None
