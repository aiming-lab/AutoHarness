"""Separates user context (CLAUDE.md, memory) from system context (git, env).

Each is independently cacheable. System prompt injection triggers cache invalidation.
"""

from __future__ import annotations

from collections.abc import Callable


class ContextManager:
    """Manages user and system context separation with caching."""

    def __init__(self) -> None:
        self._user_context_cache: str | None = None
        self._system_context_cache: str | None = None
        self._injection: str | None = None

    def set_injection(self, value: str | None) -> None:
        """Set debug injection and invalidate caches."""
        self._injection = value
        self._user_context_cache = None
        self._system_context_cache = None

    def get_user_context(self, loader: Callable[[], str]) -> str:
        """Get user context (CLAUDE.md, memory files). Cached."""
        if self._user_context_cache is None:
            self._user_context_cache = loader()
        return self._user_context_cache

    def get_system_context(self, loader: Callable[[], str]) -> str:
        """Get system context (git status, env info). Cached."""
        if self._system_context_cache is None:
            self._system_context_cache = loader()
        return self._system_context_cache

    @property
    def injection(self) -> str | None:
        """Return the current debug injection value."""
        return self._injection

    def invalidate(self) -> None:
        """Invalidate all cached context."""
        self._user_context_cache = None
        self._system_context_cache = None
