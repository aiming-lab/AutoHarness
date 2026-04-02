"""Shared fixtures for AutoHarness test suite."""

from __future__ import annotations

import pytest

from autoharness.core.constitution import Constitution
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.core.types import (
    PermissionDecision,
    RiskAssessment,
    RiskLevel,
    ToolCall,
)


@pytest.fixture
def default_constitution() -> Constitution:
    """Return a default Constitution instance."""
    return Constitution.default()


@pytest.fixture
def default_pipeline(tmp_path) -> ToolGovernancePipeline:
    """Return a ToolGovernancePipeline with default constitution, audit in tmp_path."""
    constitution = Constitution.default()
    pipeline = ToolGovernancePipeline(
        constitution=constitution,
        project_dir=str(tmp_path),
        session_id="test-session",
    )
    return pipeline


@pytest.fixture
def safe_tool_call() -> ToolCall:
    """A safe bash tool call (git status)."""
    return ToolCall(tool_name="bash", tool_input={"command": "git status"})


@pytest.fixture
def dangerous_tool_call() -> ToolCall:
    """A dangerous bash tool call (rm -rf /)."""
    return ToolCall(tool_name="bash", tool_input={"command": "rm -rf /"})


@pytest.fixture
def secret_tool_call() -> ToolCall:
    """A tool call containing a secret."""
    return ToolCall(
        tool_name="bash",
        tool_input={"command": "echo sk-abc12345678901234567890"},
    )


@pytest.fixture
def low_risk() -> RiskAssessment:
    """A low-risk assessment."""
    return RiskAssessment(level=RiskLevel.low, classifier="rules", reason="Safe")


@pytest.fixture
def allow_decision() -> PermissionDecision:
    """An allow permission decision."""
    return PermissionDecision(action="allow", reason="Allowed", source="test")
