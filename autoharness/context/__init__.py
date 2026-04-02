"""Context management engine for AutoHarness."""

from autoharness.context.artifacts import (
    ARTIFACT_HANDLE_PATTERN,
    ARTIFACT_HANDLE_PREFIX,
    ARTIFACT_MIN_TOKENS,
    ArtifactHandle,
    ArtifactStore,
    replace_large_content,
    restore_artifacts,
)
from autoharness.context.autocompact import (
    AUTOCOMPACT_BUFFER_TOKENS,
    MAX_COMPACT_STREAMING_RETRIES,
    MAX_OUTPUT_TOKENS_FOR_SUMMARY,
    WARNING_THRESHOLD_BUFFER_TOKENS,
    AutoCompactor,
    reactive_compact,
    strip_images_from_messages,
)
from autoharness.context.microcompact import (
    COMPACTABLE_TOOLS,
    MIN_CONTENT_SIZE,
    PRESERVE_RESULT_TOOLS,
    microcompact,
)
from autoharness.context.models import (
    CAPPED_DEFAULT_MAX_TOKENS,
    COMPACT_MAX_OUTPUT_TOKENS,
    ESCALATED_MAX_TOKENS,
    MODEL_CONTEXT_WINDOWS,
    MODEL_DEFAULT_MAX_OUTPUT,
    MODEL_UPPER_MAX_OUTPUT,
    get_context_window,
    get_max_output_tokens,
    has_1m_context,
    model_supports_1m,
)
from autoharness.context.post_compact import (
    POST_COMPACT_MAX_FILES_TO_RESTORE,
    POST_COMPACT_MAX_TOKENS_PER_FILE,
    POST_COMPACT_MAX_TOKENS_PER_SKILL,
    POST_COMPACT_SKILLS_TOKEN_BUDGET,
    POST_COMPACT_TOKEN_BUDGET,
    restore_files_after_compact,
)
from autoharness.context.recovery import (
    OutputRecoveryLoop,
    RetryConfig,
    compute_backoff_ms,
    is_retryable_status,
    retry_with_backoff,
)
from autoharness.context.token_budget import (
    find_token_budget_positions,
    get_budget_continuation_message,
    parse_token_budget,
)
from autoharness.context.tokens import (
    BYTES_PER_TOKEN_DEFAULT,
    BYTES_PER_TOKEN_JSON,
    IMAGE_MAX_TOKEN_SIZE,
    TokenBudget,
    TokenUsage,
    estimate_message_tokens,
    estimate_tokens,
    estimate_tokens_by_type,
)

__all__ = [
    "ARTIFACT_HANDLE_PATTERN",
    "ARTIFACT_HANDLE_PREFIX",
    # artifacts
    "ARTIFACT_MIN_TOKENS",
    # autocompact
    "AUTOCOMPACT_BUFFER_TOKENS",
    # tokens
    "BYTES_PER_TOKEN_DEFAULT",
    "BYTES_PER_TOKEN_JSON",
    "CAPPED_DEFAULT_MAX_TOKENS",
    # microcompact
    "COMPACTABLE_TOOLS",
    "COMPACT_MAX_OUTPUT_TOKENS",
    "ESCALATED_MAX_TOKENS",
    "IMAGE_MAX_TOKEN_SIZE",
    "MAX_COMPACT_STREAMING_RETRIES",
    "MAX_OUTPUT_TOKENS_FOR_SUMMARY",
    "MIN_CONTENT_SIZE",
    # models
    "MODEL_CONTEXT_WINDOWS",
    "MODEL_DEFAULT_MAX_OUTPUT",
    "MODEL_UPPER_MAX_OUTPUT",
    # post_compact
    "POST_COMPACT_MAX_FILES_TO_RESTORE",
    "POST_COMPACT_MAX_TOKENS_PER_FILE",
    "POST_COMPACT_MAX_TOKENS_PER_SKILL",
    "POST_COMPACT_SKILLS_TOKEN_BUDGET",
    "POST_COMPACT_TOKEN_BUDGET",
    "PRESERVE_RESULT_TOOLS",
    "WARNING_THRESHOLD_BUFFER_TOKENS",
    "ArtifactHandle",
    "ArtifactStore",
    "AutoCompactor",
    # recovery
    "OutputRecoveryLoop",
    "RetryConfig",
    "TokenBudget",
    "TokenUsage",
    "compute_backoff_ms",
    "estimate_message_tokens",
    "estimate_tokens",
    "estimate_tokens_by_type",
    "find_token_budget_positions",
    "get_budget_continuation_message",
    "get_context_window",
    "get_max_output_tokens",
    "has_1m_context",
    "is_retryable_status",
    "microcompact",
    "model_supports_1m",
    # token_budget
    "parse_token_budget",
    "reactive_compact",
    "replace_large_content",
    "restore_artifacts",
    "restore_files_after_compact",
    "retry_with_backoff",
    "strip_images_from_messages",
]
