"""Multi-Agent Governance — role-based permission control for agent ensembles.

Different agents in a multi-agent system need different permission sets.
A "reviewer" agent should only read files, while a "coder" agent needs
write access. A "planner" generates plans but never executes them.

Built-in agent profiles for common roles:
  - Explore agent = read-only
  - Plan agent = read-only
  - Verification agent = adversarial/read-only

Usage::

    from autoharness.core.constitution import Constitution
    from autoharness.core.multi_agent import MultiAgentGovernor, AgentProfile

    governor = MultiAgentGovernor(Constitution.default())
    governor.register_agent("coder", AgentProfile(
        name="coder",
        role="coder",
        allowed_tools=["bash", "read", "write", "edit"],
        max_risk_level="medium",
    ))
    governor.register_agent("reviewer", AgentProfile(
        name="reviewer",
        role="reviewer",
        allowed_tools=["read", "grep", "glob"],
        max_risk_level="low",
    ))

    coder_pipeline = governor.get_pipeline("coder")
    reviewer_pipeline = governor.get_pipeline("reviewer")

    # Each pipeline has isolated audit trails and enforces agent-specific rules
"""

from __future__ import annotations

import copy
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from autoharness.core.constitution import Constitution
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.types import (
    HookAction,
    HookResult,
    PermissionDecision,
    RiskAssessment,
    ToolCall,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk level ordering for comparison
# ---------------------------------------------------------------------------

_RISK_LEVEL_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def _risk_level_value(level: str) -> int:
    """Convert a risk level string to an ordinal for comparison."""
    return _RISK_LEVEL_ORDER.get(level, 0)


# ---------------------------------------------------------------------------
# AgentProfile
# ---------------------------------------------------------------------------


@dataclass
class AgentProfile:
    """Define governance profile for a specific agent role.

    Parameters
    ----------
    name : str
        Unique identifier for this agent profile.
    role : str
        Semantic role: "coder", "reviewer", "planner", "executor", etc.
    allowed_tools : list[str] | None
        Whitelist of tool names this agent may use. ``None`` means all tools
        are allowed (subject to other governance checks).
    denied_tools : list[str] | None
        Blacklist of tool names this agent may NOT use. Applied after the
        whitelist. ``None`` means no explicit denials.
    constitution_override : dict | None
        Partial constitution dict to merge on top of the base constitution.
        Useful for overriding risk thresholds, adding extra rules, etc.
    max_risk_level : str
        Maximum risk level this agent can handle without automatic denial.
        Calls exceeding this level are blocked. One of: "low", "medium",
        "high", "critical".
    inherit_from : str | None
        Name of another registered profile to inherit settings from.
        The current profile's explicit settings override inherited ones.
    metadata : dict
        Arbitrary metadata attached to this profile (e.g., description,
        model name, cost tier).
    """

    name: str
    role: str
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    constitution_override: dict[str, Any] | None = None
    max_risk_level: str = "medium"
    inherit_from: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_risk_level not in _RISK_LEVEL_ORDER:
            raise ValueError(
                f"Invalid max_risk_level: {self.max_risk_level!r}. "
                f"Must be one of: {', '.join(_RISK_LEVEL_ORDER)}"
            )
        if self.allowed_tools is not None and self.denied_tools is not None:
            overlap = set(self.allowed_tools) & set(self.denied_tools)
            if overlap:
                raise ValueError(
                    f"Tools appear in both allowed and denied lists: {overlap}"
                )


# ---------------------------------------------------------------------------
# Pre-built profiles
# ---------------------------------------------------------------------------


BUILTIN_PROFILES: dict[str, AgentProfile] = {
    "coder": AgentProfile(
        name="coder",
        role="coder",
        allowed_tools=None,  # Full access to all tools
        denied_tools=None,
        max_risk_level="medium",
        metadata={"description": "Full-access coding agent. Can read, write, and execute."},
    ),
    "reviewer": AgentProfile(
        name="reviewer",
        role="reviewer",
        allowed_tools=["read", "Read", "grep", "Grep", "glob", "Glob", "search"],
        denied_tools=None,
        max_risk_level="low",
        metadata={
            "description": "Read-only review agent. "
            "Cannot modify files or execute commands."
        },
    ),
    "planner": AgentProfile(
        name="planner",
        role="planner",
        allowed_tools=["read", "Read", "grep", "Grep", "glob", "Glob", "search"],
        denied_tools=None,
        max_risk_level="low",
        metadata={
            "description": "Planning agent. Read-only access "
            "for analysis and plan generation."
        },
    ),
    "executor": AgentProfile(
        name="executor",
        role="executor",
        allowed_tools=[
            "bash", "Bash", "write", "Write", "edit", "Edit",
            "read", "Read", "grep", "Grep", "glob", "Glob",
        ],
        denied_tools=None,
        max_risk_level="medium",
        constitution_override={
            "risk": {
                "thresholds": {
                    "low": "allow",
                    "medium": "allow",
                    "high": "deny",
                    "critical": "deny",
                },
            },
        },
        metadata={
            "description": "Restricted executor. Can run commands and write files "
            "but high-risk operations are blocked.",
        },
    ),
}


# ---------------------------------------------------------------------------
# Tool filter hook factory
# ---------------------------------------------------------------------------


def _make_tool_filter_hook(
    agent_name: str,
    allowed_tools: list[str] | None,
    denied_tools: list[str] | None,
    max_risk_level: str,
) -> Callable[[ToolCall, RiskAssessment, dict[str, Any]], HookResult]:
    """Create a pre-hook that enforces tool whitelist/blacklist and risk ceiling.

    Returns a callable with the standard pre-hook signature:
        (tool_call, risk, context) -> HookResult
    """
    max_risk_value = _risk_level_value(max_risk_level)
    allowed_set = set(allowed_tools) if allowed_tools is not None else None
    denied_set = set(denied_tools) if denied_tools is not None else None

    def _agent_tool_filter(
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> HookResult:
        tool = tool_call.tool_name

        # Check whitelist
        if allowed_set is not None and tool not in allowed_set:
            return HookResult(
                action=HookAction.deny,
                reason=(
                    f"Agent '{agent_name}' (role) is not allowed to use tool "
                    f"'{tool}'. Allowed tools: {sorted(allowed_set)}"
                ),
                severity="error",
            )

        # Check blacklist
        if denied_set is not None and tool in denied_set:
            return HookResult(
                action=HookAction.deny,
                reason=(
                    f"Agent '{agent_name}' is explicitly denied tool '{tool}'"
                ),
                severity="error",
            )

        # Check risk ceiling
        actual_risk_value = _risk_level_value(risk.level.value)
        if actual_risk_value > max_risk_value:
            return HookResult(
                action=HookAction.deny,
                reason=(
                    f"Agent '{agent_name}' max risk is '{max_risk_level}' but "
                    f"tool call is '{risk.level.value}'"
                    + (f": {risk.reason}" if risk.reason else "")
                ),
                severity="error",
            )

        return HookResult(action=HookAction.allow)

    _agent_tool_filter.__name__ = f"agent_filter_{agent_name}"
    _agent_tool_filter._hook_name = f"agent_filter_{agent_name}"  # type: ignore[attr-defined]
    _agent_tool_filter._hook_event = "pre_tool_use"  # type: ignore[attr-defined]

    return _agent_tool_filter


# ---------------------------------------------------------------------------
# MultiAgentGovernor
# ---------------------------------------------------------------------------


class MultiAgentGovernor:
    """Manage governance for multiple agent roles.

    The governor holds a base constitution and produces per-agent
    ToolGovernancePipeline instances with role-specific restrictions.

    Each agent gets:
    - A tool whitelist/blacklist enforced via pre-hooks
    - A risk ceiling (calls above the agent's max_risk_level are blocked)
    - Optional constitution overrides (e.g., stricter thresholds)
    - An isolated session ID for separate audit trails

    Parameters
    ----------
    base_constitution : Constitution
        The base governance constitution. Agent-specific overrides are
        merged on top of this.
    project_dir : str | None
        Project root directory for path scoping. Defaults to cwd.
    session_prefix : str | None
        Prefix for auto-generated session IDs. Each agent gets
        ``"{prefix}-{agent_name}-{uuid}"``.
    """

    def __init__(
        self,
        base_constitution: Constitution,
        *,
        project_dir: str | None = None,
        session_prefix: str | None = None,
    ) -> None:
        self._base_constitution = base_constitution
        self._project_dir = project_dir
        self._session_prefix = session_prefix or "multi"
        self._profiles: dict[str, AgentProfile] = {}
        self._pipelines: dict[str, ToolGovernancePipeline] = {}

    # ------------------------------------------------------------------
    # Profile registration
    # ------------------------------------------------------------------

    def register_agent(
        self,
        name: str,
        profile: AgentProfile | None = None,
    ) -> None:
        """Register an agent profile.

        If ``profile`` is ``None``, looks up the name in built-in profiles.

        Parameters
        ----------
        name : str
            The agent name (used as lookup key).
        profile : AgentProfile | None
            The profile to register. If None, uses a built-in profile
            matching ``name``.

        Raises
        ------
        ValueError
            If no profile is provided and the name is not a built-in.
        """
        if profile is None:
            if name not in BUILTIN_PROFILES:
                raise ValueError(
                    f"No built-in profile named '{name}'. "
                    f"Available: {', '.join(BUILTIN_PROFILES)}. "
                    f"Or provide an explicit AgentProfile."
                )
            profile = copy.deepcopy(BUILTIN_PROFILES[name])

        # Resolve inheritance
        resolved = self._resolve_inheritance(profile)

        self._profiles[name] = resolved
        # Invalidate cached pipeline
        self._pipelines.pop(name, None)

        logger.info(
            "Registered agent '%s' (role=%s, max_risk=%s, allowed=%s, denied=%s)",
            name,
            resolved.role,
            resolved.max_risk_level,
            resolved.allowed_tools,
            resolved.denied_tools,
        )

    def register_builtin(self, name: str) -> None:
        """Register a built-in profile by name.

        Convenience method equivalent to ``register_agent(name, None)``.

        Parameters
        ----------
        name : str
            One of: "coder", "reviewer", "planner", "executor".
        """
        self.register_agent(name)

    def register_all_builtins(self) -> None:
        """Register all four built-in profiles at once."""
        for name in BUILTIN_PROFILES:
            self.register_agent(name)

    # ------------------------------------------------------------------
    # Inheritance resolution
    # ------------------------------------------------------------------

    def _resolve_inheritance(self, profile: AgentProfile) -> AgentProfile:
        """Resolve profile inheritance chain.

        If ``profile.inherit_from`` is set, load the parent profile and
        merge: parent values are used for any ``None`` fields in the child.

        Raises
        ------
        ValueError
            If the parent profile is not registered and not a built-in.
        """
        if profile.inherit_from is None:
            return profile

        parent_name = profile.inherit_from
        # Look up in registered profiles first, then built-ins
        parent = self._profiles.get(parent_name)
        if parent is None:
            parent = BUILTIN_PROFILES.get(parent_name)
        if parent is None:
            raise ValueError(
                f"Profile '{profile.name}' inherits from '{parent_name}', "
                f"which is not registered or built-in."
            )

        # Recursively resolve parent
        parent = self._resolve_inheritance(parent)

        # Merge: child overrides parent
        return AgentProfile(
            name=profile.name,
            role=profile.role or parent.role,
            allowed_tools=(
                profile.allowed_tools
                if profile.allowed_tools is not None
                else parent.allowed_tools
            ),
            denied_tools=(
                profile.denied_tools
                if profile.denied_tools is not None
                else parent.denied_tools
            ),
            constitution_override=_merge_overrides(
                parent.constitution_override, profile.constitution_override
            ),
            max_risk_level=profile.max_risk_level,
            inherit_from=None,  # resolved
            metadata={**parent.metadata, **profile.metadata},
        )

    # ------------------------------------------------------------------
    # Pipeline construction
    # ------------------------------------------------------------------

    def get_pipeline(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
    ) -> ToolGovernancePipeline:
        """Get or create a governance pipeline for the named agent.

        Pipelines are cached per agent name. Call ``reset_pipeline(name)``
        to force reconstruction.

        Parameters
        ----------
        agent_name : str
            Name of a registered agent.
        session_id : str | None
            Override the auto-generated session ID.

        Returns
        -------
        ToolGovernancePipeline
            A pipeline configured with the agent's restrictions.

        Raises
        ------
        KeyError
            If the agent name is not registered.
        """
        if agent_name not in self._profiles:
            raise KeyError(
                f"Agent '{agent_name}' is not registered. "
                f"Registered agents: {', '.join(self._profiles) or '(none)'}"
            )

        if agent_name in self._pipelines:
            return self._pipelines[agent_name]

        profile = self._profiles[agent_name]
        pipeline = self._build_pipeline(profile, session_id)
        self._pipelines[agent_name] = pipeline
        return pipeline

    def _build_pipeline(
        self,
        profile: AgentProfile,
        session_id: str | None,
    ) -> ToolGovernancePipeline:
        """Construct a pipeline for a specific agent profile."""
        # Build agent-specific constitution
        constitution = self._build_agent_constitution(profile)

        # Generate session ID
        sid = session_id or (
            f"{self._session_prefix}-{profile.name}-{uuid.uuid4().hex[:8]}"
        )

        # Create pipeline
        pipeline = ToolGovernancePipeline(
            constitution=constitution,
            project_dir=self._project_dir,
            session_id=sid,
        )

        # Register the agent tool filter hook
        hook_func = _make_tool_filter_hook(
            agent_name=profile.name,
            allowed_tools=profile.allowed_tools,
            denied_tools=profile.denied_tools,
            max_risk_level=profile.max_risk_level,
        )
        pipeline.hook_registry.register("pre_tool_use", hook_func)

        return pipeline

    def _build_agent_constitution(self, profile: AgentProfile) -> Constitution:
        """Build an agent-specific constitution by merging overrides."""
        if profile.constitution_override is None:
            return self._base_constitution

        # Merge override on top of base
        override_constitution = Constitution.from_dict(profile.constitution_override)
        return Constitution.merge(self._base_constitution, override_constitution)

    # ------------------------------------------------------------------
    # Pipeline lifecycle
    # ------------------------------------------------------------------

    def reset_pipeline(self, agent_name: str) -> None:
        """Force reconstruction of the pipeline for an agent.

        Useful after changing the agent's profile or the base constitution.
        """
        self._pipelines.pop(agent_name, None)

    def reset_all_pipelines(self) -> None:
        """Force reconstruction of all cached pipelines."""
        self._pipelines.clear()

    # ------------------------------------------------------------------
    # Convenience: evaluate without getting the pipeline
    # ------------------------------------------------------------------

    def evaluate(
        self,
        agent_name: str,
        tool_call: ToolCall,
    ) -> PermissionDecision:
        """Evaluate a tool call for a specific agent.

        Shortcut for ``governor.get_pipeline(name).evaluate(tool_call)``.
        """
        pipeline = self.get_pipeline(agent_name)
        return pipeline.evaluate(tool_call)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def agents(self) -> dict[str, AgentProfile]:
        """Return a copy of registered agent profiles."""
        return dict(self._profiles)

    @property
    def base_constitution(self) -> Constitution:
        """The base constitution used for all agents."""
        return self._base_constitution

    def get_profile(self, agent_name: str) -> AgentProfile:
        """Return the profile for a registered agent.

        Raises
        ------
        KeyError
            If the agent is not registered.
        """
        if agent_name not in self._profiles:
            raise KeyError(f"Agent '{agent_name}' is not registered.")
        return self._profiles[agent_name]

    def get_audit_summary(self, agent_name: str) -> dict[str, Any]:
        """Get audit summary for a specific agent's session.

        Returns an empty summary if no pipeline has been created yet.
        """
        if agent_name not in self._pipelines:
            return {
                "total_calls": 0,
                "blocked_count": 0,
                "error_count": 0,
                "risk_distribution": {},
                "top_blocked_reasons": {},
                "tools_used": {},
                "session_duration_seconds": 0.0,
            }
        return self._pipelines[agent_name].get_audit_summary()

    def get_all_audit_summaries(self) -> dict[str, dict[str, Any]]:
        """Get audit summaries for all agents that have active pipelines."""
        return {
            name: self.get_audit_summary(name)
            for name in self._profiles
        }

    def list_agents(self) -> list[dict[str, Any]]:
        """Return a summary list of all registered agents."""
        result = []
        for name, profile in self._profiles.items():
            result.append({
                "name": name,
                "role": profile.role,
                "max_risk_level": profile.max_risk_level,
                "allowed_tools": profile.allowed_tools,
                "denied_tools": profile.denied_tools,
                "has_pipeline": name in self._pipelines,
                "metadata": profile.metadata,
            })
        return result

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> MultiAgentGovernor:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Agent Fork Governance
    # ------------------------------------------------------------------

    def fork_agent(
        self,
        parent_name: str,
        fork_name: str | None = None,
        *,
        restrict_tools: list[str] | None = None,
        max_risk_level: str | None = None,
        session_id: str | None = None,
    ) -> ToolGovernancePipeline:
        """Create a forked sub-agent with governance no weaker than the parent.

        Fork semantics:
        - Fork inherits parent's governance configuration
        - Fork permissions are a subset of parent (can only restrict, never expand)
        - Fork gets an isolated audit trail (sidechain by agent ID)
        - Recursive fork prevention (max depth tracked)

        Parameters
        ----------
        parent_name : str
            The registered parent agent to fork from.
        fork_name : str | None
            Name for the forked agent. Auto-generated if None.
        restrict_tools : list[str] | None
            Further restrict tools beyond parent's whitelist.
        max_risk_level : str | None
            Further restrict risk level (cannot exceed parent's).
        session_id : str | None
            Override the auto-generated session ID.

        Returns
        -------
        ToolGovernancePipeline
            A pipeline for the forked agent with >= parent governance.

        Raises
        ------
        KeyError
            If parent is not registered.
        ValueError
            If fork attempts to expand permissions beyond parent.
        """
        parent_profile = self.get_profile(parent_name)

        # Generate fork name
        actual_fork_name = fork_name or f"{parent_name}_fork_{uuid.uuid4().hex[:6]}"

        # Compute forked tool set — intersection with parent (can only shrink)
        forked_tools = parent_profile.allowed_tools
        if restrict_tools is not None:
            if forked_tools is not None:
                # Intersection: fork can't have tools parent doesn't have
                forked_tools = [t for t in restrict_tools if t in set(forked_tools)]
            else:
                forked_tools = restrict_tools

        # Compute forked risk level — minimum of parent and requested
        forked_risk = parent_profile.max_risk_level
        if max_risk_level is not None:
            if _risk_level_value(max_risk_level) > _risk_level_value(forked_risk):
                raise ValueError(
                    f"Fork cannot expand risk level beyond parent. "
                    f"Parent max: {forked_risk}, requested: {max_risk_level}"
                )
            forked_risk = max_risk_level

        # Create fork profile
        fork_profile = AgentProfile(
            name=actual_fork_name,
            role=f"fork_of_{parent_profile.role}",
            allowed_tools=forked_tools,
            denied_tools=parent_profile.denied_tools,
            constitution_override=parent_profile.constitution_override,
            max_risk_level=forked_risk,
            metadata={
                **parent_profile.metadata,
                "_parent": parent_name,
                "_fork": True,
                "description": f"Fork of {parent_name} (restricted)",
            },
        )

        # Register and get pipeline
        self.register_agent(actual_fork_name, fork_profile)
        pipeline = self.get_pipeline(actual_fork_name, session_id=session_id)

        logger.info(
            "Forked agent '%s' from '%s' (tools=%s, risk=%s)",
            actual_fork_name,
            parent_name,
            forked_tools,
            forked_risk,
        )

        return pipeline

    def is_fork(self, agent_name: str) -> bool:
        """Check if an agent is a fork of another agent."""
        profile = self._profiles.get(agent_name)
        if profile is None:
            return False
        return bool(profile.metadata.get("_fork", False))

    def get_fork_parent(self, agent_name: str) -> str | None:
        """Get the parent agent name for a fork, or None."""
        profile = self._profiles.get(agent_name)
        if profile is None:
            return None
        return profile.metadata.get("_parent")

    def close(self) -> None:
        """Close all cached pipelines and release resources."""
        for name, pipeline in self._pipelines.items():
            try:
                pipeline.audit_engine.close()
            except Exception:
                logger.debug("Error closing pipeline for agent '%s'", name)
        self._pipelines.clear()

    def __repr__(self) -> str:
        agents = ", ".join(
            f"{n}({p.role})" for n, p in self._profiles.items()
        )
        return f"<MultiAgentGovernor agents=[{agents}]>"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _merge_overrides(
    parent: dict[str, Any] | None,
    child: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge two constitution override dicts (child wins)."""
    if parent is None and child is None:
        return None
    if parent is None:
        return child
    if child is None:
        return parent

    # Deep merge
    result = copy.deepcopy(parent)
    for key, value in child.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_overrides(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
