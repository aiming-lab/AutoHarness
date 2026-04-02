"""Lightweight metrics collection for AutoHarness.

Tracks key operational metrics without requiring external dependencies.
When OTel is configured, exports to configured backend.
When not configured, metrics available via get_metrics().
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HarnessMetrics:
    """Accumulated metrics for a AutoHarness session."""

    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_governance_checks: int = 0
    total_governance_denials: int = 0
    total_compactions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_hook_executions: int = 0
    total_hook_failures: int = 0
    avg_governance_latency_ms: float = 0.0
    _governance_latencies: list[float] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_llm_call(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Record an LLM call with token counts."""
        with self._lock:
            self.total_llm_calls += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

    def record_tool_call(self) -> None:
        """Record a tool call execution."""
        with self._lock:
            self.total_tool_calls += 1

    def record_governance_check(self, allowed: bool, latency_ms: float) -> None:
        """Record a governance check with its result and latency."""
        with self._lock:
            self.total_governance_checks += 1
            if not allowed:
                self.total_governance_denials += 1
            self._governance_latencies.append(latency_ms)
            self.avg_governance_latency_ms = sum(self._governance_latencies) / len(
                self._governance_latencies
            )

    def record_compaction(self) -> None:
        """Record a context compaction event."""
        with self._lock:
            self.total_compactions += 1

    def record_hook(self, success: bool) -> None:
        """Record a hook execution with its success/failure status."""
        with self._lock:
            self.total_hook_executions += 1
            if not success:
                self.total_hook_failures += 1

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as a plain dictionary."""
        return {
            "llm_calls": self.total_llm_calls,
            "tool_calls": self.total_tool_calls,
            "governance_checks": self.total_governance_checks,
            "governance_denials": self.total_governance_denials,
            "compactions": self.total_compactions,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cost_usd": round(self.total_cost_usd, 4),
            "hook_executions": self.total_hook_executions,
            "hook_failures": self.total_hook_failures,
            "avg_governance_latency_ms": round(self.avg_governance_latency_ms, 2),
        }


# Global metrics instance
_metrics = HarnessMetrics()


def get_metrics() -> HarnessMetrics:
    """Get the global metrics instance."""
    return _metrics


def reset_metrics() -> None:
    """Reset the global metrics instance."""
    global _metrics
    _metrics = HarnessMetrics()
