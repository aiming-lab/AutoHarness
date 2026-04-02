"""Model context window mapping and output token configuration.

Maps Claude model identifiers to their context window sizes, default
max output tokens, and upper max output limits. Supports the ``[1m]``
suffix convention for 1M-context variants.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Context windows (input tokens)
# ---------------------------------------------------------------------------

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Claude 4.x
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4": 200_000,
    # Claude 3.x
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-sonnet-20240620": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    # GPT models
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-4-32k": 32_768,
    "gpt-3.5-turbo": 16_385,
    # o-series
    "o1": 200_000,
    "o1-mini": 128_000,
    "o1-pro": 200_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
}

# ---------------------------------------------------------------------------
# Default max output tokens per model
# ---------------------------------------------------------------------------

MODEL_DEFAULT_MAX_OUTPUT: dict[str, int] = {
    # Claude 4.x
    "claude-opus-4-6": 64_000,
    "claude-sonnet-4-6": 32_000,
    "claude-opus-4-5": 64_000,
    "claude-sonnet-4-5": 32_000,
    "claude-sonnet-4": 32_000,
    "claude-haiku-4-5": 32_000,
    "claude-haiku-4": 16_000,
    # Claude 3.x
    "claude-3-opus-20240229": 4_096,
    "claude-3-sonnet-20240229": 4_096,
    "claude-3-haiku-20240307": 4_096,
    "claude-3-5-sonnet-20241022": 8_192,
    "claude-3-5-sonnet-20240620": 8_192,
    "claude-3-5-haiku-20241022": 8_192,
    # GPT models
    "gpt-4o": 16_384,
    "gpt-4o-mini": 16_384,
    "gpt-4-turbo": 4_096,
    "gpt-4": 4_096,
    "gpt-4-32k": 4_096,
    "gpt-3.5-turbo": 4_096,
    # o-series
    "o1": 100_000,
    "o1-mini": 65_536,
    "o1-pro": 100_000,
    "o3": 100_000,
    "o3-mini": 100_000,
    "o4-mini": 100_000,
}

# ---------------------------------------------------------------------------
# Upper max output tokens (when escalated / extended thinking)
# ---------------------------------------------------------------------------

MODEL_UPPER_MAX_OUTPUT: dict[str, int] = {
    "claude-opus-4-6": 128_000,
    "claude-sonnet-4-6": 128_000,
    "claude-opus-4-5": 128_000,
    "claude-sonnet-4-5": 128_000,
    "claude-sonnet-4": 128_000,
}

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

CAPPED_DEFAULT_MAX_TOKENS: int = 8_000
"""Conservative max output for budget-conscious or simple tasks."""

ESCALATED_MAX_TOKENS: int = 64_000
"""Max output when extended/escalated mode is requested."""

COMPACT_MAX_OUTPUT_TOKENS: int = 20_000
"""Max output tokens to use during a compaction summarization call."""

_1M_CONTEXT_SIZE: int = 1_000_000
"""Context window size for models with the [1m] suffix."""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _strip_1m_suffix(model: str) -> tuple[str, bool]:
    """Strip the ``[1m]`` suffix and return (base_model, had_suffix)."""
    if model.endswith("[1m]"):
        return model[:-4], True
    return model, False


def get_context_window(model: str) -> int:
    """Return the context window size for *model*.

    If the model name ends with ``[1m]``, a 1 000 000 token window is
    returned.  Otherwise the value is looked up in
    :data:`MODEL_CONTEXT_WINDOWS`, falling back to ``200_000``.

    Parameters
    ----------
    model : str
        A model identifier such as ``"claude-opus-4-6"`` or
        ``"claude-opus-4-6[1m]"``.

    Returns
    -------
    int
        The context window size in tokens.
    """
    base, has_1m = _strip_1m_suffix(model)
    if has_1m:
        return _1M_CONTEXT_SIZE
    return MODEL_CONTEXT_WINDOWS.get(base, 200_000)


def get_max_output_tokens(model: str, escalated: bool = False) -> int:
    """Return the max output token limit for *model*.

    Parameters
    ----------
    model : str
        A model identifier, optionally with a ``[1m]`` suffix.
    escalated : bool
        If ``True``, return the upper (escalated) limit when available.

    Returns
    -------
    int
        Max output tokens.
    """
    base, _ = _strip_1m_suffix(model)
    if escalated:
        upper = MODEL_UPPER_MAX_OUTPUT.get(base)
        if upper is not None:
            return upper
    default = MODEL_DEFAULT_MAX_OUTPUT.get(base)
    if default is not None:
        return default
    return CAPPED_DEFAULT_MAX_TOKENS


def has_1m_context(model: str) -> bool:
    """Return ``True`` if *model* has the ``[1m]`` context suffix.

    Parameters
    ----------
    model : str
        A model identifier.

    Returns
    -------
    bool
    """
    return model.endswith("[1m]")


def model_supports_1m(model: str) -> bool:
    """Return ``True`` if the base model is known to support 1M context.

    Currently all models listed in :data:`MODEL_CONTEXT_WINDOWS` support
    the 1M context variant.

    Parameters
    ----------
    model : str
        A model identifier (with or without the ``[1m]`` suffix).

    Returns
    -------
    bool
    """
    base, _ = _strip_1m_suffix(model)
    return base in MODEL_CONTEXT_WINDOWS
