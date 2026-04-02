# AutoHarness OPA Policy — Example Rego Policy for Tool Governance
#
# Deploy to OPA at path: autoharness/allow
# Query endpoint: POST /v1/data/autoharness/allow
#
# Input schema (from AutoHarness PolicyEngineAdapter._build_input_payload):
#   {
#     "tool_name": "bash",
#     "tool_input": {"command": "rm -rf /tmp/cache"},
#     "risk_level": "medium",
#     "risk_reason": "Destructive bash command",
#     "risk_confidence": 0.95,
#     "session_id": "abc-123",
#     "agent_role": "coder",
#     "project_dir": "/home/user/project",
#     "timestamp": "2026-03-31T12:00:00Z"
#   }
#
# Output schema (expected by AutoHarness OPAIntegration):
#   {
#     "decision": "allow" | "deny" | "ask",
#     "reason": "Human-readable explanation"
#   }

package autoharness.allow

import rego.v1

# Default decision: ask (require human confirmation for unmatched cases)
default decision := {"decision": "ask", "reason": "No matching policy — requires human review"}

# --- Role-based access control ---

# Reviewer agents can only use read-only tools
decision := {"decision": "deny", "reason": "Reviewer agents cannot use write tools"} if {
    input.agent_role == "reviewer"
    input.tool_name in {"bash", "write", "Write", "edit", "Edit", "file_write"}
}

# Planner agents are read-only
decision := {"decision": "deny", "reason": "Planner agents are read-only"} if {
    input.agent_role == "planner"
    input.tool_name in {"bash", "write", "Write", "edit", "Edit", "file_write"}
}

# --- Risk-based controls ---

# Critical risk is always denied
decision := {"decision": "deny", "reason": sprintf("Critical risk: %s", [input.risk_reason])} if {
    input.risk_level == "critical"
}

# High risk requires confirmation
decision := {"decision": "ask", "reason": sprintf("High risk requires confirmation: %s", [input.risk_reason])} if {
    input.risk_level == "high"
}

# --- Destructive command patterns ---

# Block rm -rf on system directories
decision := {"decision": "deny", "reason": "Destructive command targeting system directory"} if {
    input.tool_name == "bash"
    command := input.tool_input.command
    regex.match(`rm\s+-rf?\s+/(?:usr|etc|var|home|opt|boot)`, command)
}

# Block force pushes to main/master
decision := {"decision": "deny", "reason": "Force push to protected branch is blocked"} if {
    input.tool_name == "bash"
    command := input.tool_input.command
    regex.match(`git\s+push\s+.*--force.*\s+(main|master)`, command)
}

# --- Secret protection ---

# Block commits of .env files
decision := {"decision": "deny", "reason": "Cannot commit .env files — they may contain secrets"} if {
    input.tool_name == "bash"
    command := input.tool_input.command
    regex.match(`git\s+add\s+.*\.env`, command)
}

# --- Path-based controls ---

# Block writes outside project directory
decision := {"decision": "deny", "reason": sprintf("Write outside project dir: %s", [path])} if {
    input.tool_name in {"write", "Write", "edit", "Edit", "file_write"}
    path := input.tool_input.file_path
    not startswith(path, input.project_dir)
    not startswith(path, "/tmp")
}

# --- Time-based controls (example: restrict after hours) ---

# Deny high-risk operations outside business hours (UTC)
# Uncomment to enable:
# decision := {"decision": "deny", "reason": "High-risk operations restricted outside business hours"} if {
#     input.risk_level in {"high", "critical"}
#     time.now_ns() # Use OPA's time functions for hour-based checks
# }

# --- Allow low-risk, read-only operations ---

decision := {"decision": "allow", "reason": "Low-risk read operation allowed"} if {
    input.risk_level in {"low", "medium"}
    input.tool_name in {"read", "Read", "grep", "Grep", "glob", "Glob", "search"}
}

# Allow coder agents for medium-risk operations
decision := {"decision": "allow", "reason": "Coder agent allowed for medium-risk operations"} if {
    input.agent_role == "coder"
    input.risk_level in {"low", "medium"}
}

# Allow executor agents for low-risk operations
decision := {"decision": "allow", "reason": "Executor agent allowed for low-risk operations"} if {
    input.agent_role == "executor"
    input.risk_level == "low"
}
