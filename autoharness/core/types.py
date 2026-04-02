"""
AutoHarness Core Types
====================

Foundational data models for AutoHarness — an AI agent behavioral governance
middleware. All models use Pydantic v2 with strict validation.

These types define the complete data flow:
  ToolCall -> RiskAssessment -> HookResult -> PermissionDecision -> AuditRecord

Models are frozen (immutable) where semantically appropriate — once a risk
assessment or audit record is created, it should never be mutated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PipelineMode(str, Enum):
    """Governance pipeline operating mode.

    Controls how many pipeline steps are active and which features are enabled.

    - core: 6-step pipeline with basic risk classification and audit.
      Suitable for lightweight governance with minimal overhead.
    - standard: 8-step pipeline adding hooks and interface validation.
      Includes trace-based auditing inspired by Meta-Harness.
    - enhanced: Full 14-step pipeline with all governance features.
      Includes advanced context compaction, multi-agent orchestration,
      anti-distillation, and frustration detection.
    """

    core = "core"
    standard = "standard"
    enhanced = "enhanced"


class CompactionMode(str, Enum):
    """Context compaction operating mode.

    Controls which compaction layers are active.

    - core: Token budget tracking with simple oldest-first truncation.
    - standard: Adds microcompact (tool result clearing) on top of core.
    - enhanced: Multi-layer context compaction including LLM-based summarization,
      image stripping, and post-compact file restoration.
    """

    core = "core"
    standard = "standard"
    enhanced = "enhanced"


class RiskLevel(str, Enum):
    """Risk classification levels, ordered by severity."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class HookAction(str, Enum):
    """Actions a hook can prescribe for a tool call."""

    allow = "allow"
    deny = "deny"
    ask = "ask"
    sanitize = "sanitize"
    modify = "modify"


class Enforcement(str, Enum):
    """How a rule is enforced at runtime.

    - prompt: injected into the LLM system prompt only
    - hook: enforced programmatically via pre/post hooks
    - both: prompt guidance *and* hook enforcement
    """

    prompt = "prompt"
    hook = "hook"
    both = "both"


class RuleSeverity(str, Enum):
    """Severity level of a constitutional rule violation."""

    info = "info"
    warning = "warning"
    error = "error"


class HookProfile(str, Enum):
    """Predefined hook profiles controlling which hooks are active.

    - minimal: only critical safety hooks
    - standard: safety + common governance hooks
    - strict: all hooks enabled, maximum governance
    """

    minimal = "minimal"
    standard = "standard"
    strict = "strict"


class HookEvent(str, Enum):
    """Lifecycle events that hooks can subscribe to.

    Shell hook integration following the Hook I/O protocol standard.
    """

    pre_tool_use = "PreToolUse"
    post_tool_use = "PostToolUse"
    post_tool_use_failure = "PostToolUseFailure"
    on_block = "on_block"
    session_start = "SessionStart"
    session_end = "SessionEnd"
    pre_compact = "PreCompact"
    post_compact = "PostCompact"
    stop = "Stop"
    subagent_start = "SubagentStart"
    subagent_stop = "SubagentStop"
    permission_denied = "PermissionDenied"


# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------


class ToolCall(BaseModel, frozen=True):
    """Represents an incoming tool call to be governed.

    Captures everything needed to evaluate, route, and audit a single
    tool invocation before it reaches the underlying tool implementation.
    """

    tool_name: str = Field(..., description="Canonical name of the tool being called")
    tool_input: dict[str, Any] = Field(
        ..., description="Arguments passed to the tool"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (caller, model, etc.)",
    )
    session_id: str | None = Field(
        default=None, description="Session identifier for grouping related calls"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when the call was received",
    )

    @field_validator("tool_name")
    @classmethod
    def tool_name_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tool_name must be a non-empty string")
        return v


class ToolResult(BaseModel, frozen=True):
    """Result of a tool execution, including governance metadata.

    Created after a tool call completes (or is blocked before execution).
    """

    tool_name: str = Field(..., description="Name of the tool that was called")
    status: Literal["success", "blocked", "error"] = Field(
        ..., description="Outcome status of the tool call"
    )
    output: Any = Field(default=None, description="Raw output from the tool")
    error: str | None = Field(
        default=None, description="Error message if status is 'error'"
    )
    duration_ms: float = Field(
        default=0, ge=0, description="Execution time in milliseconds"
    )
    sanitized: bool = Field(
        default=False, description="Whether the output was sanitized by a post-hook"
    )
    blocked_reason: str | None = Field(
        default=None, description="Explanation if the call was blocked"
    )


class RiskAssessment(BaseModel, frozen=True):
    """Risk classification result for a tool call.

    Produced by the risk classifier (rule-based, LLM-based, or hybrid).
    """

    level: RiskLevel = Field(..., description="Assessed risk level")
    classifier: Literal["rules", "llm", "hybrid"] = Field(
        ..., description="Which classifier produced this assessment"
    )
    matched_rule: str | None = Field(
        default=None,
        description="ID of the rule that matched (for rules/hybrid classifiers)",
    )
    reason: str | None = Field(
        default=None, description="Human-readable explanation of the assessment"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score (1.0 for deterministic rule matches)",
    )


class HookResult(BaseModel, frozen=True):
    """Return value from a pre- or post-hook execution.

    Hooks inspect or transform tool calls/results and return an action
    plus optional modifications.
    """

    action: HookAction = Field(
        default=HookAction.allow, description="Prescribed action for the tool call"
    )
    reason: str | None = Field(
        default=None, description="Why this action was chosen"
    )
    severity: Literal["info", "warning", "error"] = Field(
        default="info", description="Severity of the hook finding"
    )
    modified_input: dict[str, Any] | None = Field(
        default=None,
        description="Replacement tool input (only when action is 'modify')",
    )
    sanitized_output: str | None = Field(
        default=None,
        description="Sanitized output string (only when action is 'sanitize')",
    )


class PermissionDecision(BaseModel, frozen=True):
    """Final permission decision for a tool call.

    Aggregates signals from rules, hooks, and classifiers into a single
    allow/deny/ask verdict.
    """

    action: Literal["allow", "deny", "ask"] = Field(
        ..., description="The final permission verdict"
    )
    reason: str = Field(
        ..., description="Human-readable explanation of the decision"
    )
    source: str = Field(
        ...,
        description="Which rule, hook, or classifier produced this decision",
    )
    risk_level: RiskLevel | None = Field(
        default=None, description="Associated risk level, if assessed"
    )
    rule_source: str | None = Field(
        default=None,
        description=(
            "Provenance of the rule that produced this decision. "
            "E.g. 'user_config', 'project_config', 'local_config', "
            "'cli_arg', 'session', 'constitution'. "
            "Enables enterprise audit trails to trace every decision "
            "back to the configuration file that defined the rule."
        ),
    )


class AuditRecord(BaseModel, frozen=True):
    """Complete audit trail entry for a single governed tool call.

    Captures the full lifecycle: call -> risk assessment -> hooks ->
    permission -> execution result. Designed for JSONL serialization.
    """

    timestamp: datetime = Field(
        ..., description="UTC timestamp of the event"
    )
    session_id: str = Field(
        ..., description="Session this event belongs to"
    )
    event_type: Literal[
        "tool_call",
        "tool_blocked",
        "tool_error",
        "hook_fired",
        "permission_check",
    ] = Field(..., description="Type of audit event")
    tool_name: str = Field(
        ..., description="Name of the tool involved"
    )
    tool_input_hash: str = Field(
        ...,
        description="SHA-256 hex digest of the serialized tool input (not raw input)",
    )
    risk: RiskAssessment | None = Field(
        default=None, description="Risk assessment result, if performed"
    )
    hooks_pre: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Summary dicts from pre-execution hooks",
    )
    hooks_post: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Summary dicts from post-execution hooks",
    )
    permission: PermissionDecision = Field(
        ..., description="Final permission decision"
    )
    execution: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "pending",
            "duration_ms": 0,
            "output_size": 0,
            "sanitized": False,
        },
        description="Execution result summary (status, duration, output_size, sanitized)",
    )

    @field_validator("tool_input_hash")
    @classmethod
    def must_be_valid_sha256(cls, v: str) -> str:
        """Validate that tool_input_hash looks like a SHA-256 hex digest."""
        if len(v) != 64 or not all(c in "0123456789abcdef" for c in v):
            raise ValueError(
                "tool_input_hash must be a 64-character lowercase hex SHA-256 digest"
            )
        return v

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line for JSONL audit logs."""
        return self.model_dump_json()

    @staticmethod
    def hash_input(tool_input: dict[str, Any]) -> str:
        """Compute a SHA-256 hex digest of a tool input dict.

        Uses a deterministic JSON serialization (sorted keys) so the
        same logical input always produces the same hash.
        """
        canonical = json.dumps(tool_input, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Constitution / configuration models
# ---------------------------------------------------------------------------


class Rule(BaseModel, frozen=True):
    """A single behavioral rule from the constitution.

    Rules define what an agent must/must not do and how violations are
    detected and enforced.
    """

    id: str = Field(..., description="Unique rule identifier (e.g. 'no-secrets-in-git')")
    description: str = Field(..., description="Human-readable rule description")
    severity: RuleSeverity = Field(
        default=RuleSeverity.error,
        description="How severe a violation of this rule is",
    )
    enforcement: Enforcement = Field(
        default=Enforcement.both,
        description="Whether enforced via prompt, hook, or both",
    )
    patterns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="File-match patterns for hook-enforced rules",
    )
    triggers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tool + pattern combinations that trigger this rule",
    )
    checks: list[str] = Field(
        default_factory=list,
        description="Named check functions to run for validation",
    )

    @field_validator("id")
    @classmethod
    def id_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Rule id must be a non-empty string")
        return v


class ToolPermission(BaseModel, frozen=True):
    """Permission configuration for a single tool.

    Defines the default policy and pattern-based overrides for path
    and argument matching.
    """

    policy: Literal["allow", "restricted", "deny"] = Field(
        ..., description="Base policy for this tool"
    )
    deny_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns that trigger denial",
    )
    ask_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns that require user confirmation",
    )
    allow_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns that are always allowed",
    )
    deny_paths: list[str] = Field(
        default_factory=list,
        description="Filesystem paths that trigger denial",
    )
    ask_paths: list[str] = Field(
        default_factory=list,
        description="Filesystem paths that require user confirmation",
    )
    allow_paths: list[str] = Field(
        default_factory=list,
        description="Filesystem paths that are always allowed",
    )
    scope: str | None = Field(
        default=None,
        description="Optional scope constraint (e.g. 'project_root')",
    )
    allow_domains: list[str] = Field(
        default_factory=list,
        description="Allowed domains for network-capable tools",
    )


class PermissionDefaults(BaseModel, frozen=True):
    """Global default permission policies.

    Applied when no tool-specific or pattern-specific rule matches.
    """

    unknown_tool: Literal["allow", "ask", "deny"] = Field(
        default="ask",
        description="Policy for tools not listed in permissions.tools",
    )
    unknown_path: Literal["allow", "ask", "deny"] = Field(
        default="deny",
        description="Policy for paths not matching any pattern",
    )
    on_error: Literal["allow", "ask", "deny"] = Field(
        default="deny",
        description="Policy when an error occurs during permission evaluation",
    )


# ---------------------------------------------------------------------------
# Typed sub-models for ConstitutionConfig
# ---------------------------------------------------------------------------


class IdentityConfig(BaseModel):
    """Typed identity configuration."""

    name: str = "autoharness"
    description: str = "AI agent behavioral governance middleware"
    boundaries: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class RiskThresholds(BaseModel, frozen=True):
    """Maps risk levels to governance actions."""

    low: Literal["allow", "ask", "deny", "flag"] = "allow"
    medium: Literal["allow", "ask", "deny", "flag"] = "ask"
    high: Literal["allow", "ask", "deny", "flag"] = "deny"
    critical: Literal["allow", "ask", "deny", "flag"] = "deny"

    model_config = {"extra": "ignore"}


class RiskConfig(BaseModel):
    """Typed risk classification configuration."""

    classifier: Literal["rules", "llm", "hybrid"] = "rules"
    thresholds: RiskThresholds = Field(default_factory=RiskThresholds)
    custom_rules: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class HooksConfig(BaseModel):
    """Typed hooks configuration."""

    profile: str = HookProfile.standard.value
    pre: list[dict[str, Any]] = Field(default_factory=list)
    post: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class AuditConfig(BaseModel):
    """Typed audit logging configuration."""

    enabled: bool = True
    format: str = "jsonl"
    output: str = "./audit.jsonl"
    retention_days: int = 90
    include: list[str] = Field(
        default_factory=lambda: [
            "tool_call", "tool_blocked", "tool_error",
            "hook_fired", "permission_check",
        ]
    )

    model_config = {"extra": "ignore"}


class PermissionsConfig(BaseModel):
    """Typed permissions configuration."""

    defaults: PermissionDefaults = Field(default_factory=PermissionDefaults)
    tools: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


# Valid actions that risk thresholds can map to
_VALID_THRESHOLD_ACTIONS = {"allow", "ask", "deny", "flag"}


class ConstitutionConfig(BaseModel):
    """The full parsed constitution model.

    This is the top-level configuration that defines an agent's behavioral
    governance: identity, rules, permissions, risk classification, hooks,
    and audit settings.

    Not frozen because it may be built incrementally during config loading,
    but individual sub-models are frozen once constructed.
    """

    version: str = Field(
        default="1.0", description="Constitution schema version"
    )
    mode: PipelineMode = Field(
        default=PipelineMode.enhanced,
        description=(
            "Pipeline operating mode: 'core' (6-step), "
            "'standard' (8-step), or 'enhanced' (14-step, default)"
        ),
    )
    identity: IdentityConfig | dict[str, Any] = Field(
        default_factory=IdentityConfig,
        description="Agent identity: name, description, and behavioral boundaries",
    )
    rules: list[Rule] = Field(
        default_factory=list,
        description="Ordered list of behavioral rules",
    )
    permissions: PermissionsConfig | dict[str, Any] = Field(
        default_factory=PermissionsConfig,
        description="Permission configuration with defaults and per-tool overrides",
    )
    risk: RiskConfig | dict[str, Any] = Field(
        default_factory=RiskConfig,
        description="Risk classification config: classifier type, thresholds, custom rules",
    )
    hooks: HooksConfig | dict[str, Any] = Field(
        default_factory=HooksConfig,
        description="Hook configuration: profile and event lists",
    )
    audit: AuditConfig | dict[str, Any] = Field(
        default_factory=AuditConfig,
        description="Audit logging configuration",
    )

    model_config = {"extra": "ignore"}

    @field_validator("risk")
    @classmethod
    def validate_risk_thresholds(
        cls, v: RiskConfig | dict[str, Any],
    ) -> RiskConfig | dict[str, Any]:
        """Ensure risk thresholds map RiskLevel values to valid actions."""
        if isinstance(v, RiskConfig):
            return v  # Already validated by the RiskConfig model
        thresholds = v.get("thresholds", {})
        if isinstance(thresholds, dict):
            for level_name, action in thresholds.items():
                if level_name not in {rl.value for rl in RiskLevel}:
                    raise ValueError(
                        f"Invalid risk level in thresholds: '{level_name}'. "
                        f"Must be one of: {', '.join(rl.value for rl in RiskLevel)}"
                    )
                if action not in _VALID_THRESHOLD_ACTIONS:
                    raise ValueError(
                        f"Invalid action for risk level '{level_name}': '{action}'. "
                        f"Must be one of: {', '.join(sorted(_VALID_THRESHOLD_ACTIONS))}"
                    )
        return v

    @field_validator("hooks")
    @classmethod
    def validate_hooks_profile(
        cls, v: HooksConfig | dict[str, Any],
    ) -> HooksConfig | dict[str, Any]:
        """Ensure the hook profile is a valid HookProfile value."""
        if isinstance(v, HooksConfig):
            return v  # Already validated by the HooksConfig model
        profile = v.get("profile")
        if profile is not None:
            valid = {hp.value for hp in HookProfile}
            if profile not in valid:
                raise ValueError(
                    f"Invalid hook profile: '{profile}'. "
                    f"Must be one of: {', '.join(sorted(valid))}"
                )
        return v

    def get_tool_permission(self, tool_name: str) -> ToolPermission | None:
        """Look up the permission config for a specific tool."""
        perms = self.permissions
        if isinstance(perms, PermissionsConfig):
            tools = perms.tools
        elif isinstance(perms, dict):
            tools = perms.get("tools", {})
        else:
            return None
        raw = tools.get(tool_name) if isinstance(tools, dict) else None
        if raw is None:
            return None
        if isinstance(raw, ToolPermission):
            return raw
        return ToolPermission(**raw)

    def get_defaults(self) -> PermissionDefaults:
        """Return the global permission defaults."""
        perms = self.permissions
        if isinstance(perms, PermissionsConfig):
            return perms.defaults
        if isinstance(perms, dict):
            raw = perms.get("defaults", {})
            if isinstance(raw, PermissionDefaults):
                return raw
            return PermissionDefaults(**raw)
        return PermissionDefaults()


class RiskPattern(BaseModel):
    """A compiled regex pattern for risk matching.

    Used by the rule-based risk classifier to detect dangerous operations.
    """

    pattern: str = Field(..., description="Raw regex string")
    description: str = Field(..., description="Human-readable description")
    category: str = Field(
        ...,
        description="Tool category: bash, file_write, file_read, secrets_in_content",
    )
