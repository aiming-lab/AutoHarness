"""Cost attribution — fine-grained cost tracking per tool, agent, and workflow.

Tracks token costs at multiple granularities: per-tool-call, per-agent,
per-workflow, and per-session. Enables cost optimization and billing.

Usage::

    tracker = CostTracker()

    with tracker.track_call("Bash", agent_id="explore-1") as call:
        # ... execute tool call ...
        call.record_tokens(input=1200, output=300)

    report = tracker.generate_report()
    print(report.by_tool)     # {"Bash": $0.012, "Read": $0.003, ...}
    print(report.by_agent)    # {"explore-1": $0.015, "plan-1": $0.008}
    print(report.total_cost)  # $0.023
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing tables — cost per 1M tokens (USD)
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-sonnet-4": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-3.5": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
    # OpenAI
    "gpt-4o": {
        "input": 2.50,
        "output": 10.0,
        "cache_read": 1.25,
        "cache_write": 2.50,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cache_read": 0.075,
        "cache_write": 0.15,
    },
    "o3": {
        "input": 10.0,
        "output": 40.0,
        "cache_read": 5.0,
        "cache_write": 10.0,
    },
    "o3-mini": {
        "input": 1.10,
        "output": 4.40,
        "cache_read": 0.55,
        "cache_write": 1.10,
    },
}

# Fallback when model is not in the pricing table.
_DEFAULT_PRICING: dict[str, float] = {
    "input": 3.0,
    "output": 15.0,
    "cache_read": 0.30,
    "cache_write": 3.75,
}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def compute_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Compute the cost in USD for a given token usage.

    Returns the cost rounded to six decimal places.  Unknown models fall back
    to Sonnet-class pricing so callers always get a reasonable estimate.
    """
    pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    cost = (
        input_tokens * pricing.get("input", _DEFAULT_PRICING["input"]) / 1_000_000
        + output_tokens * pricing.get("output", _DEFAULT_PRICING["output"]) / 1_000_000
        + cache_read_tokens * pricing.get("cache_read", _DEFAULT_PRICING["cache_read"]) / 1_000_000
        + cache_write_tokens
            * pricing.get("cache_write", _DEFAULT_PRICING["cache_write"])
            / 1_000_000
    )
    return round(cost, 6)


def compute_cache_savings(
    model: str,
    cache_read_tokens: int = 0,
) -> float:
    """Estimate money saved by cache hits vs. paying full input price."""
    pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    full_input_rate = pricing.get("input", _DEFAULT_PRICING["input"])
    cache_read_rate = pricing.get("cache_read", _DEFAULT_PRICING["cache_read"])
    savings = cache_read_tokens * (full_input_rate - cache_read_rate) / 1_000_000
    return round(savings, 6)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CostEntry:
    """A single cost-attribution record."""

    tool_name: str
    model: str
    input_tokens: int
    output_tokens: int
    timestamp: float
    cost_usd: float
    agent_id: str | None = None
    workflow_id: str | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class CostReport:
    """Aggregated cost breakdown across multiple dimensions."""

    by_tool: dict[str, float] = field(default_factory=dict)
    by_agent: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    by_workflow: dict[str, float] = field(default_factory=dict)
    total_cost: float = 0.0
    total_tokens: int = 0
    cache_savings: float = 0.0

    def format_table(self) -> str:
        """Return a human-readable table summarising the report."""
        lines: list[str] = []
        sep = "-" * 52

        lines.append(sep)
        lines.append(f"{'Cost Attribution Report':^52}")
        lines.append(sep)

        def _section(title: str, data: dict[str, float]) -> None:
            if not data:
                return
            lines.append(f"\n  {title}")
            lines.append(f"  {'':─<48}")
            for key, val in sorted(data.items(), key=lambda kv: -kv[1]):
                lines.append(f"    {key:<32} ${val:>10.4f}")

        _section("By Tool", self.by_tool)
        _section("By Agent", self.by_agent)
        _section("By Model", self.by_model)
        _section("By Workflow", self.by_workflow)

        lines.append(f"\n{sep}")
        lines.append(f"  Total cost:          ${self.total_cost:>10.4f}")
        lines.append(f"  Total tokens:        {self.total_tokens:>11,}")
        lines.append(f"  Cache savings:       ${self.cache_savings:>10.4f}")
        lines.append(sep)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Call context manager helper
# ---------------------------------------------------------------------------

class _CallContext:
    """Accumulates token usage within a ``track_call`` block."""

    def __init__(self, tool_name: str, model: str, agent_id: str | None,
                 workflow_id: str | None, tracker: CostTracker) -> None:
        self._tool_name = tool_name
        self._model = model
        self._agent_id = agent_id
        self._workflow_id = workflow_id
        self._tracker = tracker
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._committed = False

    def record_tokens(
        self,
        input: int = 0,
        output: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> None:
        """Record token counts for this call."""
        self._input_tokens += input
        self._output_tokens += output
        self._cache_read_tokens += cache_read
        self._cache_write_tokens += cache_write

    def _commit(self) -> None:
        """Flush accumulated usage into the parent tracker."""
        if self._committed:
            return
        self._committed = True
        self._tracker.record_usage(
            model=self._model,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cache_read=self._cache_read_tokens,
            cache_write=self._cache_write_tokens,
            tool_name=self._tool_name,
            agent_id=self._agent_id,
            workflow_id=self._workflow_id,
        )


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------

class CostTracker:
    """Thread-safe, fine-grained cost attribution tracker.

    Collects :class:`CostEntry` records and produces :class:`CostReport`
    breakdowns on demand.  Intended to be shared across all agents in a
    single session.
    """

    def __init__(self, default_model: str = "claude-sonnet-4") -> None:
        self._entries: list[CostEntry] = []
        self._lock = threading.Lock()
        self._default_model = default_model

    # -- recording -----------------------------------------------------------

    @contextmanager
    def track_call(
        self,
        tool_name: str,
        *,
        model: str | None = None,
        agent_id: str | None = None,
        workflow_id: str | None = None,
    ) -> Generator[_CallContext, None, None]:
        """Context manager that attributes cost to a single tool call.

        Token usage recorded via the yielded :class:`_CallContext` is committed
        to the tracker when the block exits.
        """
        ctx = _CallContext(
            tool_name=tool_name,
            model=model or self._default_model,
            agent_id=agent_id,
            workflow_id=workflow_id,
            tracker=self,
        )
        try:
            yield ctx
        finally:
            ctx._commit()

    def record_usage(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        tool_name: str | None = None,
        agent_id: str | None = None,
        workflow_id: str | None = None,
    ) -> CostEntry:
        """Directly record a cost entry without the context-manager pattern."""
        cost = compute_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        entry = CostEntry(
            tool_name=tool_name or "unknown",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
            agent_id=agent_id,
            workflow_id=workflow_id,
            timestamp=time.time(),
        )
        with self._lock:
            self._entries.append(entry)
        logger.debug(
            "cost_entry tool=%s agent=%s cost=$%.6f",
            entry.tool_name, entry.agent_id, entry.cost_usd,
        )
        return entry

    # -- querying ------------------------------------------------------------

    @property
    def entries(self) -> list[CostEntry]:
        """Return a snapshot of all recorded entries."""
        with self._lock:
            return list(self._entries)

    @property
    def total_cost(self) -> float:
        """Sum of all recorded costs in USD."""
        with self._lock:
            return round(sum(e.cost_usd for e in self._entries), 6)

    def generate_report(self) -> CostReport:
        """Build an aggregated :class:`CostReport` from current entries."""
        with self._lock:
            snapshot = list(self._entries)

        by_tool: dict[str, float] = defaultdict(float)
        by_agent: dict[str, float] = defaultdict(float)
        by_model: dict[str, float] = defaultdict(float)
        by_workflow: dict[str, float] = defaultdict(float)
        total_cost = 0.0
        total_tokens = 0
        cache_savings = 0.0

        for entry in snapshot:
            total_cost += entry.cost_usd
            total_tokens += (
                entry.input_tokens + entry.output_tokens
                + entry.cache_read_tokens + entry.cache_write_tokens
            )
            by_tool[entry.tool_name] += entry.cost_usd
            by_model[entry.model] += entry.cost_usd
            if entry.agent_id:
                by_agent[entry.agent_id] += entry.cost_usd
            if entry.workflow_id:
                by_workflow[entry.workflow_id] += entry.cost_usd
            cache_savings += compute_cache_savings(entry.model, entry.cache_read_tokens)

        return CostReport(
            by_tool=dict(by_tool),
            by_agent=dict(by_agent),
            by_model=dict(by_model),
            by_workflow=dict(by_workflow),
            total_cost=round(total_cost, 6),
            total_tokens=total_tokens,
            cache_savings=round(cache_savings, 6),
        )
