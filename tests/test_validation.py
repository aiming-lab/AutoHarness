"""Tests for Structured Output Validation system.

Covers OnFail enum, ValidationResult, OutputValidator (with Pydantic models,
JSON extraction, custom validators, JSON repair), and ValidatedLoop retry logic.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from autoharness.validation import OnFail, OutputValidator, ValidatedLoop, ValidationResult

# ---------------------------------------------------------------------------
# Test Pydantic models
# ---------------------------------------------------------------------------

class CodeReview(BaseModel):
    summary: str
    issues: list[str]
    approved: bool


class UserProfile(BaseModel):
    name: str
    age: int = Field(ge=0)
    email: str | None = None


class NestedModel(BaseModel):
    title: str
    metadata: dict[str, str]


# ---------------------------------------------------------------------------
# 1. OnFail enum values
# ---------------------------------------------------------------------------

class TestOnFailEnum:
    def test_all_values_exist(self):
        assert OnFail.REASK == "reask"
        assert OnFail.FIX == "fix"
        assert OnFail.FILTER == "filter"
        assert OnFail.ESCALATE == "escalate"
        assert OnFail.BLOCK == "block"
        assert OnFail.NOOP == "noop"

    def test_is_string_enum(self):
        assert isinstance(OnFail.REASK, str)

    def test_member_count(self):
        assert len(OnFail) == 6


# ---------------------------------------------------------------------------
# 2. ValidationResult creation
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_valid_result(self):
        result = ValidationResult(is_valid=True, value={"key": "val"})
        assert result.is_valid is True
        assert result.value == {"key": "val"}
        assert result.errors == []
        assert result.retry_prompt is None

    def test_invalid_result(self):
        result = ValidationResult(
            is_valid=False,
            errors=["missing field 'name'"],
            raw_output="bad output",
            retry_prompt="Please fix",
        )
        assert result.is_valid is False
        assert result.value is None
        assert len(result.errors) == 1
        assert result.retry_prompt == "Please fix"

    def test_retries_used_default(self):
        result = ValidationResult(is_valid=True)
        assert result.retries_used == 0


# ---------------------------------------------------------------------------
# 3. OutputValidator — no schema (pass-through)
# ---------------------------------------------------------------------------

class TestOutputValidatorNoSchema:
    def test_valid_json_passthrough(self):
        v = OutputValidator()
        result = v.validate('{"hello": "world"}')
        assert result.is_valid is True
        assert result.value == {"hello": "world"}

    def test_array_passthrough(self):
        v = OutputValidator()
        result = v.validate('[1, 2, 3]')
        assert result.is_valid is True
        assert result.value == [1, 2, 3]


# ---------------------------------------------------------------------------
# 4. OutputValidator — Pydantic model validation
# ---------------------------------------------------------------------------

class TestOutputValidatorPydantic:
    def test_valid_pydantic_output(self):
        v = OutputValidator(schema=CodeReview)
        data = {"summary": "Looks good", "issues": [], "approved": True}
        result = v.validate(json.dumps(data))
        assert result.is_valid is True
        assert isinstance(result.value, CodeReview)
        assert result.value.summary == "Looks good"
        assert result.value.approved is True

    def test_invalid_pydantic_output_missing_field(self):
        v = OutputValidator(schema=CodeReview)
        data = {"summary": "Looks good"}  # missing issues and approved
        result = v.validate(json.dumps(data))
        assert result.is_valid is False
        assert any("validation failed" in e.lower() or "Schema" in e for e in result.errors)

    def test_invalid_pydantic_output_wrong_type(self):
        v = OutputValidator(schema=UserProfile)
        data = {"name": "Alice", "age": -5}  # age < 0
        result = v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_pydantic_optional_fields(self):
        v = OutputValidator(schema=UserProfile)
        data = {"name": "Alice", "age": 30}  # email is optional
        result = v.validate(json.dumps(data))
        assert result.is_valid is True
        assert result.value.email is None

    def test_pydantic_optional_fields_provided(self):
        v = OutputValidator(schema=UserProfile)
        data = {"name": "Alice", "age": 30, "email": "alice@example.com"}
        result = v.validate(json.dumps(data))
        assert result.is_valid is True
        assert result.value.email == "alice@example.com"


# ---------------------------------------------------------------------------
# 5. JSON extraction
# ---------------------------------------------------------------------------

class TestJSONExtraction:
    def test_extract_from_plain_json(self):
        v = OutputValidator()
        result = v.validate('{"a": 1}')
        assert result.is_valid is True
        assert result.value == {"a": 1}

    def test_extract_from_markdown_code_block(self):
        v = OutputValidator()
        text = 'Here is the result:\n```\n{"a": 1}\n```\nDone.'
        result = v.validate(text)
        assert result.is_valid is True
        assert result.value == {"a": 1}

    def test_extract_from_json_code_block(self):
        v = OutputValidator()
        text = 'Result:\n```json\n{"key": "value"}\n```\nEnd.'
        result = v.validate(text)
        assert result.is_valid is True
        assert result.value == {"key": "value"}

    def test_extract_json_from_surrounding_text(self):
        v = OutputValidator()
        text = 'The answer is {"x": 42} as expected.'
        result = v.validate(text)
        assert result.is_valid is True
        assert result.value == {"x": 42}

    def test_no_json_found(self):
        v = OutputValidator()
        result = v.validate("This has no JSON at all")
        assert result.is_valid is False
        assert "No valid JSON found" in result.errors[0]

    def test_nested_json_extraction(self):
        v = OutputValidator(schema=NestedModel)
        data = {"title": "Test", "metadata": {"k1": "v1", "k2": "v2"}}
        result = v.validate(json.dumps(data))
        assert result.is_valid is True
        assert result.value.metadata == {"k1": "v1", "k2": "v2"}

    def test_array_json_extraction(self):
        v = OutputValidator()
        text = 'Results: [{"id": 1}, {"id": 2}]'
        result = v.validate(text)
        assert result.is_valid is True
        assert len(result.value) == 2


# ---------------------------------------------------------------------------
# 6. JSON repair (OnFail.FIX)
# ---------------------------------------------------------------------------

class TestJSONRepair:
    def test_trailing_comma_fix(self):
        v = OutputValidator(on_fail=OnFail.FIX)
        broken = '{"a": 1, "b": 2,}'
        result = v.validate(broken)
        assert result.is_valid is True
        assert result.value == {"a": 1, "b": 2}

    def test_single_quote_fix(self):
        v = OutputValidator(on_fail=OnFail.FIX)
        broken = "{'a': 'hello', 'b': 'world'}"
        result = v.validate(broken)
        assert result.is_valid is True
        assert result.value == {"a": "hello", "b": "world"}

    def test_unfixable_json(self):
        v = OutputValidator(on_fail=OnFail.FIX)
        result = v.validate("{totally broken json {{{}}")
        assert result.is_valid is False


# ---------------------------------------------------------------------------
# 7. Custom validators
# ---------------------------------------------------------------------------

class TestCustomValidators:
    def test_custom_validator_pass(self):
        def check_has_name(data):
            if "name" not in data:
                return "Missing 'name' field"
            return True

        v = OutputValidator(custom_validators=[check_has_name])
        result = v.validate('{"name": "Alice"}')
        assert result.is_valid is True

    def test_custom_validator_fail(self):
        def check_has_name(data):
            if "name" not in data:
                return "Missing 'name' field"
            return True

        v = OutputValidator(custom_validators=[check_has_name])
        result = v.validate('{"age": 30}')
        assert result.is_valid is False
        assert "Missing 'name' field" in result.errors[0]

    def test_multiple_custom_validators(self):
        def check_name(data):
            if "name" not in data:
                return "Missing name"
            return True

        def check_age(data):
            if "age" not in data:
                return "Missing age"
            return True

        v = OutputValidator(custom_validators=[check_name, check_age])
        result = v.validate('{"foo": "bar"}')
        assert result.is_valid is False
        assert len(result.errors) == 2

    def test_custom_validator_exception(self):
        def bad_validator(data):
            raise ValueError("boom")

        v = OutputValidator(custom_validators=[bad_validator])
        result = v.validate('{"a": 1}')
        assert result.is_valid is False
        assert "boom" in result.errors[0]


# ---------------------------------------------------------------------------
# 8. Retry prompt generation
# ---------------------------------------------------------------------------

class TestRetryPrompt:
    def test_reask_generates_retry_prompt_with_errors(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK)
        result = v.validate("not json at all")
        assert result.retry_prompt is not None
        assert "No valid JSON found" in result.retry_prompt
        assert "Validation errors" in result.retry_prompt

    def test_reask_includes_schema_in_prompt(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK)
        result = v.validate("not json")
        assert result.retry_prompt is not None
        assert "Required schema" in result.retry_prompt
        assert "summary" in result.retry_prompt

    def test_block_produces_no_retry_prompt(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.BLOCK)
        result = v.validate("not json")
        assert result.is_valid is False
        assert result.retry_prompt is None

    def test_noop_produces_no_retry_prompt(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.NOOP)
        result = v.validate("not json")
        assert result.is_valid is False
        assert result.retry_prompt is None

    def test_escalate_produces_no_retry_prompt(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.ESCALATE)
        result = v.validate("not json")
        assert result.is_valid is False
        assert result.retry_prompt is None


# ---------------------------------------------------------------------------
# 9. ValidatedLoop
# ---------------------------------------------------------------------------

class TestValidatedLoop:
    def test_success_on_first_try(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK)
        loop = ValidatedLoop(validator=v)

        good_output = json.dumps({
            "summary": "All good",
            "issues": [],
            "approved": True,
        })

        def llm_callback(messages):
            return good_output

        result = loop.run_with_validation(llm_callback, [{"role": "user", "content": "review"}])
        assert result.is_valid is True
        assert result.retries_used == 0
        assert isinstance(result.value, CodeReview)

    def test_retry_on_validation_failure(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK, max_retries=3)
        loop = ValidatedLoop(validator=v)

        call_count = 0

        def llm_callback(messages):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "not valid json"
            return json.dumps({
                "summary": "Fixed",
                "issues": ["typo"],
                "approved": False,
            })

        result = loop.run_with_validation(llm_callback, [{"role": "user", "content": "review"}])
        assert result.is_valid is True
        assert result.retries_used == 2
        assert call_count == 3

    def test_max_retries_exhausted(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK, max_retries=2)
        loop = ValidatedLoop(validator=v)

        def llm_callback(messages):
            return "always bad output"

        result = loop.run_with_validation(llm_callback, [{"role": "user", "content": "review"}])
        assert result.is_valid is False
        assert result.retries_used == 2

    def test_retries_used_count_correct(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK, max_retries=5)
        loop = ValidatedLoop(validator=v)

        call_count = 0

        def llm_callback(messages):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return "bad"
            return json.dumps({
                "summary": "OK",
                "issues": [],
                "approved": True,
            })

        result = loop.run_with_validation(llm_callback, [{"role": "user", "content": "go"}])
        assert result.is_valid is True
        assert result.retries_used == 3

    def test_messages_accumulate_on_retry(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK, max_retries=2)
        loop = ValidatedLoop(validator=v)

        captured_messages: list[list[dict]] = []

        call_count = 0

        def llm_callback(messages):
            nonlocal call_count
            captured_messages.append(list(messages))
            call_count += 1
            if call_count < 2:
                return "bad"
            return json.dumps({
                "summary": "OK",
                "issues": [],
                "approved": True,
            })

        loop.run_with_validation(llm_callback, [{"role": "user", "content": "go"}])
        # First call: 1 message (original)
        assert len(captured_messages[0]) == 1
        # Second call: original + assistant + user retry = 3 messages
        assert len(captured_messages[1]) == 3
        assert captured_messages[1][1]["role"] == "assistant"
        assert captured_messages[1][2]["role"] == "user"

    def test_no_retry_on_block(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.BLOCK, max_retries=3)
        loop = ValidatedLoop(validator=v)

        call_count = 0

        def llm_callback(messages):
            nonlocal call_count
            call_count += 1
            return "bad output"

        result = loop.run_with_validation(llm_callback, [{"role": "user", "content": "go"}])
        assert result.is_valid is False
        # BLOCK produces no retry_prompt, so loop exits after first attempt
        assert call_count == 1

    def test_custom_max_retries_override(self):
        v = OutputValidator(schema=CodeReview, on_fail=OnFail.REASK, max_retries=10)
        loop = ValidatedLoop(validator=v, max_retries=1)

        call_count = 0

        def llm_callback(messages):
            nonlocal call_count
            call_count += 1
            return "bad"

        result = loop.run_with_validation(llm_callback, [{"role": "user", "content": "go"}])
        assert result.is_valid is False
        # max_retries=1 means 2 calls total (initial + 1 retry)
        assert call_count == 2
