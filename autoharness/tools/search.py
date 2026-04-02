"""ToolSearch -- deferred tool discovery via keyword matching.

When too many tools are registered, non-essential tools are deferred.
The model can call ToolSearch to discover them by keyword.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

class ToolSearch:
    """Keyword-based tool discovery for deferred tools."""

    def __init__(self, registry: Any = None) -> None:
        self.registry = registry
        self._description_cache: dict[str, str] = {}

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search deferred tools by keyword.

        Returns list of matching tool schemas (name, description, input_schema).
        """
        if not self.registry:
            return []

        deferred = self.registry.list_deferred()
        if not deferred:
            return []

        # Score each tool by keyword match
        query_terms = set(query.lower().split())
        scored = []

        for tool in deferred:
            score = self._score_tool(tool, query_terms)
            if score > 0:
                scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _, tool in scored[:max_results]:
            results.append(tool.to_api_schema())

        return results

    def _score_tool(self, tool: Any, query_terms: set[str]) -> float:
        """Score a tool against query terms."""
        score = 0.0

        # Match against name
        name_lower = tool.name.lower()
        for term in query_terms:
            if term in name_lower:
                score += 3.0

        # Match against description
        desc_lower = tool.description.lower()
        for term in query_terms:
            if term in desc_lower:
                score += 1.0

        # Match against search_hint (highest weight)
        if tool.search_hint:
            hint_lower = tool.search_hint.lower()
            for term in query_terms:
                if term in hint_lower:
                    score += 5.0

        # Match against aliases
        for alias in tool.aliases:
            alias_lower = alias.lower()
            for term in query_terms:
                if term in alias_lower:
                    score += 2.0

        return score

    def invalidate_cache(self) -> None:
        """Clear description cache when tool set changes."""
        self._description_cache.clear()
