"""Pre-built constitution templates for the init wizard.

Three security tiers — Minimal, Standard, Strict — each using template
variables ``{project_name}`` and ``{project_type}`` that are substituted
at generation time.
"""

from __future__ import annotations

MINIMAL_CONSTITUTION = """\
version: "1.0"
identity:
  name: "{project_name}"
  description: "Minimal governance for {project_type} project"
rules:
  - id: no-secrets
    description: "Never expose API keys or secrets in output"
    severity: error
    enforcement: both
permissions:
  defaults:
    unknown_tool: ask
  tools:
    bash:
      policy: allow
    read:
      policy: allow
    write:
      policy: allow
    edit:
      policy: allow
"""

STANDARD_CONSTITUTION = """\
version: "1.0"
identity:
  name: "{project_name}"
  description: "Standard governance for {project_type} project"
rules:
  - id: no-secrets
    description: "Never expose API keys, tokens, or credentials"
    severity: error
    enforcement: both
  - id: no-destructive-commands
    description: "Block destructive shell commands (rm -rf /, sudo, etc.)"
    severity: error
    enforcement: hook
  - id: confirm-external
    description: "Require confirmation for network requests and git push"
    severity: warning
    enforcement: hook
  - id: no-env-modification
    description: "Do not modify .env or credential files"
    severity: error
    enforcement: hook
permissions:
  defaults:
    unknown_tool: ask
    unknown_path: deny
  tools:
    bash:
      policy: restricted
      deny_patterns:
        - "rm\\\\s+-rf\\\\s+/"
        - "sudo\\\\s+"
        - "curl.*\\\\|.*sh"
      ask_patterns:
        - "git\\\\s+push"
        - "npm\\\\s+publish"
    read:
      policy: allow
    write:
      policy: restricted
      deny_paths: [".env", ".env.*", "credentials.*", "*.pem", "*.key"]
      ask_paths: ["package.json", "pyproject.toml", "Dockerfile"]
    edit:
      policy: restricted
      deny_paths: [".env", "credentials.*"]
risk:
  classifier: rules
  thresholds:
    low: allow
    medium: allow
    high: ask
    critical: deny
hooks:
  profile: standard
audit:
  enabled: true
  format: jsonl
"""

STRICT_CONSTITUTION = """\
version: "1.0"
identity:
  name: "{project_name}"
  description: "Strict governance for {project_type} project"
  boundaries:
    - "Only modify files within the project directory"
    - "Never access network without explicit approval"
    - "All file writes require confirmation"
rules:
  - id: no-secrets
    description: "Never expose API keys, tokens, or credentials"
    severity: error
    enforcement: both
  - id: no-destructive-commands
    description: "Block all destructive shell commands"
    severity: error
    enforcement: hook
  - id: confirm-all-writes
    description: "Require confirmation for all file modifications"
    severity: warning
    enforcement: hook
  - id: no-network-without-approval
    description: "Block network access without explicit approval"
    severity: error
    enforcement: hook
  - id: no-env-modification
    description: "Never modify environment or credential files"
    severity: error
    enforcement: hook
  - id: no-config-weakening
    description: "Do not modify linter or formatter configurations"
    severity: warning
    enforcement: hook
  - id: path-boundary
    description: "Stay within project directory boundaries"
    severity: error
    enforcement: hook
permissions:
  defaults:
    unknown_tool: deny
    unknown_path: deny
    on_error: deny
  tools:
    bash:
      policy: restricted
      deny_patterns:
        - "rm\\\\s+-rf"
        - "sudo"
        - "curl.*\\\\|.*sh"
        - "wget.*\\\\|.*sh"
        - "chmod\\\\s+777"
        - "pkill|kill\\\\s+-9"
      ask_patterns:
        - "git\\\\s+(push|reset|rebase)"
        - "npm\\\\s+(publish|unpublish)"
        - "pip\\\\s+install"
        - "curl|wget|fetch"
    read:
      policy: allow
    write:
      policy: restricted
      deny_paths: [".env", ".env.*", "credentials.*", "*.pem", "*.key", ".ssh/*"]
      ask_paths: ["*"]
    edit:
      policy: restricted
      deny_paths: [".env", "credentials.*", ".eslintrc*", ".prettierrc*", "tsconfig.json"]
      ask_paths: ["*"]
risk:
  classifier: rules
  thresholds:
    low: allow
    medium: ask
    high: ask
    critical: deny
hooks:
  profile: strict
audit:
  enabled: true
  format: jsonl
"""

# Map security level names to their templates
SECURITY_TEMPLATES = {
    "minimal": MINIMAL_CONSTITUTION,
    "standard": STANDARD_CONSTITUTION,
    "strict": STRICT_CONSTITUTION,
}

# Agent type descriptions (used in the generated example script)
AGENT_TYPES = {
    "coding": "Coding assistant",
    "rag": "RAG chatbot",
    "pipeline": "Data pipeline",
    "custom": "Custom agent",
}

# LLM provider choices
LLM_PROVIDERS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "both": "Both Anthropic & OpenAI",
}


def render_constitution(
    template: str,
    project_name: str,
    project_type: str,
) -> str:
    """Substitute template variables into a constitution template.

    Args:
        template: Raw constitution YAML with ``{project_name}`` / ``{project_type}`` placeholders.
        project_name: The project name to inject.
        project_type: The detected or chosen project type string.

    Returns:
        The rendered YAML string ready to write to disk.
    """
    return template.replace("{project_name}", project_name).replace(
        "{project_type}", project_type
    )


def get_example_script(
    project_name: str,
    agent_type: str,
    llm_provider: str,
) -> str:
    """Generate a starter example script tailored to user choices.

    Args:
        project_name: Name of the project.
        agent_type: One of the AGENT_TYPES keys.
        llm_provider: One of the LLM_PROVIDERS keys.

    Returns:
        Python source code as a string.
    """
    provider_import = ""
    provider_setup = ""
    if llm_provider == "anthropic":
        provider_import = "# pip install anthropic\n# import anthropic"
        provider_setup = '# client = anthropic.Anthropic()'
    elif llm_provider == "openai":
        provider_import = "# pip install openai\n# import openai"
        provider_setup = '# client = openai.OpenAI()'
    else:
        provider_import = (
            "# pip install anthropic openai\n"
            "# import anthropic\n"
            "# import openai"
        )
        provider_setup = (
            '# anthropic_client = anthropic.Anthropic()\n'
            '# openai_client = openai.OpenAI()'
        )

    agent_comment = {
        "coding": "# This agent assists with code generation, review, and refactoring.",
        "rag": "# This agent answers questions using retrieved context from a knowledge base.",
        "pipeline": "# This agent orchestrates data processing pipelines with safety guardrails.",
        "custom": "# Customize this agent for your specific use case.",
    }.get(agent_type, "# Custom agent")

    return f'''\
#!/usr/bin/env python3
"""AutoHarness starter — {project_name}

{agent_comment.lstrip("# ")}

Generated by `autoharness init`.
"""

from autoharness import Constitution, ToolGovernancePipeline
from autoharness.core.types import ToolCall

{provider_import}


def main() -> None:
    # Load the constitution (auto-discovers constitution.yaml)
    constitution = Constitution.discover()
    pipeline = ToolGovernancePipeline(constitution)

    {provider_setup}

    # Example: evaluate a tool call through the governance pipeline
    call = ToolCall(
        tool_name="Bash",
        tool_input={{"command": "echo Hello from {project_name}"}},
    )

    result = pipeline.process(call)
    print(f"Status: {{result.status}}")
    print(f"Output: {{result.output}}")


if __name__ == "__main__":
    main()
'''
