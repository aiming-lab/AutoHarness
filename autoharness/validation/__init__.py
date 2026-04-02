"""Structured Output Validation — type-safe agent output contracts.

Ensures agent outputs conform to typed schemas. When validation fails,
automatically retries with the validation error as feedback.

Inspired by Pydantic AI's result_type pattern and Guardrails AI's
on-fail action taxonomy.
"""

from autoharness.validation.output import (
    OnFail,
    OutputValidator,
    ValidatedLoop,
    ValidationResult,
)
from autoharness.validation.rails import (
    ContentLengthRail,
    PIIRedactionRail,
    PromptInjectionRail,
    Rail,
    RailResult,
    TopicGuardRail,
    ValidationPipeline,
)

__all__ = [
    # Rails pipeline
    "ContentLengthRail",
    # Output validation
    "OnFail",
    "OutputValidator",
    "PIIRedactionRail",
    "PromptInjectionRail",
    "Rail",
    "RailResult",
    "TopicGuardRail",
    "ValidatedLoop",
    "ValidationPipeline",
    "ValidationResult",
]
