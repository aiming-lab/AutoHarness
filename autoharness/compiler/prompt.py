"""Prompt Compiler — transforms constitution rules into a concise system prompt addendum.

Generates a natural-language behavioral guide that can be injected into an LLM's
system prompt so the model understands what governance rules are in effect.

Design goals:
- Output < 500 tokens for a standard constitution
- Only include rules with enforcement="prompt" or "both"
- Describe "what" and "why", never implementation details (regex, hook names)
- Read naturally when embedded in a system prompt
"""

from __future__ import annotations

from typing import Any

from autoharness.core.constitution import Constitution
from autoharness.core.types import Enforcement, Rule, RuleSeverity


class PromptCompiler:
    """Compiles a Constitution into a prompt-friendly text addendum."""

    def compile(self, constitution: Constitution) -> str:
        """Generate a concise, context-friendly prompt addendum from the constitution.

        Only includes rules enforced via prompt or both (not hook-only rules,
        which are enforced programmatically and don't need LLM awareness).

        Args:
            constitution: The loaded and validated Constitution.

        Returns:
            A multi-line string suitable for injection into a system prompt.
        """
        sections: list[str] = []

        sections.append("# AutoHarness Behavioral Rules\n")
        sections.append(
            "The following rules are enforced by AutoHarness governance middleware.\n"
            "Violations will be blocked at runtime."
        )

        # Identity section
        identity_block = self._compile_identity(constitution)
        if identity_block:
            sections.append(identity_block)

        # Rules section
        rules_block = self._compile_rules(constitution)
        if rules_block:
            sections.append(rules_block)

        # Tool permissions summary
        perms_block = self._compile_permissions(constitution)
        if perms_block:
            sections.append(perms_block)

        # Enforcement explanation
        sections.append(self._compile_enforcement_note())

        return "\n\n".join(sections)

    def compile_minimal(self, constitution: Constitution) -> str:
        """Ultra-short version for context-constrained situations (< 200 tokens).

        Returns just the prompt-relevant rules as bullet points with no
        headers, explanations, or formatting.

        Args:
            constitution: The loaded and validated Constitution.

        Returns:
            A compact bullet-point string of active rules.
        """
        rules = self._get_prompt_rules(constitution)
        if not rules:
            return "No active behavioral rules."

        lines: list[str] = []
        for rule in rules:
            severity_tag = rule.severity.value.upper()
            lines.append(f"- [{severity_tag}] {rule.description}")
        return "\n".join(lines)

    def compile_for_budget(
        self,
        constitution: Constitution,
        token_budget: int = 500,
    ) -> str:
        """Compile a prompt addendum that fits within a token budget.

        Automatically chooses between full, reduced, and minimal versions
        based on the budget.  Useful after context compaction when the
        available prompt space shrinks.

        Parameters
        ----------
        constitution
            The governance constitution.
        token_budget
            Maximum approximate tokens for the addendum.

        Returns
        -------
        str
            The best-fit prompt addendum.
        """
        # Try full version first
        full = self.compile(constitution)
        if self.estimate_tokens(full) <= token_budget:
            return full

        # Try without permissions section (saves ~30-50%)
        sections: list[str] = []
        sections.append("# AutoHarness Behavioral Rules\n")
        sections.append("The following rules are enforced by AutoHarness governance.")
        rules_block = self._compile_rules(constitution)
        if rules_block:
            sections.append(rules_block)
        reduced = "\n\n".join(sections)
        if self.estimate_tokens(reduced) <= token_budget:
            return reduced

        # Fall back to minimal
        return self.compile_minimal(constitution)

    def compile_post_compact(self, constitution: Constitution) -> str:
        """Generate a re-injection addendum after context compaction.

        This is a compact version that reminds the LLM that governance
        is active, without repeating the full rule set.  Designed to be
        injected via a PostCompact hook.

        Parameters
        ----------
        constitution
            The governance constitution.

        Returns
        -------
        str
            A short reminder string (< 100 tokens).
        """
        rule_count = len(constitution.rules)
        rules = self._get_prompt_rules(constitution)
        error_rules = [r for r in rules if r.severity == RuleSeverity.error]

        lines = [
            "[AutoHarness] Governance is ACTIVE after context compaction.",
            f"{rule_count} rules enforced ({len(error_rules)} critical).",
        ]
        if error_rules:
            lines.append("Critical rules:")
            for r in error_rules[:5]:  # Top 5 only
                lines.append(f"  - {r.description}")
        lines.append("Tool calls are monitored. Do not circumvent rules.")
        return "\n".join(lines)

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate using the ~4 characters per token heuristic.

        This is intentionally simple — not meant to replace a real tokenizer,
        just good enough for budget checks.

        Args:
            text: The text to estimate.

        Returns:
            Approximate token count.
        """
        return len(text) // 4

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_prompt_rules(constitution: Constitution) -> list[Rule]:
        """Return rules that should appear in the prompt.

        Filters to enforcement=prompt or enforcement=both. Hook-only rules
        are enforced programmatically and don't need LLM awareness.
        """
        return [
            r
            for r in constitution.rules
            if r.enforcement in (Enforcement.prompt, Enforcement.both)
        ]

    @staticmethod
    def _compile_identity(constitution: Constitution) -> str:
        """Build the identity section from constitution metadata."""
        identity = constitution.identity
        # Handle both dict-style and object-style identity
        if isinstance(identity, dict):
            name = identity.get("name", "")
            description = identity.get("description", "")
            boundaries = identity.get("boundaries", [])
        else:
            name = getattr(identity, "name", "")
            description = getattr(identity, "description", "")
            boundaries = getattr(identity, "boundaries", [])

        if not name and not description:
            return ""

        parts: list[str] = ["## Identity"]
        desc_part = f" \u2014 {description}" if description else ""
        parts.append(f"You are: {name}{desc_part}")

        if boundaries:
            parts.append("Boundaries:")
            for b in boundaries:
                parts.append(f"- {b}")

        return "\n".join(parts)

    def _compile_rules(self, constitution: Constitution) -> str:
        """Build the rules section from prompt-relevant rules."""
        rules = self._get_prompt_rules(constitution)
        if not rules:
            return ""

        lines: list[str] = ["## Rules"]

        # Group by severity for readability: errors first, then warnings, then info
        severity_order = {
            RuleSeverity.error: 0,
            RuleSeverity.warning: 1,
            RuleSeverity.info: 2,
        }
        sorted_rules = sorted(rules, key=lambda r: severity_order.get(r.severity, 9))

        for rule in sorted_rules:
            severity_tag = rule.severity.value.upper()
            lines.append(f"- [{severity_tag}] {rule.description}")

        return "\n".join(lines)

    @staticmethod
    def _compile_permissions(constitution: Constitution) -> str:
        """Build a human-readable tool permissions summary."""
        permissions = constitution.permissions
        if permissions is None:
            return ""

        # Extract the tools list or dict depending on model version
        tools_data: Any = None
        if isinstance(permissions, dict):
            tools_data = permissions.get("tools", {})
        else:
            tools_data = getattr(permissions, "tools", None)

        if not tools_data:
            return ""

        lines: list[str] = ["## Tool Permissions Summary"]

        # Handle list of tool permissions (legacy model)
        if isinstance(tools_data, list):
            for tp in tools_data:
                if isinstance(tp, dict):
                    tool_name = tp.get("tool", "unknown")
                    summary = _summarize_tool_permission_dict(tp)
                else:
                    tool_name = getattr(tp, "tool", "unknown")
                    summary = _summarize_tool_permission_obj(tp)
                lines.append(f"- {tool_name}: {summary}")
        # Handle dict of tool permissions (new model)
        elif isinstance(tools_data, dict):
            for tool_name, tp in tools_data.items():
                if isinstance(tp, dict):
                    summary = _summarize_tool_permission_new_dict(tp)
                else:
                    policy = getattr(tp, "policy", "allow")
                    summary = _policy_to_summary(policy, tp)
                lines.append(f"- {tool_name}: {summary}")

        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _compile_enforcement_note() -> str:
        """Explain what happens on violation."""
        return (
            "## What Happens When You Violate\n"
            "- ERROR rules: action will be BLOCKED by runtime hooks\n"
            "- WARNING rules: action will proceed but be logged\n"
            "- INFO rules: noted for audit, no enforcement"
        )


# ======================================================================
# Module-level helpers for permission summarization
# ======================================================================


def _summarize_tool_permission_obj(tp: Any) -> str:
    """Summarize a legacy ToolPermission object for prompt display."""
    blocked = getattr(tp, "blocked_patterns", [])
    confirm = getattr(tp, "require_confirmation", False)
    allowed = getattr(tp, "allow", True)

    if not allowed:
        return "denied"
    if blocked or confirm:
        parts: list[str] = []
        if blocked:
            parts.append("some commands blocked")
        if confirm:
            parts.append("some require confirmation")
        return f"restricted ({', '.join(parts)})"
    return "allowed"


def _summarize_tool_permission_dict(tp: dict[str, Any]) -> str:
    """Summarize a legacy ToolPermission dict for prompt display."""
    blocked = tp.get("blocked_patterns", [])
    confirm = tp.get("require_confirmation", False)
    allowed = tp.get("allow", True)

    if not allowed:
        return "denied"
    if blocked or confirm:
        parts: list[str] = []
        if blocked:
            parts.append("some commands blocked")
        if confirm:
            parts.append("some require confirmation")
        return f"restricted ({', '.join(parts)})"
    return "allowed"


def _summarize_tool_permission_new_dict(tp: dict[str, Any]) -> str:
    """Summarize a new-style ToolPermission dict for prompt display."""
    policy = tp.get("policy", "allow")
    deny_patterns = tp.get("deny_patterns", [])
    ask_patterns = tp.get("ask_patterns", [])
    deny_paths = tp.get("deny_paths", [])
    ask_paths = tp.get("ask_paths", [])
    return _policy_to_summary_from_parts(policy, deny_patterns, ask_patterns, deny_paths, ask_paths)


def _policy_to_summary(policy: str, tp: Any) -> str:
    """Convert new-model policy + object to a human summary."""
    deny_patterns = getattr(tp, "deny_patterns", [])
    ask_patterns = getattr(tp, "ask_patterns", [])
    deny_paths = getattr(tp, "deny_paths", [])
    ask_paths = getattr(tp, "ask_paths", [])
    return _policy_to_summary_from_parts(policy, deny_patterns, ask_patterns, deny_paths, ask_paths)


def _policy_to_summary_from_parts(
    policy: str,
    deny_patterns: list[str],
    ask_patterns: list[str],
    deny_paths: list[str],
    ask_paths: list[str],
) -> str:
    """Build a human-readable one-liner from permission components."""
    if policy == "deny":
        return "denied"
    if policy == "restricted" or deny_patterns or deny_paths or ask_patterns or ask_paths:
        details: list[str] = []
        if deny_patterns or deny_paths:
            details.append("some paths blocked")
        if ask_patterns or ask_paths:
            details.append("some require confirmation")
        qualifier = f" ({', '.join(details)})" if details else ""
        return f"restricted{qualifier}"
    return "allowed"
