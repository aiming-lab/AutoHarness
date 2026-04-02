"""Session cost tracking — per-session token usage and cost metrics."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Approximate pricing per 1M tokens (USD)
MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
}

@dataclass
class SessionCost:
    """Tracks cumulative token usage and estimated cost for a session."""
    session_id: str = ""
    model: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    turns: int = 0

    def record_turn(self, input_tokens: int = 0, output_tokens: int = 0,
                    cache_read: int = 0, cache_write: int = 0) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cache_read_tokens += cache_read
        self.total_cache_write_tokens += cache_write
        self.turns += 1

    @property
    def estimated_cost_usd(self) -> float:
        pricing = MODEL_PRICING.get(self.model, MODEL_PRICING.get("claude-sonnet-4-6", {}))
        if not pricing:
            return 0.0
        cost = (
            self.total_input_tokens * pricing.get("input", 3.0) / 1_000_000
            + self.total_output_tokens * pricing.get("output", 15.0) / 1_000_000
            + self.total_cache_read_tokens * pricing.get("cache_read", 0.3) / 1_000_000
            + self.total_cache_write_tokens * pricing.get("cache_write", 3.75) / 1_000_000
        )
        return round(cost, 4)

    @property
    def total_tokens(self) -> int:
        return (self.total_input_tokens + self.total_output_tokens +
                self.total_cache_read_tokens + self.total_cache_write_tokens)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> SessionCost:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)
