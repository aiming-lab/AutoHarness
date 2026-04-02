"""Multi-axis risk scoring — 4-dimensional risk assessment.

Axes: base_risk + file_sensitivity + blast_radius + irreversibility
Composite score maps to actions: allow/review/require_confirmation/block
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Base risk levels by tool category
TOOL_BASE_RISK: dict[str, float] = {
    "bash": 0.7, "write": 0.5, "edit": 0.4, "read": 0.1,
    "grep": 0.05, "glob": 0.05, "web_fetch": 0.3, "web_search": 0.2,
    "agent": 0.3, "skill": 0.1,
}

# Sensitive file patterns
SENSITIVE_FILES = {
    ".env": 0.9, ".env.local": 0.9, "credentials.json": 0.95,
    ".ssh/": 0.95, "id_rsa": 1.0, ".aws/": 0.9,
    "secrets.yaml": 0.9, ".npmrc": 0.7, ".pypirc": 0.7,
}

@dataclass
class MultiAxisRisk:
    """4-axis risk assessment result."""
    base_risk: float = 0.0
    file_sensitivity: float = 0.0
    blast_radius: float = 0.0
    irreversibility: float = 0.0

    @property
    def composite(self) -> float:
        return (self.base_risk + self.file_sensitivity +
                self.blast_radius + self.irreversibility) / 4

    @property
    def action(self) -> Literal["allow", "review", "require_confirmation", "block"]:
        score = self.composite
        if score >= 0.75:
            return "block"
        if score >= 0.50:
            return "require_confirmation"
        if score >= 0.25:
            return "review"
        return "allow"

def assess_risk(
    tool_name: str,
    file_path: str | None = None,
    command: str | None = None,
) -> MultiAxisRisk:
    """Compute multi-axis risk for a tool invocation."""
    base = TOOL_BASE_RISK.get(tool_name.lower(), 0.3)

    file_sens = 0.0
    if file_path:
        from pathlib import PurePosixPath
        name = PurePosixPath(file_path).name
        for pattern, score in SENSITIVE_FILES.items():
            if pattern in file_path or name == pattern:
                file_sens = max(file_sens, score)

    blast = 0.0
    if command:
        cmd_lower = command.lower()
        if any(kw in cmd_lower for kw in ["push", "deploy", "publish", "release"]):
            blast = 0.8
        elif any(kw in cmd_lower for kw in ["install", "pip", "npm", "apt"]):
            blast = 0.5
        elif any(kw in cmd_lower for kw in ["curl", "wget", "fetch"]):
            blast = 0.4

    irrev = 0.0
    if command:
        cmd_lower = command.lower()
        if any(kw in cmd_lower for kw in ["rm -rf", "drop table", "format", "fdisk"]):
            irrev = 1.0
        elif any(kw in cmd_lower for kw in ["rm ", "delete", "truncate"]):
            irrev = 0.7
        elif any(kw in cmd_lower for kw in ["git reset --hard", "git push --force"]):
            irrev = 0.8
        elif any(kw in cmd_lower for kw in ["mv ", "rename"]):
            irrev = 0.3

    return MultiAxisRisk(
        base_risk=base,
        file_sensitivity=file_sens,
        blast_radius=blast,
        irreversibility=irrev,
    )
