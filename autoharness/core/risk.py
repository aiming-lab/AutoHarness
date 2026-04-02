"""Risk Classifier engine for AutoHarness.

Classifies tool calls by risk level using regex pattern matching against
built-in and custom rule sets. Designed to run on every tool call with
sub-5ms latency in rules mode.

Modes:
    - "rules"  : Pure regex matching. Fast (<5ms). Default.
    - "llm"    : LLM-based classification (Phase 2 placeholder).
    - "hybrid" : Rules first, LLM for ambiguous cases (Phase 2 placeholder).
"""

from __future__ import annotations

import re
from typing import Any

from autoharness.core.types import RiskAssessment, RiskLevel, ToolCall
from autoharness.rules.builtin import BUILTIN_RULES, SAFE_COMMAND_PREFIXES


class _CompiledRule:
    """Internal wrapper pairing a compiled regex with its metadata."""

    __slots__ = ("category", "description", "level", "regex")

    def __init__(
        self,
        regex: re.Pattern[str],
        description: str,
        category: str,
        level: RiskLevel,
    ) -> None:
        self.regex = regex
        self.description = description
        self.category = category
        self.level = level


# Map from string risk names to RiskLevel enum, ordered by severity for
# comparison.
_LEVEL_ORDER: dict[RiskLevel, int] = {
    RiskLevel.low: 0,
    RiskLevel.medium: 1,
    RiskLevel.high: 2,
    RiskLevel.critical: 3,
}

_STR_TO_LEVEL: dict[str, RiskLevel] = {
    "low": RiskLevel.low,
    "medium": RiskLevel.medium,
    "high": RiskLevel.high,
    "critical": RiskLevel.critical,
}


class RiskClassifier:
    """Classify tool calls by risk level using pattern matching.

    Parameters
    ----------
    custom_rules:
        Optional list of rule dicts with keys: pattern, level, reason, tool.
    mode:
        Classification strategy — "rules", "llm", or "hybrid".
    """

    def __init__(
        self,
        custom_rules: list[dict[str, Any]] | None = None,
        mode: str = "rules",
    ) -> None:
        if mode not in ("rules", "llm", "hybrid"):
            raise ValueError(f"Invalid mode {mode!r}; expected 'rules', 'llm', or 'hybrid'")
        self._mode = mode

        # Pre-compile all rules once, grouped by tool category.
        # Structure: { category: [_CompiledRule, ...] }
        self._rules: dict[str, list[_CompiledRule]] = {}
        self._compile_builtin_rules()

        if custom_rules:
            for rule in custom_rules:
                self.add_custom_rule(
                    pattern=rule["pattern"],
                    level=rule["level"],
                    reason=rule.get("reason", ""),
                    tool=rule.get("tool", "*"),
                )

        self._safe_prefixes = frozenset(SAFE_COMMAND_PREFIXES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, tool_call: ToolCall) -> RiskAssessment:
        """Classify a tool call and return its risk assessment.

        For "rules" mode this is pure regex and completes in <5ms.
        For "llm"/"hybrid" modes, falls back to rules for now (Phase 2).
        """
        # Determine what text to scan and which rule categories apply.
        category = self._tool_to_category(tool_call.tool_name)
        text = self._extract_scannable_text(tool_call, category)

        # Fast path: if bash and command matches a known-safe prefix, return low.
        if category == "bash" and self._is_safe_command(text):
            return RiskAssessment(
                level=RiskLevel.low,
                classifier="rules",
                reason="Matches known-safe command prefix",
            )

        # Match against rules for this category (+ wildcard "*" rules).
        matches = self._match_rules(category, text)

        # Also scan all string values for secrets
        all_text = "\n".join(
            str(v) for v in tool_call.tool_input.values() if isinstance(v, str)
        )
        if all_text:
            matches.extend(self._match_rules("secrets_in_content", all_text))

        if not matches:
            return RiskAssessment(
                level=RiskLevel.low,
                classifier="rules",
                reason="No risk patterns matched",
            )

        # Return the highest severity match.
        matches.sort(key=lambda r: _LEVEL_ORDER[r.level], reverse=True)
        highest = matches[0]

        return RiskAssessment(
            level=highest.level,
            classifier="rules",
            matched_rule=highest.description,
            reason=highest.description,
        )

    def classify_content(self, content: str) -> RiskAssessment:
        """Scan arbitrary text for secrets and sensitive data.

        Used by output_sanitizer hooks to check tool outputs.
        """
        if not content:
            return RiskAssessment(
                level=RiskLevel.low,
                classifier="rules",
                reason="Empty content",
            )

        matches = self._match_rules("secrets_in_content", content)
        if not matches:
            return RiskAssessment(
                level=RiskLevel.low,
                classifier="rules",
                reason="No secrets detected",
            )

        matches.sort(key=lambda r: _LEVEL_ORDER[r.level], reverse=True)
        highest = matches[0]

        return RiskAssessment(
            level=highest.level,
            classifier="rules",
            matched_rule=highest.description,
            reason=highest.description,
        )

    def add_custom_rule(
        self,
        pattern: str,
        level: str,
        reason: str,
        tool: str = "*",
    ) -> None:
        """Add a custom risk rule at runtime.

        Parameters
        ----------
        pattern: Regex pattern string.
        level: One of "low", "medium", "high", "critical".
        reason: Human-readable description.
        tool: Tool category this applies to, or "*" for all.
        """
        risk_level = _STR_TO_LEVEL.get(level.lower())
        if risk_level is None:
            raise ValueError(
                f"Invalid risk level {level!r}; expected one of: "
                f"{', '.join(_STR_TO_LEVEL)}"
            )
        try:
            compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern {pattern!r}: {exc}") from exc

        rule = _CompiledRule(
            regex=compiled,
            description=reason,
            category=tool,
            level=risk_level,
        )
        self._rules.setdefault(tool, []).append(rule)

    def get_safe_commands(self) -> set[str]:
        """Return the set of known-safe command prefixes."""
        return set(self._safe_prefixes)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compile_builtin_rules(self) -> None:
        """Compile all built-in regex patterns once at init."""
        for category, levels in BUILTIN_RULES.items():
            compiled_list: list[_CompiledRule] = []
            for level_str, patterns in levels.items():
                risk_level = _STR_TO_LEVEL[level_str]
                for rp in patterns:
                    flags = re.MULTILINE
                    # Secrets patterns benefit from case-insensitive
                    if category == "secrets_in_content":
                        flags |= re.IGNORECASE
                    try:
                        compiled = re.compile(rp.pattern, flags)
                    except re.error:
                        # Skip malformed patterns rather than crash at init
                        continue
                    compiled_list.append(
                        _CompiledRule(
                            regex=compiled,
                            description=rp.description,
                            category=category,
                            level=risk_level,
                        )
                    )
            self._rules[category] = compiled_list

    def _tool_to_category(self, tool: str) -> str:
        """Map a tool name to a rule category.

        Handles common aliases: "Bash" -> "bash", "Write" -> "file_write", etc.
        """
        normalized = tool.lower().strip()
        mapping = {
            "bash": "bash",
            "shell": "bash",
            "terminal": "bash",
            "write": "file_write",
            "file_write": "file_write",
            "edit": "file_write",
            "read": "file_read",
            "file_read": "file_read",
        }
        return mapping.get(normalized, normalized)

    def _extract_scannable_text(self, tool_call: ToolCall, category: str) -> str:
        """Extract the primary text to scan from a tool call."""
        tool_input = tool_call.tool_input
        if category == "bash":
            return str(tool_input.get("command", ""))
        if category in ("file_write", "file_read"):
            return str(
                tool_input.get("file_path", "")
                or tool_input.get("path", "")
            )
        return str(tool_input.get("command", ""))

    def _match_rules(
        self, category: str, text: str
    ) -> list[_CompiledRule]:
        """Return all rules that match in the given category + wildcard."""
        if not text:
            return []

        matches: list[_CompiledRule] = []

        # Check category-specific rules
        for rule in self._rules.get(category, []):
            if rule.regex.search(text):
                matches.append(rule)

        # Check wildcard rules (custom rules with tool="*")
        for rule in self._rules.get("*", []):
            if rule.regex.search(text):
                matches.append(rule)

        return matches

    def _is_safe_command(self, command: str) -> bool:
        """Check if a command matches a known-safe prefix.

        Only returns True when the command is a simple, single command
        (no shell combinators like ;, &&, ||, $(), backticks) that
        starts with a recognized safe prefix with proper word boundary.
        """
        if not command:
            return False
        stripped = command.strip()

        # Never treat as safe if shell combinators or redirects are present —
        # they allow chaining dangerous commands or destructive writes
        # after a safe prefix.
        if any(ch in stripped for ch in (";", "&&", "||", "|", "$(", "`", ">", "<", "\n")):
            return False

        # Require word boundary after the prefix (space, tab, or end-of-string)
        for prefix in self._safe_prefixes:
            if stripped == prefix:
                return True
            if stripped.startswith(prefix + " ") or stripped.startswith(prefix + "\t"):
                return True
        return False
