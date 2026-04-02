"""Tests for the observability subsystem (tracing + metrics).

Covers NoOp patterns, context managers, metrics recording,
thread safety, and module-level accessors.
"""
from __future__ import annotations

import threading

import pytest

from autoharness.observability.metrics import (
    HarnessMetrics,
    get_metrics,
    reset_metrics,
)
from autoharness.observability.tracing import (
    HARNESS_AGENT_LOOP,
    HARNESS_COMPACTION,
    HARNESS_GOVERNANCE_CHECK,
    HARNESS_LLM_CALL,
    HARNESS_TOOL_EXECUTION,
    NoOpSpan,
    NoOpTracer,
    get_tracer,
    trace_agent_loop,
    trace_compaction,
    trace_governance_check,
    trace_llm_call,
    trace_tool_execution,
)

# ---------------------------------------------------------------------------
# NoOpTracer / NoOpSpan tests
# ---------------------------------------------------------------------------


class TestNoOpSpan:
    """NoOpSpan should accept all operations silently."""

    def test_set_attribute(self):
        span = NoOpSpan()
        span.set_attribute("key", "value")  # should not raise

    def test_set_status(self):
        span = NoOpSpan()
        span.set_status("OK")

    def test_record_exception(self):
        span = NoOpSpan()
        span.record_exception(RuntimeError("boom"))

    def test_add_event(self):
        span = NoOpSpan()
        span.add_event("test_event", {"key": "val"})

    def test_end(self):
        span = NoOpSpan()
        span.end()

    def test_context_manager(self):
        span = NoOpSpan()
        with span as s:
            assert s is span


class TestNoOpTracer:
    """NoOpTracer should produce NoOpSpan instances."""

    def test_start_as_current_span(self):
        tracer = NoOpTracer()
        with tracer.start_as_current_span("test") as span:
            assert isinstance(span, NoOpSpan)
            span.set_attribute("foo", "bar")

    def test_start_span(self):
        tracer = NoOpTracer()
        with tracer.start_span("test") as span:
            assert isinstance(span, NoOpSpan)


class TestGetTracer:
    """get_tracer() returns a usable tracer regardless of OTel availability."""

    def test_returns_tracer_without_otel(self):
        """When OTel is not configured, should return something usable."""
        tracer = get_tracer()
        # Should be usable as a context manager
        with tracer.start_as_current_span("test") as span:
            span.set_attribute("key", "value")


# ---------------------------------------------------------------------------
# Trace context manager tests
# ---------------------------------------------------------------------------


class TestTraceAgentLoop:
    """trace_agent_loop context manager."""

    def test_yields_span(self):
        with trace_agent_loop("do something", "claude-sonnet-4-6") as span:
            assert span is not None

    def test_truncates_long_task(self):
        long_task = "x" * 500
        with trace_agent_loop(long_task, "claude-sonnet-4-6") as span:
            # Should not raise even with a very long task
            span.set_attribute("extra", "attr")


class TestTraceLLMCall:
    """trace_llm_call context manager."""

    def test_yields_span(self):
        with trace_llm_call("claude-sonnet-4-6", turn=3) as span:
            assert span is not None

    def test_span_accepts_attributes(self):
        with trace_llm_call("claude-sonnet-4-6", turn=0) as span:
            span.set_attribute("extra_key", 42)


class TestTraceToolExecution:
    """trace_tool_execution context manager."""

    def test_yields_span(self):
        with trace_tool_execution("Bash", "tool_123") as span:
            assert span is not None

    def test_span_attributes(self):
        with trace_tool_execution("Read", "tool_456") as span:
            span.add_event("file_read", {"path": "/tmp/test"})


class TestTraceGovernanceCheck:
    """trace_governance_check context manager."""

    def test_yields_span(self):
        with trace_governance_check("Bash") as span:
            assert span is not None

    def test_exception_in_body(self):
        """Exceptions should propagate normally through the context manager."""
        with pytest.raises(ValueError, match="test error"), trace_governance_check("Bash"):
            raise ValueError("test error")


class TestTraceCompaction:
    """trace_compaction context manager."""

    def test_yields_span(self):
        with trace_compaction("auto") as span:
            assert span is not None

    def test_micro_compaction_type(self):
        with trace_compaction("micro") as span:
            span.set_attribute("autoharness.tokens.before", 50000)
            span.set_attribute("autoharness.tokens.after", 30000)


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestHarnessMetrics:
    """HarnessMetrics dataclass methods."""

    def test_record_llm_call(self):
        m = HarnessMetrics()
        m.record_llm_call(input_tokens=100, output_tokens=50)
        assert m.total_llm_calls == 1
        assert m.total_input_tokens == 100
        assert m.total_output_tokens == 50

    def test_record_llm_call_accumulates(self):
        m = HarnessMetrics()
        m.record_llm_call(input_tokens=100, output_tokens=50)
        m.record_llm_call(input_tokens=200, output_tokens=75)
        assert m.total_llm_calls == 2
        assert m.total_input_tokens == 300
        assert m.total_output_tokens == 125

    def test_record_tool_call(self):
        m = HarnessMetrics()
        m.record_tool_call()
        m.record_tool_call()
        assert m.total_tool_calls == 2

    def test_record_governance_check_allowed(self):
        m = HarnessMetrics()
        m.record_governance_check(allowed=True, latency_ms=1.5)
        assert m.total_governance_checks == 1
        assert m.total_governance_denials == 0
        assert m.avg_governance_latency_ms == 1.5

    def test_record_governance_check_denied(self):
        m = HarnessMetrics()
        m.record_governance_check(allowed=False, latency_ms=2.0)
        assert m.total_governance_checks == 1
        assert m.total_governance_denials == 1

    def test_avg_governance_latency_calculation(self):
        m = HarnessMetrics()
        m.record_governance_check(allowed=True, latency_ms=1.0)
        m.record_governance_check(allowed=True, latency_ms=3.0)
        m.record_governance_check(allowed=True, latency_ms=5.0)
        assert m.avg_governance_latency_ms == pytest.approx(3.0)

    def test_record_compaction(self):
        m = HarnessMetrics()
        m.record_compaction()
        m.record_compaction()
        assert m.total_compactions == 2

    def test_record_hook_success(self):
        m = HarnessMetrics()
        m.record_hook(success=True)
        assert m.total_hook_executions == 1
        assert m.total_hook_failures == 0

    def test_record_hook_failure(self):
        m = HarnessMetrics()
        m.record_hook(success=False)
        assert m.total_hook_executions == 1
        assert m.total_hook_failures == 1

    def test_to_dict(self):
        m = HarnessMetrics()
        m.record_llm_call(input_tokens=500, output_tokens=100)
        m.record_tool_call()
        m.record_governance_check(allowed=True, latency_ms=2.5)
        m.record_compaction()
        m.record_hook(success=True)
        m.total_cost_usd = 0.12345

        d = m.to_dict()
        assert d["llm_calls"] == 1
        assert d["tool_calls"] == 1
        assert d["governance_checks"] == 1
        assert d["governance_denials"] == 0
        assert d["compactions"] == 1
        assert d["input_tokens"] == 500
        assert d["output_tokens"] == 100
        assert d["cost_usd"] == 0.1235
        assert d["hook_executions"] == 1
        assert d["hook_failures"] == 0
        assert d["avg_governance_latency_ms"] == 2.5

    def test_to_dict_empty(self):
        m = HarnessMetrics()
        d = m.to_dict()
        assert d["llm_calls"] == 0
        assert d["cost_usd"] == 0.0
        assert d["avg_governance_latency_ms"] == 0.0


class TestGlobalMetrics:
    """Module-level get_metrics / reset_metrics."""

    def test_get_metrics_returns_instance(self):
        m = get_metrics()
        assert isinstance(m, HarnessMetrics)

    def test_reset_metrics(self):
        m = get_metrics()
        m.record_llm_call(input_tokens=100, output_tokens=50)
        assert m.total_llm_calls >= 1

        reset_metrics()
        m2 = get_metrics()
        assert m2.total_llm_calls == 0
        assert m2 is not m

    def test_get_metrics_returns_same_instance(self):
        reset_metrics()
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


class TestThreadSafety:
    """Metrics must be safe to record from multiple threads."""

    def test_concurrent_llm_calls(self):
        m = HarnessMetrics()
        num_threads = 10
        calls_per_thread = 100

        def record_calls():
            for _ in range(calls_per_thread):
                m.record_llm_call(input_tokens=1, output_tokens=1)

        threads = [threading.Thread(target=record_calls) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert m.total_llm_calls == num_threads * calls_per_thread
        assert m.total_input_tokens == num_threads * calls_per_thread
        assert m.total_output_tokens == num_threads * calls_per_thread

    def test_concurrent_mixed_operations(self):
        m = HarnessMetrics()
        num_threads = 8
        ops_per_thread = 50

        def mixed_ops():
            for i in range(ops_per_thread):
                m.record_llm_call(input_tokens=10, output_tokens=5)
                m.record_tool_call()
                m.record_governance_check(allowed=(i % 2 == 0), latency_ms=1.0)
                m.record_hook(success=True)

        threads = [threading.Thread(target=mixed_ops) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = num_threads * ops_per_thread
        assert m.total_llm_calls == total
        assert m.total_tool_calls == total
        assert m.total_governance_checks == total
        assert m.total_hook_executions == total
        # Half are denied (i % 2 != 0)
        assert m.total_governance_denials == total // 2


# ---------------------------------------------------------------------------
# Semantic convention constants
# ---------------------------------------------------------------------------


class TestSemanticConventions:
    """Verify semantic convention string constants are defined."""

    def test_constants_defined(self):
        assert HARNESS_AGENT_LOOP == "autoharness.agent_loop"
        assert HARNESS_LLM_CALL == "autoharness.llm_call"
        assert HARNESS_TOOL_EXECUTION == "autoharness.tool_execution"
        assert HARNESS_GOVERNANCE_CHECK == "autoharness.governance_check"
        assert HARNESS_COMPACTION == "autoharness.compaction"
