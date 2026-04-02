"""OpenTelemetry tracing for AutoHarness.

Every harness operation produces trace spans following OpenTelemetry
semantic conventions for GenAI. Traces are sent to any OTel-compatible
backend (Jaeger, Datadog, Grafana, Honeycomb, etc).

Usage:
    from autoharness.observability import configure_tracing
    configure_tracing(service_name="my-agent", endpoint="http://localhost:4317")

    # All AgentLoop operations now produce traces automatically.

When no tracing is configured, all operations are no-ops (zero overhead).
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Try to import opentelemetry, gracefully degrade if not installed
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

# AutoHarness semantic conventions
HARNESS_AGENT_LOOP = "autoharness.agent_loop"
HARNESS_LLM_CALL = "autoharness.llm_call"
HARNESS_TOOL_EXECUTION = "autoharness.tool_execution"
HARNESS_GOVERNANCE_CHECK = "autoharness.governance_check"
HARNESS_HOOK_EXECUTION = "autoharness.hook_execution"
HARNESS_COMPACTION = "autoharness.compaction"
HARNESS_MICROCOMPACT = "autoharness.microcompact"
HARNESS_SKILL_LOAD = "autoharness.skill_load"

_tracer = None  # Will hold the real or no-op tracer


def configure_tracing(
    service_name: str = "autoharness",
    endpoint: str | None = None,
    console: bool = False,
) -> None:
    """Configure OpenTelemetry tracing.

    Parameters
    ----------
    service_name : str
        The service name reported in traces.
    endpoint : str or None
        OTLP gRPC endpoint (e.g., ``"http://localhost:4317"``).
        Requires ``opentelemetry-exporter-otlp`` to be installed.
    console : bool
        If True, also export spans to the console (useful for debugging).
    """
    global _tracer
    if not HAS_OTEL:
        logger.warning(
            "opentelemetry not installed. Run: pip install autoharness[observability]"
        )
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
        except ImportError:
            logger.warning(
                "OTLP exporter not installed. Run: pip install opentelemetry-exporter-otlp"
            )

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("autoharness")


def get_tracer() -> Any:
    """Get the configured tracer, or a no-op tracer.

    Returns an OpenTelemetry ``Tracer`` when OTel is installed and configured,
    or a :class:`NoOpTracer` that produces zero overhead otherwise.
    """
    global _tracer
    if _tracer is not None:
        return _tracer
    if HAS_OTEL:
        return trace.get_tracer("autoharness")
    return NoOpTracer()


class NoOpSpan:
    """No-op span for when OTel is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class NoOpTracer:
    """No-op tracer for when OTel is not installed."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[NoOpSpan]:
        yield NoOpSpan()

    @contextmanager
    def start_span(self, name: str, **kwargs: Any) -> Iterator[NoOpSpan]:
        yield NoOpSpan()


@contextmanager
def trace_agent_loop(task: str, model: str) -> Iterator[Any]:
    """Trace the entire agent loop execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(HARNESS_AGENT_LOOP) as span:
        span.set_attribute("autoharness.task", task[:200])
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("autoharness.version", "0.1.1")
        yield span


@contextmanager
def trace_llm_call(model: str, turn: int) -> Iterator[Any]:
    """Trace a single LLM call."""
    tracer = get_tracer()
    with tracer.start_as_current_span(HARNESS_LLM_CALL) as span:
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("autoharness.turn", turn)
        yield span


@contextmanager
def trace_tool_execution(tool_name: str, tool_id: str) -> Iterator[Any]:
    """Trace tool execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(HARNESS_TOOL_EXECUTION) as span:
        span.set_attribute("autoharness.tool.name", tool_name)
        span.set_attribute("autoharness.tool.id", tool_id)
        yield span


@contextmanager
def trace_governance_check(tool_name: str) -> Iterator[Any]:
    """Trace governance pipeline check."""
    tracer = get_tracer()
    with tracer.start_as_current_span(HARNESS_GOVERNANCE_CHECK) as span:
        span.set_attribute("autoharness.tool.name", tool_name)
        yield span


@contextmanager
def trace_compaction(compaction_type: str) -> Iterator[Any]:
    """Trace context compaction."""
    tracer = get_tracer()
    with tracer.start_as_current_span(HARNESS_COMPACTION) as span:
        span.set_attribute("autoharness.compaction.type", compaction_type)
        yield span
