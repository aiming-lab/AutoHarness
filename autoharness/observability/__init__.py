"""Observability subsystem for AutoHarness.

Provides OpenTelemetry tracing and lightweight metrics collection.
All functionality degrades gracefully when OpenTelemetry is not installed.

Usage:
    from autoharness.observability import configure_tracing, get_metrics

    # Optional: configure OTel tracing
    configure_tracing(service_name="my-agent", endpoint="http://localhost:4317")

    # Metrics are always available (no external deps)
    metrics = get_metrics()
    print(metrics.to_dict())
"""

from autoharness.observability.cost_attribution import (
    CostEntry,
    CostReport,
    CostTracker,
)
from autoharness.observability.metrics import (
    HarnessMetrics,
    get_metrics,
    reset_metrics,
)
from autoharness.observability.tracing import (
    configure_tracing,
    get_tracer,
    trace_agent_loop,
    trace_compaction,
    trace_governance_check,
    trace_llm_call,
    trace_tool_execution,
)

__all__ = [
    "CostEntry",
    "CostReport",
    "CostTracker",
    "HarnessMetrics",
    "configure_tracing",
    "get_metrics",
    "get_tracer",
    "reset_metrics",
    "trace_agent_loop",
    "trace_compaction",
    "trace_governance_check",
    "trace_llm_call",
    "trace_tool_execution",
]
