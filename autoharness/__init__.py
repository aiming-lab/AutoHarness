"""AutoHarness -- Behavioral governance middleware for AI agents."""

# --- Core (existing) ---
# --- Agent Loop (integration layer) ---
from autoharness.agent_loop import AgentLoop
from autoharness.agents.builtin import get_builtin_agent

# --- Agents ---
from autoharness.agents.definition import AgentDefinition
from autoharness.agents.fork import build_forked_messages
from autoharness.agents.model_router import ModelRouter, ModelTier
from autoharness.context.artifacts import ArtifactHandle, ArtifactStore
from autoharness.context.autocompact import AutoCompactor
from autoharness.context.microcompact import microcompact

# --- Context ---
from autoharness.context.tokens import TokenBudget

# --- Core (new) ---
from autoharness.core.anti_distillation import (
    DecoyToolGenerator,
    generate_decoy_tools,
    inject_decoys,
    is_decoy_tool,
)
from autoharness.core.constitution import Constitution
from autoharness.core.feature_flags import FeatureFlags
from autoharness.core.hooks import HookRegistry, hook
from autoharness.core.multi_agent import AgentProfile, MultiAgentGovernor
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.sentiment import (
    FrustrationLevel,
    FrustrationSignal,
    detect_frustration,
)
from autoharness.core.types import CompactionMode, HookResult, PipelineMode

# --- Observability ---
from autoharness.observability.cost_attribution import CostReport, CostTracker

# --- Prompt ---
from autoharness.prompt.sections import (
    SystemPromptRegistry,
    system_prompt_section,
)
from autoharness.session.cost import SessionCost

# --- Session ---
from autoharness.session.persistence import SessionState
from autoharness.session.progress import ProgressTracker
from autoharness.session.transcript import TranscriptWriter
from autoharness.skills.frontmatter import ParsedSkill

# --- Skills ---
from autoharness.skills.loader import SkillRegistry
from autoharness.tools.orchestrator import ToolOrchestrator

# --- Tools ---
from autoharness.tools.registry import ToolDefinition, ToolRegistry

# --- Validation ---
from autoharness.validation.rails import RailResult, ValidationPipeline
from autoharness.wrap import AutoHarness, lint_tool_call

__version__ = "0.1.0"

__all__ = [
    # Agents
    "AgentDefinition",
    # Agent Loop
    "AgentLoop",
    "AgentProfile",
    "ArtifactHandle",
    # Artifacts
    "ArtifactStore",
    "AutoCompactor",
    # Core
    "AutoHarness",
    "CompactionMode",
    "Constitution",
    "CostReport",
    # Cost Attribution
    "CostTracker",
    # Anti-distillation
    "DecoyToolGenerator",
    # Feature flags
    "FeatureFlags",
    # Sentiment
    "FrustrationLevel",
    "FrustrationSignal",
    "HookRegistry",
    "HookResult",
    "ModelRouter",
    "ModelTier",
    "MultiAgentGovernor",
    "ParsedSkill",
    "PipelineMode",
    # Progress
    "ProgressTracker",
    "RailResult",
    "SessionCost",
    # Session
    "SessionState",
    # Skills
    "SkillRegistry",
    # Prompt
    "SystemPromptRegistry",
    # Context
    "TokenBudget",
    # Tools
    "ToolDefinition",
    "ToolGovernancePipeline",
    "ToolOrchestrator",
    "ToolRegistry",
    "TranscriptWriter",
    # Validation
    "ValidationPipeline",
    "build_forked_messages",
    "detect_frustration",
    "generate_decoy_tools",
    "get_builtin_agent",
    "hook",
    "inject_decoys",
    "is_decoy_tool",
    "lint_tool_call",
    "microcompact",
    "system_prompt_section",
]
