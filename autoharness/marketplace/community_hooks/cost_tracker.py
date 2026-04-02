"""Track estimated API cost based on token usage.

Monitors tool calls for token usage metadata and maintains a running
cost estimate. When the estimated cost exceeds a configurable threshold,
the hook can warn or block further tool calls.

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()
    marketplace.install("cost-tracker")

Or register directly::

    from autoharness.core.hooks import HookRegistry
    from autoharness.marketplace.community_hooks.cost_tracker import track_cost

    registry = HookRegistry()
    registry.register("post_tool_use", track_cost)

Configuration via environment variables:
    AUTOHARNESS_COST_WARN_THRESHOLD: Warning threshold in USD (default: 5.0)
    AUTOHARNESS_COST_DENY_THRESHOLD: Deny threshold in USD (default: 20.0)
    AUTOHARNESS_COST_INPUT_RATE: Cost per 1M input tokens in USD (default: 3.0)
    AUTOHARNESS_COST_OUTPUT_RATE: Cost per 1M output tokens in USD (default: 15.0)
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from autoharness.core.hooks import hook
from autoharness.core.types import (
    HookAction,
    HookResult,
    RiskAssessment,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

HOOK_METADATA = {
    "name": "cost-tracker",
    "description": "Track estimated API cost based on token usage",
    "event": "post_tool_use",
    "author": "AutoHarness Community",
    "version": "1.0.0",
    "tags": ["cost", "monitoring", "budget"],
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _get_float_env(key: str, default: float) -> float:
    """Read a float from an environment variable with a fallback default."""
    raw = os.environ.get(key, "")
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning(
                "Invalid float value for %s: %r, using default %s",
                key, raw, default,
            )
    return default


# Cost thresholds (USD)
_WARN_THRESHOLD = _get_float_env("AUTOHARNESS_COST_WARN_THRESHOLD", 5.0)
_DENY_THRESHOLD = _get_float_env("AUTOHARNESS_COST_DENY_THRESHOLD", 20.0)

# Token pricing (per 1M tokens, USD) — defaults approximate Claude Sonnet pricing
_INPUT_RATE = _get_float_env("AUTOHARNESS_COST_INPUT_RATE", 3.0)
_OUTPUT_RATE = _get_float_env("AUTOHARNESS_COST_OUTPUT_RATE", 15.0)

# Per-million multiplier
_PER_MILLION = 1_000_000.0


# ---------------------------------------------------------------------------
# Cost accumulator (thread-safe)
# ---------------------------------------------------------------------------


class CostAccumulator:
    """Thread-safe accumulator for tracking API costs across a session.

    Attributes
    ----------
    total_input_tokens : int
        Total input tokens consumed.
    total_output_tokens : int
        Total output tokens consumed.
    total_cost_usd : float
        Estimated total cost in USD.
    call_count : int
        Number of tool calls tracked.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.call_count: int = 0

    def add(self, input_tokens: int = 0, output_tokens: int = 0) -> float:
        """Add token usage and return the updated total cost.

        Parameters
        ----------
        input_tokens : int
            Number of input tokens to add.
        output_tokens : int
            Number of output tokens to add.

        Returns
        -------
        float
            Updated total cost in USD.
        """
        input_cost = (input_tokens / _PER_MILLION) * _INPUT_RATE
        output_cost = (output_tokens / _PER_MILLION) * _OUTPUT_RATE
        increment = input_cost + output_cost

        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cost_usd += increment
            self.call_count += 1
            return self.total_cost_usd

    def get_summary(self) -> dict[str, Any]:
        """Return a snapshot of the current cost state."""
        with self._lock:
            return {
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_cost_usd": round(self.total_cost_usd, 6),
                "call_count": self.call_count,
                "warn_threshold_usd": _WARN_THRESHOLD,
                "deny_threshold_usd": _DENY_THRESHOLD,
            }

    def reset(self) -> None:
        """Reset all counters to zero."""
        with self._lock:
            self.total_input_tokens = 0
            self.total_output_tokens = 0
            self.total_cost_usd = 0.0
            self.call_count = 0


# Global accumulator instance (shared across hook invocations in a session)
_accumulator = CostAccumulator()


def get_cost_summary() -> dict[str, Any]:
    """Get the current cost tracking summary.

    Convenience function for inspecting cost state from outside the hook.

    Returns
    -------
    dict
        Cost summary including tokens, cost, and thresholds.
    """
    return _accumulator.get_summary()


def reset_cost_tracker() -> None:
    """Reset the cost tracker to zero.

    Useful at session boundaries or for testing.
    """
    _accumulator.reset()


# ---------------------------------------------------------------------------
# Hook implementations
# ---------------------------------------------------------------------------


def _extract_token_counts(
    tool_call: ToolCall, result: ToolResult
) -> tuple[int, int]:
    """Extract input and output token counts from tool call metadata.

    Looks for token usage information in:
    1. tool_call.metadata (e.g., ``{"input_tokens": N, "output_tokens": M}``)
    2. result.output if it's a dict with token fields
    3. Estimates from output string length if no explicit counts

    Returns
    -------
    tuple[int, int]
        (input_tokens, output_tokens)
    """
    input_tokens = 0
    output_tokens = 0

    # Check tool_call metadata
    meta = tool_call.metadata
    input_tokens = int(meta.get("input_tokens", 0))
    output_tokens = int(meta.get("output_tokens", 0))

    if input_tokens or output_tokens:
        return input_tokens, output_tokens

    # Check if the result output contains token info
    if isinstance(result.output, dict):
        usage = result.output.get("usage", result.output)
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
        output_tokens = int(
            usage.get("output_tokens", usage.get("completion_tokens", 0))
        )

    if input_tokens or output_tokens:
        return input_tokens, output_tokens

    # Rough estimate from output string length (4 chars ~= 1 token)
    if result.output is not None:
        output_str = str(result.output)
        output_tokens = max(1, len(output_str) // 4)

    # Rough estimate for input from tool_input
    input_str = str(tool_call.tool_input)
    input_tokens = max(1, len(input_str) // 4)

    return input_tokens, output_tokens


@hook("post_tool_use", name="cost_tracker")
def track_cost(
    tool_call: ToolCall,
    result: ToolResult,
    context: dict[str, Any],
) -> HookResult:
    """Track estimated API cost after each tool call.

    Extracts token usage from tool call metadata or estimates from
    output length. Accumulates cost and returns warnings or denials
    when thresholds are exceeded.

    Parameters
    ----------
    tool_call : ToolCall
        The completed tool call.
    result : ToolResult
        The tool execution result.
    context : dict
        Additional context (cost summary is added under ``"cost_tracker"``).

    Returns
    -------
    HookResult
        Allow with cost info, warn at threshold, or deny at hard limit.
    """
    input_tokens, output_tokens = _extract_token_counts(tool_call, result)
    total_cost = _accumulator.add(input_tokens, output_tokens)

    # Inject cost summary into context for other hooks / audit
    context["cost_tracker"] = _accumulator.get_summary()

    if total_cost >= _DENY_THRESHOLD:
        return HookResult(
            action=HookAction.deny,
            reason=(
                f"Cost limit exceeded: estimated ${total_cost:.4f} USD "
                f"(threshold: ${_DENY_THRESHOLD:.2f}). "
                f"Total tokens: {_accumulator.total_input_tokens} in / "
                f"{_accumulator.total_output_tokens} out over "
                f"{_accumulator.call_count} calls."
            ),
            severity="error",
        )

    if total_cost >= _WARN_THRESHOLD:
        return HookResult(
            action=HookAction.allow,
            reason=(
                f"Cost warning: estimated ${total_cost:.4f} USD "
                f"approaching limit (${_DENY_THRESHOLD:.2f}). "
                f"Total tokens: {_accumulator.total_input_tokens} in / "
                f"{_accumulator.total_output_tokens} out."
            ),
            severity="warning",
        )

    return HookResult(
        action=HookAction.allow,
        reason=f"Cost tracked: ${total_cost:.6f} USD ({_accumulator.call_count} calls)",
        severity="info",
    )


@hook("pre_tool_use", name="cost_budget_gate")
def cost_budget_gate(
    tool_call: ToolCall,
    risk: RiskAssessment,
    context: dict[str, Any],
) -> HookResult:
    """Pre-tool-use gate that blocks calls if the cost budget is exhausted.

    This is a companion to the post-hook ``track_cost``. It checks the
    accumulated cost *before* a new tool call is executed, preventing
    further spending once the deny threshold has been reached.

    Parameters
    ----------
    tool_call : ToolCall
        The incoming tool call.
    risk : RiskAssessment
        Pre-computed risk assessment.
    context : dict
        Additional context.

    Returns
    -------
    HookResult
        Deny if budget exhausted, allow otherwise.
    """
    summary = _accumulator.get_summary()
    total_cost = summary["total_cost_usd"]

    if total_cost >= _DENY_THRESHOLD:
        return HookResult(
            action=HookAction.deny,
            reason=(
                f"Cost budget exhausted: ${total_cost:.4f} USD spent "
                f"(limit: ${_DENY_THRESHOLD:.2f}). "
                f"Reset with reset_cost_tracker() or increase "
                f"AUTOHARNESS_COST_DENY_THRESHOLD."
            ),
            severity="error",
        )

    return HookResult(action=HookAction.allow)
