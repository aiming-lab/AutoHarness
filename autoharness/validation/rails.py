"""Layered validation pipeline — input, execution, and output rails.

Implements the three-stage validation pattern inspired by Guardrails AI
and NeMo Guardrails, adapted for the harness engineering context.

Input rails validate/transform user input before it reaches the LLM.
Execution rails validate tool calls during execution (handled by the
governance pipeline in :mod:`autoharness.core.pipeline`).
Output rails validate/transform LLM output before returning to the user.

Usage::

    pipeline = ValidationPipeline()

    @pipeline.input_rail
    def block_prompt_injection(text: str) -> RailResult:
        if "ignore previous instructions" in text.lower():
            return RailResult.block("Potential prompt injection detected")
        return RailResult.pass_through()

    @pipeline.output_rail
    def redact_pii(text: str) -> RailResult:
        # Redact emails, phone numbers, SSNs
        cleaned = redact_patterns(text)
        return RailResult.transform(cleaned)

    # Validate user input
    result = pipeline.validate_input("Tell me about the project")
    if result.action == "block":
        raise ValueError(result.reason)

    # Validate LLM output
    result = pipeline.validate_output(llm_response)
    final_text = result.content if result.content else llm_response
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RailResult — the outcome of a single rail evaluation
# ---------------------------------------------------------------------------


@dataclass
class RailResult:
    """Result of a single rail evaluation.

    Attributes
    ----------
    action : str
        One of ``"pass"``, ``"block"``, ``"transform"``, or ``"warn"``.
    content : str or None
        Transformed content when ``action`` is ``"transform"``.
    reason : str or None
        Human-readable explanation for ``"block"`` or ``"warn"`` actions.
    rail_name : str
        Name of the rail that produced this result.
    """

    action: Literal["pass", "block", "transform", "warn"]
    content: str | None = None
    reason: str | None = None
    rail_name: str = ""

    # -- Convenience constructors ------------------------------------------

    @classmethod
    def pass_through(cls, *, rail_name: str = "") -> RailResult:
        """Content passed validation unchanged."""
        return cls(action="pass", rail_name=rail_name)

    @classmethod
    def block(cls, reason: str, *, rail_name: str = "") -> RailResult:
        """Content is blocked — must not proceed."""
        return cls(action="block", reason=reason, rail_name=rail_name)

    @classmethod
    def transform(cls, content: str, *, rail_name: str = "") -> RailResult:
        """Content was rewritten and should replace the original."""
        return cls(action="transform", content=content, rail_name=rail_name)

    @classmethod
    def warn(cls, reason: str, *, rail_name: str = "") -> RailResult:
        """Content is suspicious but allowed through with a warning."""
        return cls(action="warn", reason=reason, rail_name=rail_name)


# ---------------------------------------------------------------------------
# Rail protocol — what every rail must satisfy
# ---------------------------------------------------------------------------


@runtime_checkable
class Rail(Protocol):
    """Protocol that every rail must satisfy.

    Rails are callable objects with a ``name`` and a ``stage``.
    """

    name: str
    stage: Literal["input", "execution", "output"]

    def __call__(
        self, content: str, context: dict[str, Any] | None = None
    ) -> RailResult: ...


# ---------------------------------------------------------------------------
# ValidationPipeline — orchestrates input and output rails
# ---------------------------------------------------------------------------


class ValidationPipeline:
    """Three-stage validation pipeline for agent I/O.

    Manages collections of input and output rails.  Rails are executed
    in registration order.  The first ``"block"`` result short-circuits
    the pipeline; ``"transform"`` results are chained (each subsequent
    rail sees the transformed text).

    Parameters
    ----------
    fail_open : bool
        If *True*, exceptions raised by individual rails are logged but
        do not block the pipeline.  Defaults to *False* (fail-closed).
    """

    def __init__(self, *, fail_open: bool = False) -> None:
        self._input_rails: list[Rail] = []
        self._output_rails: list[Rail] = []
        self._fail_open = fail_open

    # -- Registration helpers -----------------------------------------------

    def add_rail(self, rail: Rail, stage: str | None = None) -> None:
        """Register a rail instance.

        Parameters
        ----------
        rail : Rail
            A rail object satisfying the :class:`Rail` protocol.
        stage : str, optional
            Override the rail's own ``stage`` attribute.  Must be one of
            ``"input"`` or ``"output"``.  If not provided, ``rail.stage``
            is used.
        """
        effective_stage = stage or rail.stage
        if effective_stage == "input":
            self._input_rails.append(rail)
        elif effective_stage == "output":
            self._output_rails.append(rail)
        else:
            raise ValueError(
                f"Unsupported stage {effective_stage!r}; use 'input' or 'output'"
            )

    def input_rail(self, fn: Callable[..., RailResult]) -> Callable[..., RailResult]:
        """Decorator that registers a function as an input rail.

        The decorated function must accept ``(text: str)`` or
        ``(text: str, context: dict)`` and return a :class:`RailResult`.

        Example::

            @pipeline.input_rail
            def no_profanity(text: str) -> RailResult:
                if has_profanity(text):
                    return RailResult.block("Profanity detected")
                return RailResult.pass_through()
        """
        rail = _FunctionRail(fn=fn, stage="input")
        self._input_rails.append(rail)
        return fn

    def output_rail(self, fn: Callable[..., RailResult]) -> Callable[..., RailResult]:
        """Decorator that registers a function as an output rail.

        Same signature requirements as :meth:`input_rail`.
        """
        rail = _FunctionRail(fn=fn, stage="output")
        self._output_rails.append(rail)
        return fn

    # -- Validation entry points --------------------------------------------

    def validate_input(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> RailResult:
        """Run all input rails against *text*.

        Returns
        -------
        RailResult
            Aggregate result.  ``action`` is ``"block"`` if any rail
            blocked; ``"transform"`` if any rail transformed (with the
            final ``content``); ``"warn"`` if any rail warned (but none
            blocked); otherwise ``"pass"``.
        """
        return self._run_stage(self._input_rails, text, context)

    def validate_output(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> RailResult:
        """Run all output rails against *text*.

        Same semantics as :meth:`validate_input` but for the output
        stage.
        """
        return self._run_stage(self._output_rails, text, context)

    # -- Internal -----------------------------------------------------------

    def _run_stage(
        self,
        rails: list[Rail],
        text: str,
        context: dict[str, Any] | None,
    ) -> RailResult:
        """Execute a list of rails in order.

        * First ``"block"`` wins — immediately returned.
        * ``"transform"`` results chain — each subsequent rail sees the
          transformed content.
        * ``"warn"`` results are accumulated; the last warning reason is
          reported.
        """
        current_text = text
        warnings: list[str] = []
        transformed = False

        for rail in rails:
            try:
                result = rail(current_text, context)
            except Exception:
                logger.exception("Rail %r raised an exception", getattr(rail, "name", rail))
                if not self._fail_open:
                    return RailResult.block(
                        f"Rail {getattr(rail, 'name', '?')!r} raised an exception (fail-closed)",
                        rail_name=getattr(rail, "name", ""),
                    )
                continue

            # Stamp the rail name if not already set
            if not result.rail_name:
                result.rail_name = getattr(rail, "name", "")

            if result.action == "block":
                logger.info(
                    "Rail %r blocked content: %s", result.rail_name, result.reason
                )
                return result

            if result.action == "transform" and result.content is not None:
                current_text = result.content
                transformed = True

            if result.action == "warn" and result.reason:
                warnings.append(result.reason)
                logger.warning(
                    "Rail %r warning: %s", result.rail_name, result.reason
                )

        # Build aggregate result
        if transformed:
            return RailResult(
                action="transform",
                content=current_text,
                rail_name="pipeline",
            )
        if warnings:
            return RailResult(
                action="warn",
                reason="; ".join(warnings),
                rail_name="pipeline",
            )
        return RailResult.pass_through(rail_name="pipeline")

    @property
    def input_rails(self) -> list[Rail]:
        """Registered input rails (read-only snapshot)."""
        return list(self._input_rails)

    @property
    def output_rails(self) -> list[Rail]:
        """Registered output rails (read-only snapshot)."""
        return list(self._output_rails)

    def __repr__(self) -> str:
        return (
            f"<ValidationPipeline input_rails={len(self._input_rails)} "
            f"output_rails={len(self._output_rails)}>"
        )


# ---------------------------------------------------------------------------
# _FunctionRail — adapter that wraps a plain function as a Rail
# ---------------------------------------------------------------------------


class _FunctionRail:
    """Wraps a plain function so it satisfies the :class:`Rail` protocol."""

    def __init__(
        self,
        fn: Callable[..., RailResult],
        stage: Literal["input", "output"],
    ) -> None:
        self.fn = fn
        self.name: str = fn.__name__
        self.stage: Literal["input", "execution", "output"] = stage

    def __call__(
        self, content: str, context: dict[str, Any] | None = None
    ) -> RailResult:
        import inspect

        sig = inspect.signature(self.fn)
        if len(sig.parameters) >= 2:
            return self.fn(content, context)
        return self.fn(content)


# ---------------------------------------------------------------------------
# Built-in Rails
# ---------------------------------------------------------------------------


class PromptInjectionRail:
    """Detects common prompt injection patterns in user input.

    Scans for phrases commonly used in prompt injection attacks such as
    "ignore previous instructions", "you are now", "system prompt", etc.

    Parameters
    ----------
    extra_patterns : list of str, optional
        Additional regex patterns to flag as injection attempts.
    """

    name: str = "prompt_injection"
    stage: Literal["input", "execution", "output"] = "input"

    # Patterns that strongly suggest prompt injection
    _DEFAULT_PATTERNS: ClassVar[list[str]] = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?above\s+instructions",
        r"disregard\s+(all\s+)?previous",
        r"you\s+are\s+now\b",
        r"forget\s+(everything|all)\s+",
        r"new\s+instructions?\s*:",
        r"system\s*prompt\s*:",
        r"override\s+(your|the)\s+instructions",
        r"\bdo\s+not\s+follow\s+(your|the)\s+(original|previous)\b",
        r"pretend\s+you\s+are\b",
        r"act\s+as\s+if\s+you\s+(are|were)\b",
        r"\b(ADMIN|ROOT)\s*MODE\b",
        r"jailbreak",
        # SYSTEM OVERRIDE / SYSTEM: directive patterns
        r"(?i)^SYSTEM\s*(?:OVERRIDE)?\s*:",
        r"(?i)\bSYSTEM\s+OVERRIDE\b",
        # ChatML / special token injection
        r"<\|im_(start|end)\|>",
        r"<\|endoftext\|>",
        r"\[INST\]|\[/INST\]",
        r"(?<![a-zA-Z])</s>(?![a-zA-Z>])|(?<![a-zA-Z/])<s>(?![a-zA-Z>])",
    ]

    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        patterns = self._DEFAULT_PATTERNS.copy()
        if extra_patterns:
            patterns.extend(extra_patterns)
        self._compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def __call__(
        self, content: str, context: dict[str, Any] | None = None
    ) -> RailResult:
        for pattern in self._compiled:
            match = pattern.search(content)
            if match:
                return RailResult.block(
                    f"Potential prompt injection detected: {match.group()!r}",
                    rail_name=self.name,
                )
        return RailResult.pass_through(rail_name=self.name)


class PIIRedactionRail:
    """Regex-based PII detection and redaction.

    Detects email addresses, US phone numbers, and US Social Security
    Numbers, replacing them with redaction tokens.

    Parameters
    ----------
    stage : str
        Which pipeline stage this rail runs in (default ``"output"``).
    """

    name: str = "pii_redaction"

    _EMAIL_RE = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    )
    _PHONE_RE = re.compile(
        r"(?<!\d)"  # not preceded by digit
        r"(?:\+?1[\s.-]?)?"
        r"(?:\(?\d{3}\)?[\s.-]?)"
        r"\d{3}[\s.-]?\d{4}"
        r"(?!\d)"  # not followed by digit
    )
    _SSN_RE = re.compile(
        r"\b\d{3}[\s-]?\d{2}[\s-]?\d{4}\b"
    )

    def __init__(
        self,
        stage: Literal["input", "output"] = "output",
    ) -> None:
        self.stage: Literal["input", "execution", "output"] = stage

    def __call__(
        self, content: str, context: dict[str, Any] | None = None
    ) -> RailResult:
        redacted = content
        changed = False

        redacted, n = self._SSN_RE.subn("[SSN REDACTED]", redacted)
        if n:
            changed = True
        redacted, n = self._EMAIL_RE.subn("[EMAIL REDACTED]", redacted)
        if n:
            changed = True
        redacted, n = self._PHONE_RE.subn("[PHONE REDACTED]", redacted)
        if n:
            changed = True

        if changed:
            return RailResult.transform(redacted, rail_name=self.name)
        return RailResult.pass_through(rail_name=self.name)


class ContentLengthRail:
    """Blocks content that exceeds a configured character limit.

    Parameters
    ----------
    max_length : int
        Maximum allowed character count (default 100_000).
    stage : str
        Pipeline stage (default ``"input"``).
    """

    name: str = "content_length"

    def __init__(
        self,
        max_length: int = 100_000,
        stage: Literal["input", "output"] = "input",
    ) -> None:
        self.max_length = max_length
        self.stage: Literal["input", "execution", "output"] = stage

    def __call__(
        self, content: str, context: dict[str, Any] | None = None
    ) -> RailResult:
        if len(content) > self.max_length:
            return RailResult.block(
                f"Content length {len(content)} exceeds limit of {self.max_length}",
                rail_name=self.name,
            )
        return RailResult.pass_through(rail_name=self.name)


class TopicGuardRail:
    """Keyword-based topic restriction.

    Blocks or warns when content touches restricted topics.  Topics are
    specified as regex patterns.

    Parameters
    ----------
    blocked_topics : dict mapping topic name to regex pattern
        Topics that should be blocked outright.
    warned_topics : dict mapping topic name to regex pattern
        Topics that should produce a warning but still pass through.
    stage : str
        Pipeline stage (default ``"input"``).
    """

    name: str = "topic_guard"

    def __init__(
        self,
        blocked_topics: dict[str, str] | None = None,
        warned_topics: dict[str, str] | None = None,
        stage: Literal["input", "output"] = "input",
    ) -> None:
        self.stage: Literal["input", "execution", "output"] = stage
        self._blocked: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern, re.IGNORECASE))
            for name, pattern in (blocked_topics or {}).items()
        ]
        self._warned: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern, re.IGNORECASE))
            for name, pattern in (warned_topics or {}).items()
        ]

    def __call__(
        self, content: str, context: dict[str, Any] | None = None
    ) -> RailResult:
        for topic_name, pattern in self._blocked:
            if pattern.search(content):
                return RailResult.block(
                    f"Restricted topic detected: {topic_name}",
                    rail_name=self.name,
                )

        for topic_name, pattern in self._warned:
            if pattern.search(content):
                return RailResult.warn(
                    f"Sensitive topic detected: {topic_name}",
                    rail_name=self.name,
                )

        return RailResult.pass_through(rail_name=self.name)
