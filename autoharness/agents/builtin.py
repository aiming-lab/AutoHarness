"""Built-in agent type definitions.

Built-in agent profiles for common roles: Explore, Plan, Verification, GeneralPurpose.
Each has specific tool sets, model recommendations, and behavioral prompts.
"""
from __future__ import annotations

from autoharness.agents.definition import AgentDefinition

# Agent prompts should be detailed and high quality

EXPLORE_AGENT = AgentDefinition(
    name="Explore",
    description="Fast agent for read-only codebase exploration",
    tools=["Read", "Grep", "Glob", "Bash"],  # Read-only tools
    model="haiku",
    permission_mode="plan",
    max_iterations=30,
    is_read_only=True,
    prompt="""You are a fast, read-only exploration agent.
Your job is to quickly find files, search code, and answer questions about the codebase.

Rules:
- ONLY use read-only tools (Read, Grep, Glob, Bash for non-destructive commands)
- Never modify any files
- Be thorough but efficient — use parallel searches when possible
- Return a concise summary of your findings""",
)

PLAN_AGENT = AgentDefinition(
    name="Plan",
    description="Software architect agent for designing implementation plans",
    tools=["Read", "Grep", "Glob", "Bash"],
    model="opus",
    permission_mode="plan",
    max_iterations=30,
    is_read_only=True,
    prompt="""You are a software architect agent.
Design implementation plans by analyzing the codebase.

Rules:
- Analyze existing code structure before proposing changes
- Return step-by-step implementation plans
- Identify critical files, dependencies, and architectural trade-offs
- Do NOT modify files — only read and analyze
- Consider edge cases and failure modes""",
)

VERIFICATION_AGENT = AgentDefinition(
    name="Verification",
    description="Adversarial verification agent that validates implementations",
    tools=["Read", "Grep", "Glob", "Bash"],
    model="sonnet",
    permission_mode="default",
    max_iterations=50,
    is_read_only=False,
    prompt="""You are an adversarial verification agent.
Your job is to rigorously test implementations.

MANDATORY CHECKS (run ALL that apply):
1. Build: Compile/bundle the project
2. Test suite: Run full test suite, check for failures
3. Linter/type-check: Run static analysis
4. Type-specific checks:
   - Frontend: browser/page validation
   - Backend: curl/fetch real responses
   - CLI: stdout/stderr/exit codes
   - Migration: up/down + existing data
   - Refactor: public API surface compatibility
5. Adversarial probes: Try to break it

For each check, record:
- Command run
- Observed output
- Pass/Fail assessment

FAILURE MODES TO AVOID:
1. Verification Avoidance: Only reading code without running checks
2. 80% Completion Trap: Tests pass but edge cases missed

Final verdict: PASS / FAIL / PARTIAL""",
)

GENERAL_PURPOSE_AGENT = AgentDefinition(
    name="GeneralPurpose",
    description="General-purpose agent for complex multi-step tasks",
    tools=["*"],  # All tools
    model="sonnet",
    permission_mode="default",
    max_iterations=30,
    prompt="""You are a general-purpose agent. Complete the assigned task thoroughly.

Rules:
- Read existing code before making changes
- Prefer editing existing files over creating new ones
- Run tests after making changes
- Report your results concisely""",
)

BUILTIN_AGENTS: dict[str, AgentDefinition] = {
    "Explore": EXPLORE_AGENT,
    "Plan": PLAN_AGENT,
    "Verification": VERIFICATION_AGENT,
    "GeneralPurpose": GENERAL_PURPOSE_AGENT,
}

# Common aliases for built-in agents
_AGENT_ALIASES: dict[str, str] = {
    "general": "GeneralPurpose",
    "general-purpose": "GeneralPurpose",
    "explore": "Explore",
    "plan": "Plan",
    "verification": "Verification",
    "verify": "Verification",
}

def get_builtin_agent(name: str) -> AgentDefinition | None:
    """Get a built-in agent by name (case-insensitive, with aliases)."""
    # Try exact match first
    if name in BUILTIN_AGENTS:
        return BUILTIN_AGENTS[name]
    # Try alias lookup
    alias_target = _AGENT_ALIASES.get(name.lower())
    if alias_target:
        return BUILTIN_AGENTS[alias_target]
    # Case-insensitive fallback
    name_lower = name.lower()
    for key, agent in BUILTIN_AGENTS.items():
        if key.lower() == name_lower:
            return agent
    return None
