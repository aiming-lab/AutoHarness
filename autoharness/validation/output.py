"""Structured Output Validation — type-safe agent output contracts.

Ensures agent outputs conform to typed schemas. When validation fails,
automatically retries with the validation error as feedback.

Inspired by Pydantic AI's result_type pattern and Guardrails AI's
on-fail action taxonomy.

Usage:
    from pydantic import BaseModel
    from autoharness.validation import OutputValidator, OnFail

    class CodeReview(BaseModel):
        summary: str
        issues: list[str]
        approved: bool

    validator = OutputValidator(
        schema=CodeReview,
        max_retries=3,
        on_fail=OnFail.REASK,
    )

    # In agent loop:
    result = validator.validate(llm_output)
    if result.is_valid:
        typed_output: CodeReview = result.value
    else:
        retry_message = result.retry_prompt  # Send back to LLM
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class OnFail(str, Enum):
    """Action to take when output validation fails."""
    REASK = "reask"           # Send validation error back to LLM for retry
    FIX = "fix"               # Attempt automatic fix (e.g., JSON repair)
    FILTER = "filter"         # Remove invalid fields, keep valid ones
    ESCALATE = "escalate"     # Escalate to human / parent agent
    BLOCK = "block"           # Block the output entirely
    NOOP = "noop"             # Log but pass through


@dataclass
class ValidationResult(Generic[T]):
    """Result of output validation."""
    is_valid: bool
    value: T | None = None
    errors: list[str] = field(default_factory=list)
    raw_output: str = ""
    retry_prompt: str | None = None
    retries_used: int = 0


class OutputValidator(Generic[T]):
    """Validates and optionally retries LLM output against a typed schema.

    Supports Pydantic models, JSON schemas, and custom validator functions.
    """

    def __init__(
        self,
        schema: type[T] | None = None,
        json_schema: dict[str, Any] | None = None,
        custom_validators: list[Any] | None = None,
        max_retries: int = 3,
        on_fail: OnFail = OnFail.REASK,
    ) -> None:
        self.schema = schema
        self.json_schema = json_schema
        self.custom_validators = custom_validators or []
        self.max_retries = max_retries
        self.on_fail = on_fail

    def validate(self, output: str) -> ValidationResult[T]:
        """Validate LLM output against the schema."""
        errors: list[str] = []

        # Step 1: Extract JSON from output (handle markdown code blocks)
        json_str = self._extract_json(output)
        if json_str is None:
            errors.append("No valid JSON found in output")
            return self._make_failure(output, errors)

        # Step 2: Parse JSON
        data: Any = None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid JSON: {exc}")
            if self.on_fail == OnFail.FIX:
                fixed = self._attempt_json_fix(json_str)
                if fixed is not None:
                    data = fixed
                    errors.clear()
                else:
                    return self._make_failure(output, errors)
            else:
                return self._make_failure(output, errors)

        # Step 3: Validate against Pydantic schema
        if self.schema is not None:
            try:
                schema: Any = self.schema
                # Check if it's a Pydantic v2 model
                if hasattr(schema, 'model_validate'):
                    value = schema.model_validate(data)
                # Check if it's a Pydantic v1 model
                elif hasattr(schema, 'parse_obj'):
                    value = schema.parse_obj(data)
                else:
                    # Plain dataclass or similar — construct from dict
                    if isinstance(data, dict):
                        value = self.schema(**data)
                    else:
                        raise TypeError(
                            f"Cannot construct {self.schema.__name__} from {type(data).__name__}"
                        )
            except Exception as exc:
                errors.append(f"Schema validation failed: {exc}")
                return self._make_failure(output, errors)

            # Run custom validators on the parsed data
            custom_errors = self._run_custom_validators(data)
            if custom_errors:
                return self._make_failure(output, custom_errors)

            return ValidationResult(is_valid=True, value=value, raw_output=output)

        # Step 4: Run custom validators (no schema case)
        custom_errors = self._run_custom_validators(data)
        if custom_errors:
            return self._make_failure(output, custom_errors)

        return ValidationResult(is_valid=True, value=data, raw_output=output)

    def _run_custom_validators(self, data: Any) -> list[str]:
        """Run all custom validators and collect errors."""
        errors: list[str] = []
        for validator_fn in self.custom_validators:
            try:
                result = validator_fn(data)
                if result is not True and result is not None:
                    if isinstance(result, str):
                        errors.append(result)
                    else:
                        errors.append(f"Custom validator failed: {validator_fn.__name__}")
            except Exception as exc:
                errors.append(f"Validator {validator_fn.__name__} error: {exc}")
        return errors

    def _extract_json(self, text: str) -> str | None:
        """Extract JSON from LLM output, handling markdown code blocks."""
        # Try direct JSON parse first
        text_stripped = text.strip()
        if text_stripped.startswith('{') or text_stripped.startswith('['):
            return text_stripped

        # Look for ```json ... ``` blocks
        json_block = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
        if json_block:
            return json_block.group(1).strip()

        # Look for first { ... } or [ ... ]
        brace_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if brace_match:
            return brace_match.group(1)

        return None

    def _attempt_json_fix(self, json_str: str) -> Any | None:
        """Attempt basic JSON repair (trailing commas, single quotes, etc.)."""
        fixed = json_str
        # Remove trailing commas before } or ]
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        # Replace single quotes with double quotes (simple cases)
        fixed = re.sub(r"'([^']*)'", r'"\1"', fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None

    def _make_failure(self, raw_output: str, errors: list[str]) -> ValidationResult[T]:
        """Create a failure result with retry prompt."""
        retry_prompt = None
        if self.on_fail == OnFail.REASK:
            error_list = "\n".join(f"- {e}" for e in errors)
            retry_prompt = (
                "Your previous output did not match the required format.\n\n"
                f"Validation errors:\n{error_list}\n\n"
            )
            if self.schema and hasattr(self.schema, 'model_json_schema'):
                schema_any: Any = self.schema
                schema_str = json.dumps(schema_any.model_json_schema(), indent=2)
                retry_prompt += f"Required schema:\n```json\n{schema_str}\n```\n\n"
            retry_prompt += "Please try again with valid output matching the schema."

        return ValidationResult(
            is_valid=False,
            errors=errors,
            raw_output=raw_output,
            retry_prompt=retry_prompt,
        )


class ValidatedLoop:
    """A validation-aware wrapper around the agent loop.

    Automatically retries LLM calls when output doesn't match schema,
    sending validation errors as feedback.
    """

    def __init__(
        self,
        validator: OutputValidator[Any],
        max_retries: int | None = None,
    ) -> None:
        self.validator = validator
        self.max_retries = max_retries or validator.max_retries

    def run_with_validation(
        self,
        llm_callback: Any,
        messages: list[dict[str, Any]],
    ) -> ValidationResult[Any]:
        """Run LLM with automatic validation retry loop.

        Args:
            llm_callback: Function that takes messages and returns LLM output string
            messages: Initial messages to send

        Returns:
            ValidationResult with the validated output or final errors
        """
        current_messages = list(messages)
        result: ValidationResult[Any] | None = None

        for attempt in range(self.max_retries + 1):
            # Call LLM
            output = llm_callback(current_messages)

            # Validate
            result = self.validator.validate(output)
            result.retries_used = attempt

            if result.is_valid:
                return result

            # If we have retries left and on_fail is REASK, retry with feedback
            if attempt < self.max_retries and result.retry_prompt:
                current_messages.append({
                    "role": "assistant",
                    "content": output,
                })
                current_messages.append({
                    "role": "user",
                    "content": result.retry_prompt,
                })
                logger.info(
                    "Validation retry %d/%d: %s",
                    attempt + 1, self.max_retries,
                    "; ".join(result.errors),
                )
            else:
                return result

        # Should not reach here, but just in case
        assert result is not None
        return result
