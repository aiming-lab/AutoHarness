// AutoHarness Cedar Policy — Example AWS Verified Permissions Policies
//
// These policies define tool governance for AI agents using the Cedar
// policy language (https://www.cedarpolicy.com/).
//
// Entity model:
//   Principal: AutoHarness::Agent     (entityId = agent role name)
//   Action:    AutoHarness::Action    (actionId = tool name)
//   Resource:  AutoHarness::ToolCall  (entityId = session ID)
//
// Context attributes (from AutoHarness CedarIntegration._build_cedar_context):
//   risk_level:      string  ("low", "medium", "high", "critical")
//   risk_confidence: string  (float as string, e.g., "0.95")
//   risk_reason:     string  (human-readable explanation)
//   tool_name:       string  (canonical tool name)
//   project_dir:     string  (project root path)
//   input_*:         varies  (selected tool_input keys, prefixed with "input_")

// ============================================================================
// FORBID policies (deny takes precedence over permit in Cedar)
// ============================================================================

// Block all agents from critical-risk operations
forbid (
    principal,
    action,
    resource
)
when {
    context.risk_level == "critical"
};

// Reviewer agents cannot use write tools
forbid (
    principal == AutoHarness::Agent::"reviewer",
    action in [
        AutoHarness::Action::"bash",
        AutoHarness::Action::"write",
        AutoHarness::Action::"Write",
        AutoHarness::Action::"edit",
        AutoHarness::Action::"Edit",
        AutoHarness::Action::"file_write"
    ],
    resource
);

// Planner agents cannot use write or execute tools
forbid (
    principal == AutoHarness::Agent::"planner",
    action in [
        AutoHarness::Action::"bash",
        AutoHarness::Action::"Bash",
        AutoHarness::Action::"write",
        AutoHarness::Action::"Write",
        AutoHarness::Action::"edit",
        AutoHarness::Action::"Edit",
        AutoHarness::Action::"file_write",
        AutoHarness::Action::"file_edit"
    ],
    resource
);

// Block high-risk operations for executor agents
forbid (
    principal == AutoHarness::Agent::"executor",
    action,
    resource
)
when {
    context.risk_level == "high"
};

// ============================================================================
// PERMIT policies
// ============================================================================

// Allow all agents to use read-only tools at low risk
permit (
    principal,
    action in [
        AutoHarness::Action::"read",
        AutoHarness::Action::"Read",
        AutoHarness::Action::"grep",
        AutoHarness::Action::"Grep",
        AutoHarness::Action::"glob",
        AutoHarness::Action::"Glob",
        AutoHarness::Action::"search"
    ],
    resource
)
when {
    context.risk_level == "low"
};

// Coder agents can use all tools at low and medium risk
permit (
    principal == AutoHarness::Agent::"coder",
    action,
    resource
)
when {
    context.risk_level == "low" || context.risk_level == "medium"
};

// Executor agents can use write tools at low risk
permit (
    principal == AutoHarness::Agent::"executor",
    action in [
        AutoHarness::Action::"bash",
        AutoHarness::Action::"Bash",
        AutoHarness::Action::"write",
        AutoHarness::Action::"Write",
        AutoHarness::Action::"edit",
        AutoHarness::Action::"Edit",
        AutoHarness::Action::"read",
        AutoHarness::Action::"Read",
        AutoHarness::Action::"grep",
        AutoHarness::Action::"Grep",
        AutoHarness::Action::"glob",
        AutoHarness::Action::"Glob"
    ],
    resource
)
when {
    context.risk_level == "low"
};

// Reviewer agents can read at low and medium risk
permit (
    principal == AutoHarness::Agent::"reviewer",
    action in [
        AutoHarness::Action::"read",
        AutoHarness::Action::"Read",
        AutoHarness::Action::"grep",
        AutoHarness::Action::"Grep",
        AutoHarness::Action::"glob",
        AutoHarness::Action::"Glob",
        AutoHarness::Action::"search"
    ],
    resource
)
when {
    context.risk_level == "low" || context.risk_level == "medium"
};
