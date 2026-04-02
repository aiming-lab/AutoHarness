"""AutoHarness CLI — governance at your fingertips.

Beautiful command-line interface for managing AI agent behavioral
constitutions, checking tool calls, auditing governance decisions,
and integrating with development tools.

Usage:
    autoharness init [--template NAME]
    autoharness check [--stdin] [--constitution PATH] [--format FORMAT]
    autoharness audit summary|report|check|clean
    autoharness install [--target TARGET]
    autoharness validate [PATH]
    autoharness version
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.tree import Tree

import autoharness
from autoharness.core.audit import AuditEngine
from autoharness.core.constitution import Constitution, ConstitutionError

console = Console(stderr=True)
out = Console()  # stdout for data output

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATES = {
    "default": "A well-rounded constitution with essential safety rules and sensible defaults.",
    "minimal": "Bare essentials only — fastest path to governance.",
    "strict": "Maximum enforcement — all rules block, all tools audited.",
    "soc2": "SOC 2 compliance-oriented: audit everything, restrict destructive ops.",
    "hipaa": "HIPAA-aware: PHI path protection, strict access controls.",
    "financial": "Financial services: PCI-DSS patterns, transaction safety.",
}


def _get_template_path(name: str) -> Path:
    """Resolve a built-in template by name."""
    templates_dir = Path(__file__).parent.parent / "templates"
    path = templates_dir / f"{name}.yaml"
    return path


def _load_template(name: str) -> str:
    """Load a built-in template's content, falling back to default."""
    path = _get_template_path(name)
    if path.exists():
        return path.read_text(encoding="utf-8")

    # For templates not yet shipped, generate from default constitution
    if name == "strict":
        return _generate_strict_template()
    elif name == "soc2":
        return _generate_compliance_template("soc2")
    elif name == "hipaa":
        return _generate_compliance_template("hipaa")
    elif name == "financial":
        return _generate_compliance_template("financial")

    # Ultimate fallback
    default_path = _get_template_path("default")
    if default_path.exists():
        return default_path.read_text(encoding="utf-8")
    return _generate_default_from_code()


def _generate_default_from_code() -> str:
    """Generate default YAML from the Constitution.default() method."""
    import yaml
    c = Constitution.default()
    data = c.config.model_dump(mode="json")
    result: str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return result


def _generate_strict_template() -> str:
    """Generate a strict template with maximum enforcement."""
    return """\
version: "1.0"
identity:
  name: my-project
  description: "Strict governance — all rules enforced via hooks"
  boundaries:
    - "All destructive operations are blocked without exception"
    - "All tool calls are audited"
    - "No secrets may appear in any output"

rules:
  - id: no-over-engineering
    description: "Prefer simple, minimal solutions"
    severity: error
    enforcement: hook

  - id: confirm-destructive-ops
    description: "Block all destructive operations (delete, drop, reset, force-push)"
    severity: error
    enforcement: hook
    triggers:
      - tool: Bash
        pattern: "rm\\\\s+-rf|git\\\\s+push.*--force|git\\\\s+reset\\\\s+--hard|DROP\\\\s+TABLE"

  - id: no-config-weakening
    description: "Never disable safety features or skip hooks"
    severity: error
    enforcement: hook
    triggers:
      - tool: Bash
        pattern: "--no-verify|--insecure|disable_ssl|--skip-hooks"

  - id: no-secret-exposure
    description: "Block any content containing secrets or credentials"
    severity: error
    enforcement: hook

  - id: sensitive-path-guard
    description: "Block reads/writes to sensitive paths"
    severity: error
    enforcement: hook

permissions:
  defaults:
    unknown_tool: deny
    unknown_path: deny
    on_error: deny
  tools:
    Bash:
      policy: restricted
      deny_patterns:
        - "rm -rf /"
        - "rm -rf ~"
        - "mkfs.*"
        - "dd if=.*of=/dev/"
        - ":(){ :|:& };:"
        - "chmod -R 777 /"
        - "curl.*|.*sh"
        - "wget.*|.*sh"
        - "git push.*--force.*(main|master)"
        - "git reset --hard"
    Edit:
      policy: restricted
      deny_paths:
        - ".env"
        - ".env.*"
        - ".ssh/*"
        - "*.pem"
        - "*.key"
        - "credentials.json"
    Read:
      policy: allow

risk:
  classifier: rules
  thresholds:
    low: allow
    medium: ask
    high: deny
    critical: deny

hooks:
  profile: strict

audit:
  enabled: true
  format: jsonl
  output: .autoharness/audit.jsonl
  retention_days: 365
  include:
    - tool_call
    - tool_blocked
    - tool_error
    - hook_fired
    - permission_check
"""


def _generate_compliance_template(flavor: str) -> str:
    """Generate a compliance-oriented template."""
    names = {"soc2": "SOC 2", "hipaa": "HIPAA", "financial": "Financial / PCI-DSS"}
    label = names.get(flavor, flavor.upper())

    extra_rules = ""
    extra_paths = ""

    if flavor == "hipaa":
        extra_rules = """
  - id: phi-protection
    description: "Protect paths containing PHI (Protected Health Information)"
    severity: error
    enforcement: hook

  - id: access-logging
    description: "All data access must be logged for HIPAA audit trail"
    severity: error
    enforcement: hook
"""
        extra_paths = """
        - "patients/*"
        - "medical_records/*"
        - "phi/*"
        - "*.hl7"
"""
    elif flavor == "soc2":
        extra_rules = """
  - id: change-management
    description: "All infrastructure changes must be audited"
    severity: error
    enforcement: hook

  - id: access-control
    description: "Principle of least privilege for all tool access"
    severity: warning
    enforcement: both
"""
    elif flavor == "financial":
        extra_rules = """
  - id: transaction-safety
    description: "Financial transactions require confirmation"
    severity: error
    enforcement: hook

  - id: pci-path-guard
    description: "Protect paths containing cardholder data"
    severity: error
    enforcement: hook
"""
        extra_paths = """
        - "cardholder/*"
        - "*.pan"
        - "payment/*"
"""

    return f"""\
# {label} Compliance Constitution
# Generated by AutoHarness — customize for your environment

version: "1.0"
identity:
  name: my-project
  description: "{label} compliance governance"
  boundaries:
    - "All operations are audited for compliance"
    - "Destructive operations are blocked"
    - "Sensitive data paths are protected"

rules:
  - id: no-over-engineering
    description: "Prefer simple, minimal solutions"
    severity: warning
    enforcement: prompt

  - id: confirm-destructive-ops
    description: "Block destructive operations without confirmation"
    severity: error
    enforcement: hook

  - id: no-config-weakening
    description: "Never disable safety features"
    severity: error
    enforcement: hook

  - id: no-secret-exposure
    description: "Never expose secrets or credentials"
    severity: error
    enforcement: hook

  - id: sensitive-path-guard
    description: "Protect sensitive filesystem paths"
    severity: error
    enforcement: hook
{extra_rules}
permissions:
  defaults:
    unknown_tool: deny
    unknown_path: deny
    on_error: deny
  tools:
    Bash:
      policy: restricted
      deny_patterns:
        - "rm -rf /"
        - "mkfs.*"
        - "dd if=.*of=/dev/"
        - "git push.*--force.*(main|master)"
        - "git reset --hard"
    Edit:
      policy: restricted
      deny_paths:
        - ".env"
        - ".env.*"
        - ".ssh/*"
        - "*.pem"
        - "*.key"{extra_paths}
    Read:
      policy: allow

risk:
  classifier: rules
  thresholds:
    low: allow
    medium: ask
    high: deny
    critical: deny

hooks:
  profile: strict

audit:
  enabled: true
  format: jsonl
  output: .autoharness/audit.jsonl
  retention_days: 365
  include:
    - tool_call
    - tool_blocked
    - tool_error
    - hook_fired
    - permission_check
"""


# ===================================================================
# CLI Group
# ===================================================================

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AutoHarness -- behavioral governance for AI agents.

    Define rules. Enforce them. Audit everything.
    """
    if ctx.invoked_subcommand is None:
        _print_banner()
        console.print()
        console.print("  Run [bold cyan]autoharness --help[/] for available commands.")
        console.print("  Run [bold cyan]autoharness init[/] to get started.")
        console.print()


def _print_banner() -> None:
    """Display the AutoHarness banner."""
    banner = (
        "[bold white]AutoHarness[/bold white] "
        f"[dim]v{autoharness.__version__}[/dim]\n"
        "[dim]Behavioral governance middleware for AI agents[/dim]"
    )
    console.print(Panel(banner, border_style="cyan", padding=(1, 2)))


# ===================================================================
# autoharness init — interactive project initialization wizard
# ===================================================================


def _detect_project_type(directory: Path) -> dict[str, Any]:
    """Auto-detect project type and environment from filesystem markers.

    Returns a dict with keys: ``project_type``, ``language``, ``has_git``,
    ``git_branch``, ``has_claude``, ``markers`` (list of human-readable
    strings describing what was found).
    """
    info: dict[str, Any] = {
        "project_type": "unknown",
        "language": "unknown",
        "has_git": False,
        "git_branch": None,
        "has_claude": False,
        "markers": [],
    }

    # Language / framework detection (first match wins for primary type)
    if (directory / "package.json").exists():
        info["project_type"] = "node"
        info["language"] = "JavaScript / TypeScript"
        info["markers"].append("package.json found -- Node.js project")
    elif (directory / "pyproject.toml").exists():
        info["project_type"] = "python"
        info["language"] = "Python"
        info["markers"].append("pyproject.toml found -- Python project")
    elif (directory / "setup.py").exists():
        info["project_type"] = "python"
        info["language"] = "Python"
        info["markers"].append("setup.py found -- Python project")
    elif (directory / "requirements.txt").exists():
        info["project_type"] = "python"
        info["language"] = "Python"
        info["markers"].append("requirements.txt found -- Python project")
    elif (directory / "go.mod").exists():
        info["project_type"] = "go"
        info["language"] = "Go"
        info["markers"].append("go.mod found -- Go project")
    elif (directory / "Cargo.toml").exists():
        info["project_type"] = "rust"
        info["language"] = "Rust"
        info["markers"].append("Cargo.toml found -- Rust project")

    # Git detection
    if (directory / ".git").exists():
        info["has_git"] = True
        info["markers"].append("Git repository detected")
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(directory),
                timeout=5,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                info["git_branch"] = branch
                info["markers"].append(f"Current branch: {branch}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Claude Code detection
    if (directory / ".claude").exists() or (directory / "CLAUDE.md").exists():
        info["has_claude"] = True
        info["markers"].append("Claude Code project detected")

    if not info["markers"]:
        info["markers"].append("No specific project markers found")

    return info


def _show_detection_panel(project_info: dict[str, Any]) -> None:
    """Display a Rich panel summarising auto-detected project information."""
    lines: list[str] = []
    for marker in project_info["markers"]:
        lines.append(f"  [green]*[/green] {marker}")
    body = "\n".join(lines) if lines else "  [dim]No project markers detected[/dim]"
    console.print()
    console.print(Panel(
        body,
        title="[bold cyan]Detected project info[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))


def _show_created_files(files: list[str], directories: list[str]) -> None:
    """Display a Rich tree of generated files and directories."""
    tree = Tree("[bold green]Generated files[/bold green]")
    for d in directories:
        tree.add(f"[dim]{d}/[/dim]")
    for f in files:
        tree.add(f"[cyan]{f}[/cyan]")
    console.print()
    console.print(tree)


@cli.command()
@click.option(
    "--template", "-t",
    type=click.Choice(list(TEMPLATES.keys()), case_sensitive=False),
    default=None,
    help="Constitution template to use (legacy; prefer --security).",
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    default="constitution.yaml",
    help="Output file path for the constitution.",
)
@click.option(
    "--non-interactive", is_flag=True, default=False,
    help="Skip interactive prompts; use defaults or flags.",
)
@click.option(
    "--security", "-s",
    type=click.Choice(["minimal", "standard", "strict"], case_sensitive=False),
    default=None,
    help="Security level (minimal / standard / strict).",
)
@click.option(
    "--agent-type",
    type=click.Choice(["coding", "rag", "pipeline", "custom"], case_sensitive=False),
    default=None,
    help="What kind of agent are you building?",
)
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic", "openai", "both"], case_sensitive=False),
    default=None,
    help="Which LLM provider?",
)
@click.option(
    "--session-persistence/--no-session-persistence",
    default=None,
    help="Enable session persistence directory.",
)
@click.option(
    "--cost-tracking/--no-cost-tracking",
    default=None,
    help="Enable cost tracking placeholders.",
)
@click.option(
    "--directory", "-d",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Project directory to initialise (default: current directory).",
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["core", "standard", "enhanced"], case_sensitive=False),
    default=None,
    help="Pipeline mode: core (6-step), standard (8-step), enhanced (14-step, default).",
)
def init(
    template: str | None,
    output: str,
    non_interactive: bool,
    security: str | None,
    agent_type: str | None,
    llm_provider: str | None,
    session_persistence: bool | None,
    cost_tracking: bool | None,
    directory: str,
    mode: str | None,
) -> None:
    """Create a new constitution.yaml with an interactive project wizard.

    Auto-detects your project type, asks a few questions, and generates
    a tailored constitution plus supporting scaffolding.

    \b
    Non-interactive usage:
        autoharness init --security standard --non-interactive
    """
    from autoharness.templates.constitutions import (
        AGENT_TYPES,
        LLM_PROVIDERS,
        SECURITY_TEMPLATES,
        get_example_script,
        render_constitution,
    )

    project_dir = Path(directory).resolve()
    output_path = project_dir / output

    # --- Overwrite check ---------------------------------------------------
    if output_path.exists():
        if non_interactive:
            console.print(
                f"[red]Error:[/] {output_path} already exists. "
                "Use --output to specify a different path."
            )
            raise SystemExit(1)
        if not Confirm.ask(
            f"[yellow]{output_path}[/] already exists. Overwrite?",
            console=console,
        ):
            console.print("[dim]Aborted.[/]")
            raise SystemExit(0)

    # --- Auto-detect project -----------------------------------------------
    project_info = _detect_project_type(project_dir)
    _show_detection_panel(project_info)

    # --- Legacy --template flag: skip wizard, behave like old init ---------
    if template is not None:
        _legacy_init(template, output_path, non_interactive, project_info)
        return

    # --- Interactive prompts (or flag defaults) ----------------------------

    # 1. Agent type
    if agent_type is None and not non_interactive:
        console.print()
        console.print("[bold]What kind of agent are you building?[/]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan bold", min_width=12)
        table.add_column("Description")
        for key, desc in AGENT_TYPES.items():
            table.add_row(key, desc)
        console.print(table)
        agent_type = Prompt.ask(
            "Agent type",
            choices=list(AGENT_TYPES.keys()),
            default="coding",
            console=console,
        )
    agent_type = agent_type or "coding"

    # 2. LLM provider
    if llm_provider is None and not non_interactive:
        console.print()
        console.print("[bold]Which LLM provider?[/]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan bold", min_width=12)
        table.add_column("Description")
        for key, desc in LLM_PROVIDERS.items():
            table.add_row(key, desc)
        console.print(table)
        llm_provider = Prompt.ask(
            "LLM provider",
            choices=list(LLM_PROVIDERS.keys()),
            default="anthropic",
            console=console,
        )
    llm_provider = llm_provider or "anthropic"

    # 3. Security level
    security_descriptions = {
        "minimal": "Basic rules, allow-most permissions",
        "standard": "Recommended rules, restricted bash, path guards",
        "strict": "All rules, deny-by-default, require confirmation for writes",
    }
    if security is None and not non_interactive:
        console.print()
        console.print("[bold]Security level?[/]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Level", style="cyan bold", min_width=12)
        table.add_column("Description")
        for key, desc in security_descriptions.items():
            table.add_row(key, desc)
        console.print(table)
        security = Prompt.ask(
            "Security level",
            choices=list(security_descriptions.keys()),
            default="standard",
            console=console,
        )
    security = security or "standard"

    # 4. Pipeline mode
    mode_descriptions = {
        "core": "6-step pipeline — lightweight governance",
        "standard": "8-step pipeline — production agents",
        "enhanced": "14-step pipeline — maximum governance (default)",
    }
    if mode is None and not non_interactive:
        console.print()
        console.print("[bold]Pipeline mode?[/]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Mode", style="cyan bold", min_width=12)
        table.add_column("Description")
        for key, desc in mode_descriptions.items():
            table.add_row(key, desc)
        console.print(table)
        mode = Prompt.ask(
            "Pipeline mode",
            choices=list(mode_descriptions.keys()),
            default="enhanced",
            console=console,
        )
    mode = mode or "enhanced"

    # 5. Session persistence
    if session_persistence is None and not non_interactive:
        session_persistence = Confirm.ask(
            "Enable session persistence?",
            default=True,
            console=console,
        )
    session_persistence = session_persistence if session_persistence is not None else True

    # 5. Cost tracking
    if cost_tracking is None and not non_interactive:
        cost_tracking = Confirm.ask(
            "Enable cost tracking?",
            default=True,
            console=console,
        )
    cost_tracking = cost_tracking if cost_tracking is not None else True

    # --- Derive project name -----------------------------------------------
    project_name = project_dir.name
    if not non_interactive:
        project_name = Prompt.ask(
            "Project name",
            default=project_name,
            console=console,
        )

    # --- Generate constitution ---------------------------------------------
    tmpl = SECURITY_TEMPLATES[security]
    project_type_label = project_info.get("language", "unknown")
    constitution_content = render_constitution(tmpl, project_name, project_type_label, mode)

    # --- Write files -------------------------------------------------------
    created_files: list[str] = []
    created_dirs: list[str] = []

    # Constitution
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(constitution_content, encoding="utf-8")
    created_files.append(str(output_path.relative_to(project_dir)))

    # .autoharness/ scaffold
    ha_dir = project_dir / ".autoharness"
    ha_dir.mkdir(exist_ok=True)
    created_dirs.append(".autoharness")

    skills_dir = ha_dir / "skills"
    skills_dir.mkdir(exist_ok=True)
    created_dirs.append(".autoharness/skills")

    # Keep empty dirs tracked in git
    gitkeep = skills_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        created_files.append(".autoharness/skills/.gitkeep")

    if session_persistence:
        sessions_dir = ha_dir / "sessions"
        sessions_dir.mkdir(exist_ok=True)
        created_dirs.append(".autoharness/sessions")
        sk = sessions_dir / ".gitkeep"
        if not sk.exists():
            sk.touch()
            created_files.append(".autoharness/sessions/.gitkeep")

    if cost_tracking:
        cost_dir = ha_dir / "costs"
        cost_dir.mkdir(exist_ok=True)
        created_dirs.append(".autoharness/costs")
        sk = cost_dir / ".gitkeep"
        if not sk.exists():
            sk.touch()
            created_files.append(".autoharness/costs/.gitkeep")

    # Example script
    example_path = project_dir / "autoharness_example.py"
    if not example_path.exists():
        example_content = get_example_script(project_name, agent_type, llm_provider)
        example_path.write_text(example_content, encoding="utf-8")
        created_files.append("autoharness_example.py")

    # --- Show results ------------------------------------------------------
    _show_created_files(created_files, created_dirs)

    console.print()
    console.print(Panel(
        "[bold]Next steps:[/]\n\n"
        f"  1. Review and customize [cyan]{output}[/]\n"
        "  2. Run [cyan]autoharness validate[/] to check your constitution\n"
        "  3. Run [cyan]autoharness install --target claude-code[/] to set up hooks\n"
        f"  4. Try [cyan]python autoharness_example.py[/] to see governance in action\n"
        "  5. Start coding with governance enabled!",
        title="[green]What's next[/]",
        border_style="green",
        padding=(1, 2),
    ))


def _legacy_init(
    template: str,
    output_path: Path,
    non_interactive: bool,
    project_info: dict[str, Any],
) -> None:
    """Handle the legacy ``--template`` flag path (pre-wizard behaviour)."""
    project_name = output_path.parent.name
    if not non_interactive:
        project_name = Prompt.ask(
            "Project name",
            default=project_name,
            console=console,
        )

    content = _load_template(template)
    content = content.replace("name: my-project", f"name: {project_name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    console.print()
    console.print(f"[green bold]  Created[/] {output_path}")
    console.print()
    console.print(Panel(
        "[bold]Next steps:[/]\n\n"
        f"  1. Review and customize [cyan]{output_path}[/]\n"
        "  2. Run [cyan]autoharness validate[/] to check your constitution\n"
        "  3. Run [cyan]autoharness install --target claude-code[/] to set up hooks\n"
        "  4. Start coding with governance enabled",
        title="[green]What's next[/]",
        border_style="green",
        padding=(1, 2),
    ))


# ===================================================================
# autoharness check
# ===================================================================

@cli.command()
@click.option("--stdin", "from_stdin", is_flag=True, help="Read tool call JSON from stdin.")
@click.option(
    "--constitution", "-c",
    type=click.Path(exists=True),
    default=None,
    help="Path to constitution.yaml.",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["human", "json", "hook"]),
    default="human",
    help="Output format. 'hook' uses exit codes for Claude Code integration.",
)
def check(from_stdin: bool, constitution: str | None, fmt: str) -> None:
    """Check a tool call against governance rules.

    Without --stdin, validates the constitution file itself.
    With --stdin, reads a tool call JSON and returns the governance decision.
    """
    # Load constitution
    const = _load_constitution(constitution)

    if not from_stdin:
        # Validate the constitution
        warnings_list = const.validate()
        if fmt == "json":
            result = {
                "valid": len([
                    w for w in warnings_list
                    if "Duplicate" in w or "no description" in w
                ]) == 0,
                "warnings": warnings_list,
            }
            out.print(json.dumps(result, indent=2))
        elif fmt == "hook":
            # Exit 0 = valid, 2 = invalid
            if any("Duplicate" in w for w in warnings_list):
                raise SystemExit(2)
            raise SystemExit(0)
        else:
            if warnings_list:
                console.print("[yellow bold]  Warnings:[/]")
                for w in warnings_list:
                    console.print(f"  [yellow]![/] {w}")
            else:
                console.print("[green bold]  Constitution is valid.[/]")
        return

    # Read tool call from stdin
    try:
        raw = sys.stdin.read()
        tool_data = json.loads(raw)
    except json.JSONDecodeError as e:
        if fmt == "json":
            out.print(json.dumps({"error": f"Invalid JSON: {e}"}))
        elif fmt == "hook":
            raise SystemExit(2) from e
        else:
            console.print(f"[red bold]  Error:[/] Invalid JSON on stdin: {e}")
        raise SystemExit(1) from e

    # Extract tool call info
    tool_name = tool_data.get("tool_name", tool_data.get("name", "unknown"))
    tool_input = tool_data.get("tool_input", tool_data.get("input", {}))

    # Use the full governance pipeline for evaluation
    from autoharness.core.pipeline import ToolGovernancePipeline
    from autoharness.core.types import ToolCall

    pipeline = ToolGovernancePipeline(const)
    tc = ToolCall(tool_name=tool_name, tool_input=tool_input)
    perm = pipeline.evaluate(tc)
    risk = pipeline.risk_classifier.classify(tc)

    decision = {
        "action": perm.action,
        "tool": tool_name,
        "risk_level": risk.level.value,
        "reason": perm.reason,
        "matched_rules": [risk.matched_rule] if risk.matched_rule else [],
    }

    if fmt == "json":
        out.print(json.dumps(decision, indent=2))
    elif fmt == "hook":
        # Exit 0 = allow, 2 = deny (Claude Code hook convention)
        if decision["action"] == "deny":
            # Print reason to stderr for Claude Code
            console.print(f"[red]BLOCKED:[/] {decision['reason']}")
            raise SystemExit(2)
        raise SystemExit(0)
    else:
        _print_check_result(decision, tool_name)


def _evaluate_tool_call(
    config: Any, tool_name: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate a tool call against the constitution and return a decision dict."""
    import re

    decision: dict[str, Any] = {
        "action": "allow",
        "tool": tool_name,
        "risk_level": "low",
        "reason": "No rules matched",
        "matched_rules": [],
    }

    # Check tool permissions
    tools_config = config.permissions.get("tools", {})
    tool_perm = tools_config.get(tool_name)

    if tool_perm is None:
        # Unknown tool — check defaults
        defaults = config.permissions.get("defaults", {})
        unknown_policy = defaults.get("unknown_tool", "ask")
        if unknown_policy == "deny":
            decision["action"] = "deny"
            decision["reason"] = f"Unknown tool '{tool_name}' denied by default policy"
            return decision
        elif unknown_policy == "ask":
            decision["action"] = "ask"
            decision["reason"] = f"Unknown tool '{tool_name}' requires confirmation"
    else:
        policy = tool_perm.get("policy", "allow") if isinstance(tool_perm, dict) else "allow"
        if policy == "deny":
            decision["action"] = "deny"
            decision["reason"] = f"Tool '{tool_name}' is denied by policy"
            return decision

        # Check deny_patterns against tool input
        deny_patterns = (
            tool_perm.get("deny_patterns", []) if isinstance(tool_perm, dict) else []
        )
        input_str = json.dumps(tool_input)
        for pattern in deny_patterns:
            try:
                if re.search(pattern, input_str):
                    decision["action"] = "deny"
                    decision["risk_level"] = "high"
                    decision["reason"] = f"Input matches denied pattern: {pattern}"
                    decision["matched_rules"].append(
                        {"type": "deny_pattern", "pattern": pattern}
                    )
                    return decision
            except re.error:
                pass

        # Check deny_paths
        deny_paths = (
            tool_perm.get("deny_paths", []) if isinstance(tool_perm, dict) else []
        )
        for input_val in tool_input.values():
            if isinstance(input_val, str):
                for dp in deny_paths:
                    if dp in input_val or input_val.endswith(dp.lstrip("*")):
                        decision["action"] = "deny"
                        decision["risk_level"] = "high"
                        decision["reason"] = f"Path matches denied path: {dp}"
                        decision["matched_rules"].append(
                            {"type": "deny_path", "path": dp}
                        )
                        return decision

        # Check ask_patterns
        ask_patterns = (
            tool_perm.get("ask_patterns", []) if isinstance(tool_perm, dict) else []
        )
        for pattern in ask_patterns:
            try:
                if re.search(pattern, input_str):
                    decision["action"] = "ask"
                    decision["risk_level"] = "medium"
                    decision["reason"] = f"Input matches ask pattern: {pattern}"
                    decision["matched_rules"].append(
                        {"type": "ask_pattern", "pattern": pattern}
                    )
            except re.error:
                pass

    # Check rules with triggers
    for rule in config.rules:
        if not rule.triggers:
            continue
        for trigger in rule.triggers:
            trigger_tool = trigger.get("tool", "")
            trigger_pattern = trigger.get("pattern", "")
            if trigger_tool and trigger_tool != tool_name:
                continue
            if trigger_pattern:
                input_str = json.dumps(tool_input)
                try:
                    if re.search(trigger_pattern, input_str):
                        enf = (
                            rule.enforcement.value
                            if hasattr(rule.enforcement, "value")
                            else str(rule.enforcement)
                        )
                        if enf in ("hook", "both"):
                            sev = (
                                rule.severity.value
                                if hasattr(rule.severity, "value")
                                else str(rule.severity)
                            )
                            if sev == "error":
                                decision["action"] = "deny"
                                decision["risk_level"] = "high"
                            else:
                                if decision["action"] != "deny":
                                    decision["action"] = "ask"
                                    decision["risk_level"] = "medium"
                            decision["reason"] = f"Rule '{rule.id}': {rule.description}"
                            decision["matched_rules"].append(
                                {"type": "rule", "id": rule.id, "severity": sev}
                            )
                except re.error:
                    pass

    return decision


def _print_check_result(decision: dict[str, Any], tool_name: str) -> None:
    """Pretty-print a check result for human consumption."""
    action = decision["action"]
    risk = decision["risk_level"]

    # Color-code the action
    if action == "allow":
        action_str = "[green bold]ALLOW[/]"
        icon = "[green]  [/]"
    elif action == "ask":
        action_str = "[yellow bold]ASK[/]"
        icon = "[yellow]  ?[/]"
    else:
        action_str = "[red bold]DENY[/]"
        icon = "[red]  [/]"

    # Color-code risk level
    risk_colors = {"low": "green", "medium": "yellow", "high": "red", "critical": "red bold"}
    risk_color = risk_colors.get(risk, "white")

    console.print()
    console.print(f"{icon} Tool: [bold]{escape(tool_name)}[/]")
    console.print(f"     Decision: {action_str}")
    console.print(f"     Risk: [{risk_color}]{risk}[/{risk_color}]")
    console.print(f"     Reason: {escape(decision['reason'])}")

    if decision.get("matched_rules"):
        console.print("     Matched rules:")
        for rule in decision["matched_rules"]:
            rule_type = rule.get("type", "unknown")
            if rule_type == "rule":
                console.print(
                    f"       - [dim]{rule['id']}[/]"
                    f" (severity: {rule.get('severity', '?')})"
                )
            elif rule_type == "deny_pattern":
                console.print(f"       - [dim]deny_pattern:[/] {escape(rule.get('pattern', ''))}")
            elif rule_type == "deny_path":
                console.print(f"       - [dim]deny_path:[/] {escape(rule.get('path', ''))}")
            else:
                console.print(f"       - [dim]{escape(str(rule))}[/]")
    console.print()


# ===================================================================
# autoharness audit
# ===================================================================

@cli.group()
def audit() -> None:
    """Audit log management and reporting."""
    pass


@audit.command("summary")
@click.option("--session", "-s", default=None, help="Filter by session ID.")
@click.option("--path", "-p", default=".autoharness/audit.jsonl", help="Audit log path.")
def audit_summary(session: str | None, path: str) -> None:
    """Show audit summary with statistics."""
    engine = AuditEngine(output_path=path, enabled=True)
    try:
        summary = engine.get_summary(session_id=session)
    finally:
        engine.close()

    total = summary["total_calls"]
    if total == 0:
        console.print()
        console.print("[dim]  No audit records found.[/]")
        console.print(f"[dim]  Looked in: {path}[/]")
        console.print()
        return

    blocked = summary["blocked_count"]
    errors = summary["error_count"]
    allowed = total - blocked - errors
    duration = summary["session_duration_seconds"]

    # Header
    console.print()
    console.print(Panel(
        "[bold]Audit Summary[/]",
        border_style="cyan",
        padding=(0, 2),
    ))

    # Stats table
    stats = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    stats.add_column("Metric", style="dim")
    stats.add_column("Value", justify="right")
    stats.add_row("Total calls", str(total))
    stats.add_row("Allowed", f"[green]{allowed}[/]")
    stats.add_row("Blocked", f"[red]{blocked}[/]" if blocked else "0")
    stats.add_row("Errors", f"[yellow]{errors}[/]" if errors else "0")
    stats.add_row("Duration", f"{duration:.1f}s")
    console.print(stats)

    # Risk distribution
    risk_dist = summary["risk_distribution"]
    if risk_dist:
        console.print()
        console.print("[bold]  Risk Distribution[/]")
        risk_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        risk_table.add_column("Level")
        risk_table.add_column("Count", justify="right")
        risk_table.add_column("Bar")

        max_count = max(risk_dist.values()) if risk_dist else 1
        risk_styles = {
            "critical": "red bold",
            "high": "red",
            "medium": "yellow",
            "low": "green",
            "unassessed": "dim",
        }
        for level in ("critical", "high", "medium", "low", "unassessed"):
            count = risk_dist.get(level, 0)
            if count > 0:
                bar_len = int((count / max_count) * 30)
                style = risk_styles.get(level, "white")
                risk_table.add_row(
                    f"[{style}]{level}[/{style}]",
                    str(count),
                    f"[{style}]{'#' * bar_len}[/{style}]",
                )
        console.print(risk_table)

    # Tools used
    tools_used = summary["tools_used"]
    if tools_used:
        console.print()
        console.print("[bold]  Tools Used[/]")
        tools_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        tools_table.add_column("Tool")
        tools_table.add_column("Calls", justify="right")
        for tool, count in tools_used.items():
            tools_table.add_row(tool, str(count))
        console.print(tools_table)

    # Top blocked reasons
    blocked_reasons = summary["top_blocked_reasons"]
    if blocked_reasons:
        console.print()
        console.print("[bold red]  Top Blocked Reasons[/]")
        for reason, count in blocked_reasons.items():
            short = reason[:60] + "..." if len(reason) > 60 else reason
            console.print(f"    [red]{count}x[/] {escape(short)}")

    console.print()


@audit.command("report")
@click.option(
    "--format", "fmt",
    type=click.Choice(["text", "html", "json"]),
    default="text",
    help="Report format.",
)
@click.option("--output", "-o", default=None, help="Write report to file.")
@click.option("--path", "-p", default=".autoharness/audit.jsonl", help="Audit log path.")
def audit_report(fmt: str, output: str | None, path: str) -> None:
    """Generate an audit report."""
    engine = AuditEngine(output_path=path, enabled=True)
    try:
        report = engine.generate_report(format=fmt, output=output)
    finally:
        engine.close()

    if output:
        console.print(f"[green bold]  Report written to[/] {output}")
    else:
        out.print(report)


@audit.command("check")
@click.option(
    "--max-blocks", "-n", default=0, type=int,
    help="Fail if blocks exceed this threshold.",
)
@click.option("--path", "-p", default=".autoharness/audit.jsonl", help="Audit log path.")
def audit_check(max_blocks: int, path: str) -> None:
    """CI check: fail if blocked calls exceed threshold."""
    engine = AuditEngine(output_path=path, enabled=True)
    try:
        summary = engine.get_summary()
    finally:
        engine.close()

    blocked = summary["blocked_count"]
    total = summary["total_calls"]

    if total == 0:
        console.print("[dim]  No audit records found. Passing.[/]")
        raise SystemExit(0)

    console.print(f"  Total calls: {total}, Blocked: {blocked}, Threshold: {max_blocks}")

    if blocked > max_blocks:
        console.print(
            f"[red bold]  FAIL:[/] {blocked} blocked calls"
            f" exceed threshold of {max_blocks}"
        )
        raise SystemExit(1)
    else:
        console.print(
            f"[green bold]  PASS:[/] {blocked} blocked calls"
            f" within threshold of {max_blocks}"
        )
        raise SystemExit(0)


@audit.command("clean")
@click.option("--days", "-d", default=30, type=int, help="Remove records older than N days.")
@click.option("--path", "-p", default=".autoharness/audit.jsonl", help="Audit log path.")
def audit_clean(days: int, path: str) -> None:
    """Remove old audit records."""
    engine = AuditEngine(output_path=path, enabled=True, retention_days=days)
    try:
        removed = engine.cleanup(retention_days=days)
    finally:
        engine.close()

    if removed > 0:
        console.print(f"[green]  Removed {removed} records older than {days} days.[/]")
    else:
        console.print(f"[dim]  No records older than {days} days found.[/]")


# ===================================================================
# autoharness install
# ===================================================================

@cli.command()
@click.option(
    "--target", "-t",
    type=click.Choice(["claude-code", "cursor"]),
    default="claude-code",
    help="Target tool to install hooks for.",
)
@click.option(
    "--constitution", "-c",
    type=click.Path(),
    default="constitution.yaml",
    help="Path to constitution file.",
)
def install(target: str, constitution: str) -> None:
    """Install AutoHarness hooks into your development tool."""
    const_path = Path(constitution)

    if target == "claude-code":
        _install_claude_code(const_path)
    elif target == "cursor":
        _install_cursor(const_path)


def _install_claude_code(const_path: Path) -> None:
    """Install AutoHarness as a Claude Code hook."""
    hooks_dir = Path(".claude")
    settings_path = hooks_dir / "settings.json"

    console.print()
    console.print("[bold]Installing AutoHarness hooks for Claude Code...[/]")
    console.print()

    # Create .claude directory
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Build the hook command
    hook_cmd = f"autoharness check --stdin --constitution {const_path} --format hook"

    # Load or create settings.json
    settings: dict[str, Any] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            console.print(
                "[yellow]  Warning: existing settings.json"
                " is invalid, creating new one.[/]"
            )

    # Add hook configuration for PreToolUse / PostToolUse events
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "PreToolUse" not in settings["hooks"]:
        settings["hooks"]["PreToolUse"] = []

    # Check if already installed
    existing = settings["hooks"]["PreToolUse"]
    already_installed = any(
        "autoharness" in (h.get("command", "") if isinstance(h, dict) else str(h))
        for h in existing
    )

    if already_installed:
        console.print("[yellow]  AutoHarness hook is already installed.[/]")
        console.print(
            "[dim]  To reinstall, remove the autoharness"
            " entry from .claude/settings.json[/]"
        )
        return

    # Add the hook entry
    # matcher: tool name pattern (blank = match all tools)
    # kind: "command" for shell hooks
    existing.append({
        "type": "command",
        "command": hook_cmd,
        "description": (
            "AutoHarness governance check "
            "— risk classification, permission enforcement, "
            "secret scanning"
        ),
    })

    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )

    console.print(f"[green]  [/] Hook command: [cyan]{hook_cmd}[/]")
    console.print(f"[green]  [/] Settings written to: [cyan]{settings_path}[/]")
    console.print()

    # Verify constitution exists
    if const_path.exists():
        console.print(f"[green]  [/] Constitution found: [cyan]{const_path}[/]")
    else:
        console.print(f"[yellow]  ![/] Constitution not found at [cyan]{const_path}[/]")
        console.print("     Run [cyan]autoharness init[/] to create one.")

    console.print()
    console.print(
        "[green bold]  AutoHarness is ready.[/] Claude Code will now"
        " check tool calls against your constitution."
    )
    console.print()


def _install_cursor(const_path: Path) -> None:
    """Install AutoHarness as Cursor rules from a constitution file."""
    from autoharness.integrations.cursor import CursorInstaller

    console.print()
    console.print("[bold]Installing AutoHarness rules for Cursor...[/]")
    console.print()

    installer = CursorInstaller(project_dir=Path.cwd())

    constitution_arg = str(const_path) if const_path.exists() else None
    result = installer.install(
        constitution_path=constitution_arg,
        enable_hooks=True,
    )

    rule_file = result.get("rule_file", "")
    hooks_installed = result.get("hooks_installed", False)

    console.print(f"[green]  [/] Rule file: [cyan]{rule_file}[/]")
    if hooks_installed:
        console.print(f"[green]  [/] Hook script: [cyan]{result.get('hook_script', '')}[/]")
    else:
        console.print("[dim]    Hooks not installed (Cursor 0.50+ required)[/]")

    if constitution_arg:
        console.print(f"[green]  [/] Constitution found: [cyan]{const_path}[/]")
    else:
        console.print(f"[yellow]  ![/] Constitution not found at [cyan]{const_path}[/]")
        console.print(
            "     Run [cyan]autoharness init[/]"
            " to create one, or using default template."
        )

    console.print()
    console.print(
        "[green bold]  AutoHarness is ready.[/]"
        " Cursor will now follow your governance rules."
    )
    console.print()


# ===================================================================
# autoharness export
# ===================================================================

@cli.command()
@click.option(
    "--format", "-f", "fmt",
    type=click.Choice(["claude-code", "cursor", "yaml"]),
    default="yaml",
    help="Target format for export.",
)
@click.option(
    "--constitution", "-c",
    type=click.Path(),
    default=None,
    help="Path to constitution.yaml.",
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    default=None,
    help="Output file path. Defaults to stdout.",
)
def export(fmt: str, constitution: str | None, output: str | None) -> None:
    """Export constitution in a target harness format.

    Formats:

      yaml        — Normalized constitution YAML (default)

      cursor      — Cursor-compatible .cursor/rules/autoharness.md

      claude-code — Claude Code .claude/settings.json hooks config
    """
    import yaml as _yaml

    const = _load_constitution(constitution)
    config = const.config

    if fmt == "yaml":
        data = config.model_dump(mode="json")
        content = _yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    elif fmt == "cursor":
        from autoharness.integrations.cursor import CursorInstaller

        installer = CursorInstaller()
        # Build a dict from the constitution config for the rule generator
        raw = config.model_dump(mode="json")
        content = installer._generate_rule_markdown(raw)
    elif fmt == "claude-code":
        # Generate the hooks.json structure that Claude Code expects
        const_path = constitution or "constitution.yaml"
        hook_cmd = f"autoharness check --stdin --constitution {const_path} --format hook"
        settings: dict[str, Any] = {
            "hooks": {
                "PreToolUse": [
                    {
                        "type": "command",
                        "command": hook_cmd,
                        "description": (
            "AutoHarness governance check "
            "— risk classification, permission enforcement, "
            "secret scanning"
        ),
                    }
                ],
            },
        }
        content = json.dumps(settings, indent=2) + "\n"
    else:
        console.print(f"[red]Unknown format: {fmt}[/]")
        raise SystemExit(1)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        console.print(f"[green bold]  Exported to[/] {out_path}")
    else:
        out.print(content, end="")


# ===================================================================
# autoharness validate
# ===================================================================

@cli.command()
@click.argument("path", default="constitution.yaml", type=click.Path())
def validate(path: str) -> None:
    """Validate a constitution.yaml file."""
    filepath = Path(path)

    if not filepath.exists():
        console.print(f"[red bold]  Error:[/] File not found: {filepath}")
        raise SystemExit(1)

    console.print()
    console.print(f"[dim]  Validating {filepath}...[/]")
    console.print()

    # Try loading
    try:
        const = Constitution.load(filepath)
    except ConstitutionError as e:
        console.print("[red bold]  Error:[/] Failed to load constitution")
        console.print()
        # Show the error in a panel for readability
        console.print(Panel(
            escape(str(e)),
            title="[red]Validation Error[/]",
            border_style="red",
            padding=(1, 2),
        ))
        raise SystemExit(1) from None
    except FileNotFoundError:
        console.print(f"[red bold]  Error:[/] File not found: {filepath}")
        raise SystemExit(1) from None

    # Run soft validation
    warnings_list = const.validate()

    # Show constitution summary
    config = const.config
    rules_count = len(config.rules)
    permissions_raw = config.permissions
    tools_config: Any = (
        permissions_raw.get("tools", {})
        if isinstance(permissions_raw, dict)
        else getattr(permissions_raw, "tools", {})
    )
    tools_count = len(tools_config) if isinstance(tools_config, dict) else 0
    identity = config.identity
    name = (
        identity.get("name", "unnamed")
        if isinstance(identity, dict)
        else getattr(identity, "name", "unnamed")
    )

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Name", name)
    table.add_row("Version", config.version)
    table.add_row("Rules", str(rules_count))
    table.add_row("Tool configs", str(tools_count))
    console.print(table)
    console.print()

    # Show warnings
    errors = [w for w in warnings_list if "Duplicate" in w]
    soft_warnings = [w for w in warnings_list if w not in errors]

    if errors:
        console.print("[red bold]  Errors:[/]")
        for err_msg in errors:
            console.print(f"  [red]  [/] {err_msg}")
        console.print()

    if soft_warnings:
        console.print("[yellow bold]  Warnings:[/]")
        for w in soft_warnings:
            console.print(f"  [yellow]  ![/] {w}")
        console.print()

    if errors:
        console.print("[red bold]  Constitution has errors.[/]")
        raise SystemExit(1)
    elif soft_warnings:
        console.print("[green bold]  Constitution is valid[/] [dim](with warnings)[/]")
    else:
        console.print("[green bold]  Constitution is valid.[/]")

    console.print()


# ===================================================================
# autoharness version
# ===================================================================

@cli.command()
def version() -> None:
    """Show AutoHarness version."""
    out.print(f"[bold]autoharness[/] {autoharness.__version__}")


# ===================================================================
# autoharness mode
# ===================================================================

@cli.command("mode")
@click.argument("new_mode", required=False, type=click.Choice(["core", "standard", "enhanced"]))
@click.option(
    "--constitution", "-c",
    type=click.Path(),
    default=None,
    help="Path to constitution.yaml.",
)
def mode_cmd(new_mode: str | None, constitution: str | None) -> None:
    """Show or switch the pipeline mode.

    \b
    Without arguments, shows the current mode:
        autoharness mode

    \b
    With an argument, updates the constitution file:
        autoharness mode enhanced
    """
    import yaml

    if new_mode is None:
        # Show current mode
        try:
            c = _load_constitution(constitution)
            current = getattr(c.config, "mode", "enhanced")
            if hasattr(current, "value"):
                current = current.value
            console.print(f"[bold]Current pipeline mode:[/] [cyan]{current}[/]")

            mode_info = {
                "core": ("6-step pipeline", "Basic risk classification, permission check, audit"),
                "standard": ("8-step pipeline", "Adds hooks, interface validation, trace store"),
                "enhanced": ("14-step pipeline", "Full governance with all advanced features"),
            }
            for m, (title, desc) in mode_info.items():
                marker = " [green]<< active[/]" if m == str(current) else ""
                console.print(f"  [cyan]{m}[/]: {title}{marker}")
                console.print(f"    [dim]{desc}[/]")
        except (ConstitutionError, FileNotFoundError):
            console.print("[yellow]No constitution found. Default mode: enhanced[/]")
        return

    # Update constitution file
    config_path = Path(constitution) if constitution else _find_constitution_file()
    if config_path is None or not config_path.exists():
        console.print(
            "[red]No constitution file found.[/] Run [cyan]autoharness init[/] first."
        )
        raise SystemExit(1)

    raw = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    data["mode"] = new_mode
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    console.print(f"[green]Pipeline mode set to:[/] [bold cyan]{new_mode}[/]")
    console.print(f"[dim]Updated {config_path}[/]")


def _find_constitution_file() -> Path | None:
    """Find the first constitution file in the current directory."""
    candidates = (
        "constitution.yaml",
        ".autoharness.yaml",
        ".autoharness/constitution.yaml",
        "autoharness.yaml",
    )
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None


# ===================================================================
# Helpers
# ===================================================================

def _load_constitution(path: str | None) -> Constitution:
    """Load a constitution from a path, or use cascading discovery if not specified."""
    if path:
        return Constitution.load(path)

    # Use cascading config discovery (user -> project -> local)
    return Constitution.discover()


# ===================================================================
# autoharness wrap
# ===================================================================

@cli.command("wrap", context_settings={"ignore_unknown_options": True})
@click.option(
    "--constitution", "-c",
    type=click.Path(),
    default=None,
    help="Path to constitution.yaml.",
)
@click.option(
    "--audit-log", "-a",
    default=".autoharness/audit.jsonl",
    help="Path for the audit JSONL log.",
)
@click.option(
    "--session-id", "-s",
    default=None,
    help="Session ID for audit grouping. Auto-generated if omitted.",
)
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
def wrap(
    constitution: str | None,
    audit_log: str,
    session_id: str | None,
    command: tuple[str, ...],
) -> None:
    """Wrap a subprocess with AutoHarness governance.

    Sets up environment variables and runs the given command, collecting
    audit data from a shared JSONL file. Prints a governance summary on exit.

    Usage:

        autoharness wrap -- python my_agent.py

        autoharness wrap -c constitution.yaml -- node agent.js
    """
    import io
    import os
    import signal
    import subprocess
    import uuid

    if not command:
        console.print("[red bold]  Error:[/] No command provided.")
        console.print("  Usage: autoharness wrap -- <command> [args...]")
        raise SystemExit(1)

    # Strip leading "--" if present (click passes it through)
    cmd_list = list(command)
    if cmd_list and cmd_list[0] == "--":
        cmd_list = cmd_list[1:]

    if not cmd_list:
        console.print("[red bold]  Error:[/] No command after '--'.")
        raise SystemExit(1)

    # Resolve constitution path
    const_path = constitution
    if const_path is None:
        for candidate in (
            "constitution.yaml",
            "constitution.yml",
            ".autoharness/constitution.yaml",
        ):
            if Path(candidate).exists():
                const_path = candidate
                break

    # Generate session ID
    sid = session_id or f"wrap-{uuid.uuid4().hex[:12]}"

    # Build environment
    env = os.environ.copy()
    env["AUTOHARNESS_ACTIVE"] = "1"
    env["AUTOHARNESS_SESSION_ID"] = sid
    env["AUTOHARNESS_AUDIT_LOG"] = str(Path(audit_log).resolve())
    if const_path:
        env["AUTOHARNESS_CONSTITUTION"] = str(Path(const_path).resolve())

    # Print startup banner
    console.print()
    console.print(Panel(
        f"[bold]AutoHarness Wrapper Mode[/]\n\n"
        f"  Command:      [cyan]{' '.join(cmd_list)}[/]\n"
        f"  Session:      [dim]{sid}[/]\n"
        f"  Constitution: [dim]{const_path or '(default)'}[/]\n"
        f"  Audit log:    [dim]{audit_log}[/]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    # Run the subprocess
    exit_code = 0
    try:
        # Determine stdio handles — Click's CliRunner uses fake streams
        # without fileno(), so fall back to PIPE and let output pass through.
        stdin_arg = None
        stdout_arg = None
        stderr_arg = None
        use_pipe = False

        try:
            if hasattr(sys.stdin, "fileno"):
                sys.stdin.fileno()
            stdin_arg = sys.stdin
            stdout_arg = sys.stdout
            stderr_arg = sys.stderr
        except (AttributeError, OSError, io.UnsupportedOperation):
            # Running inside Click's test runner or similar
            use_pipe = True
            stdin_arg = subprocess.DEVNULL
            stdout_arg = subprocess.PIPE
            stderr_arg = subprocess.PIPE

        proc = subprocess.Popen(
            cmd_list,
            env=env,
            stdout=stdout_arg,
            stderr=stderr_arg,
            stdin=stdin_arg,
        )

        # Forward signals to the child process
        def _forward_signal(signum: int, frame: Any) -> None:
            with contextlib.suppress(ProcessLookupError, OSError):
                proc.send_signal(signum)

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _forward_signal)
        signal.signal(signal.SIGTERM, _forward_signal)

        try:
            if use_pipe:
                stdout_data, stderr_data = proc.communicate()
                exit_code = proc.returncode
                if stdout_data:
                    click.echo(stdout_data.decode(errors="replace"), nl=False)
                if stderr_data:
                    click.echo(stderr_data.decode(errors="replace"), nl=False, err=True)
            else:
                exit_code = proc.wait()
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

    except FileNotFoundError:
        console.print(f"[red bold]  Error:[/] Command not found: {cmd_list[0]}")
        raise SystemExit(127) from None
    except Exception as e:
        console.print(f"[red bold]  Error:[/] Failed to run command: {e}")
        raise SystemExit(1) from None

    # Collect and print audit summary
    console.print()
    console.print("[dim]" + "-" * 60 + "[/]")
    console.print()

    audit_path = Path(audit_log)
    if audit_path.exists() and audit_path.stat().st_size > 0:
        engine = AuditEngine(output_path=str(audit_path), enabled=True)
        try:
            summary = engine.get_summary(session_id=sid)
        finally:
            engine.close()

        total = summary["total_calls"]
        blocked = summary["blocked_count"]
        errors = summary["error_count"]
        allowed = total - blocked - errors

        if total > 0:
            console.print("[bold]  AutoHarness Wrap Summary[/]")
            console.print()
            console.print(f"    Total calls:  {total}")
            console.print(f"    Allowed:      [green]{allowed}[/]")
            if blocked:
                console.print(f"    Blocked:      [red]{blocked}[/]")
            else:
                console.print("    Blocked:      0")
            if errors:
                console.print(f"    Errors:       [yellow]{errors}[/]")
            else:
                console.print("    Errors:       0")

            if summary["top_blocked_reasons"]:
                console.print()
                console.print("    [red]Blocked reasons:[/]")
                for reason, count in list(summary["top_blocked_reasons"].items())[:5]:
                    short = reason[:50] + "..." if len(reason) > 50 else reason
                    console.print(f"      {count}x {escape(short)}")
        else:
            console.print("[dim]  No audit records found for this session.[/]")
    else:
        console.print(
            "[dim]  No audit log found. The subprocess"
            " may not have used AutoHarness governance.[/]"
        )

    console.print()

    if exit_code != 0:
        console.print(f"[yellow]  Subprocess exited with code {exit_code}[/]")

    raise SystemExit(exit_code)


# ===================================================================
# autoharness report
# ===================================================================

@cli.command()
@click.option("--path", "-p", default=".autoharness/audit.jsonl", help="Audit log path.")
@click.option(
    "--output", "-o", default=None,
    help="Write report to file (default: stdout or auto-named HTML).",
)
@click.option("--session", "-s", default=None, help="Filter by session ID.")
@click.option(
    "--format", "fmt",
    type=click.Choice(["html", "text", "json"]),
    default="html",
    help="Report format.",
)
def report(path: str, output: str | None, session: str | None, fmt: str) -> None:
    """Generate a pretty audit report.

    By default, generates a standalone HTML report. Use --format to
    change output format.

    Examples:

        autoharness report

        autoharness report --format html -o report.html

        autoharness report --format text

        autoharness report --session wrap-abc123
    """
    audit_path = Path(path)

    if not audit_path.exists():
        console.print()
        console.print(f"[yellow]  No audit log found at {path}[/]")
        console.print(
            "  Run [cyan]autoharness wrap -- <command>[/]"
            " or use the pipeline to generate audit data."
        )
        console.print()
        raise SystemExit(1)

    engine = AuditEngine(output_path=str(audit_path), enabled=True)
    try:
        summary = engine.get_summary(session_id=session)
    finally:
        engine.close()

    total = summary["total_calls"]
    if total == 0:
        console.print()
        console.print("[dim]  No audit records found.[/]")
        if session:
            console.print(f"[dim]  Session filter: {session}[/]")
        console.print()
        raise SystemExit(0)

    # Generate report
    engine2 = AuditEngine(output_path=str(audit_path), enabled=True)
    try:
        report_content = engine2.generate_report(format=fmt, output=output)
    finally:
        engine2.close()

    if output:
        console.print(f"[green bold]  Report written to[/] {output}")
        console.print()
    else:
        if fmt == "html":
            # For HTML without output file, auto-generate filename
            auto_path = ".autoharness/report.html"
            Path(auto_path).parent.mkdir(parents=True, exist_ok=True)
            Path(auto_path).write_text(report_content, encoding="utf-8")
            console.print(f"[green bold]  HTML report written to[/] {auto_path}")
            console.print()
        else:
            out.print(report_content)


# ===================================================================
# autoharness agents
# ===================================================================

@cli.command("agents")
@click.option(
    "--constitution", "-c",
    type=click.Path(exists=True),
    default=None,
    help="Path to constitution.yaml.",
)
def agents_cmd(constitution: str | None) -> None:
    """Show available built-in agent profiles for multi-agent governance."""
    from autoharness.core.multi_agent import BUILTIN_PROFILES

    console.print()
    console.print("[bold]Built-in Agent Profiles[/]")
    console.print()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Name", style="cyan bold", min_width=10)
    table.add_column("Role", min_width=10)
    table.add_column("Max Risk", min_width=10)
    table.add_column("Allowed Tools")
    table.add_column("Description")

    for name, profile in BUILTIN_PROFILES.items():
        tools_str = (
            ", ".join(sorted(set(t.lower() for t in profile.allowed_tools)))
            if profile.allowed_tools
            else "[dim]all[/]"
        )
        table.add_row(
            name,
            profile.role,
            profile.max_risk_level,
            tools_str,
            profile.metadata.get("description", ""),
        )

    console.print(table)
    console.print()
    console.print(
        "[dim]  Use these with the MultiAgentGovernor API"
        " or extend with custom profiles.[/]"
    )
    console.print()


# ===================================================================
# autoharness run
# ===================================================================

@cli.command("run")
@click.argument("task", required=False, default=None)
@click.option("--model", "-m", default="claude-sonnet-4-6", help="Model to use.")
@click.option(
    "--constitution", "-c", type=click.Path(exists=True),
    default=None, help="Path to constitution.",
)
@click.option("--interactive", "-i", is_flag=True, help="Interactive REPL mode.")
@click.option("--max-iterations", default=200, type=int, help="Maximum loop iterations.")
def run_cmd(
    task: str | None,
    model: str,
    constitution: str | None,
    interactive: bool,
    max_iterations: int,
) -> None:
    """Run the agent loop on a task.

    \b
    Examples:
        autoharness run "Fix the bug in auth.py" --model claude-sonnet-4-6
        autoharness run --interactive
    """
    from autoharness.agent_loop import AgentLoop

    const = _load_constitution(constitution) if constitution else None

    loop = AgentLoop(
        model=model,
        constitution=const,
        max_iterations=max_iterations,
    )

    if interactive:
        console.print(Panel(
            "[bold]AutoHarness Interactive Mode[/]\n"
            f"Model: {model} | Session: {loop.session_id}\n"
            "Type 'exit' or 'quit' to leave.",
            title="AutoHarness REPL",
        ))
        while True:
            try:
                user_input = Prompt.ask("[bold cyan]>[/]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/]")
                break
            if user_input.strip().lower() in ("exit", "quit", "q"):
                console.print("[dim]Goodbye.[/]")
                break
            if not user_input.strip():
                continue
            try:
                result = loop.run(user_input)
                console.print(f"\n{result}\n")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/]")
    elif task:
        try:
            result = loop.run(task)
            out.print(result)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/]")
            raise SystemExit(1) from None
    else:
        console.print("[red]Provide a task argument or use --interactive.[/]")
        raise SystemExit(1)


# ===================================================================
# autoharness tools
# ===================================================================

@cli.group("tools")
def tools_group() -> None:
    """Manage registered tools."""
    pass


@tools_group.command("list")
def tools_list() -> None:
    """List all registered tools."""
    from autoharness.tools.registry import ToolRegistry

    registry = ToolRegistry()

    # Show built-in tools info
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Name", style="cyan bold")
    table.add_column("Source")
    table.add_column("Read-Only")
    table.add_column("Deferred")
    table.add_column("Description")

    tools = registry.list_all()
    if not tools:
        console.print("[dim]No tools registered in a bare registry.[/]")
        console.print("[dim]Tools are registered when the AgentLoop is initialized.[/]")
        return

    for t in sorted(tools, key=lambda x: x.name):
        table.add_row(
            t.name,
            t.source,
            "yes" if t.is_read_only else "",
            "yes" if t.should_defer else "",
            t.description[:60] + "..." if len(t.description) > 60 else t.description,
        )

    console.print(table)


# ===================================================================
# autoharness skills
# ===================================================================

@cli.group("skills")
def skills_group() -> None:
    """Manage discovered skills."""
    pass


@skills_group.command("list")
@click.option("--dir", "skills_dir", default=None, help="Skills directory to scan.")
def skills_list(skills_dir: str | None) -> None:
    """List discovered skills."""
    from autoharness.skills.loader import SkillRegistry, load_skills_into_registry

    registry = SkillRegistry()
    count = load_skills_into_registry(registry, project_dir=skills_dir)

    if count == 0:
        console.print("[dim]No skills discovered.[/]")
        console.print("[dim]Place SKILL.md files in .autoharness/skills/<name>/ directories.[/]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Name", style="cyan bold")
    table.add_column("Disabled")
    table.add_column("Model")
    table.add_column("Description")

    for skill in sorted(registry.list_all(), key=lambda s: s.metadata.name):
        m = skill.metadata
        table.add_row(
            m.name,
            "yes" if m.disabled else "",
            m.model or "",
            m.description[:60] + "..." if len(m.description) > 60 else m.description,
        )

    console.print(table)
    console.print(f"\n[dim]{count} skill(s) discovered.[/]")


# ===================================================================
# autoharness session
# ===================================================================

@cli.group("session")
def session_group() -> None:
    """Manage agent sessions."""
    pass


@session_group.command("list")
@click.option("--days", default=7, help="Show sessions from last N days.")
@click.option("--dir", "base_dir", default=None, help="Sessions directory.")
def session_list(days: int, base_dir: str | None) -> None:
    """List recent sessions."""
    from autoharness.session.persistence import list_recent_sessions, load_session

    sessions = list_recent_sessions(base_dir=base_dir, days=days)

    if not sessions:
        console.print("[dim]No recent sessions found.[/]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Session ID", style="cyan bold")
    table.add_column("Date")
    table.add_column("Status")
    table.add_column("Project")

    for path in sessions:
        try:
            state = load_session(path)
            table.add_row(
                state.session_id,
                state.date[:19] if state.date else "",
                state.status,
                state.project,
            )
        except Exception:
            table.add_row(path.stem, "", "error", "")

    console.print(table)
    console.print(f"\n[dim]{len(sessions)} session(s) found.[/]")


@session_group.command("resume")
@click.option("--dir", "base_dir", default=None, help="Sessions directory.")
def session_resume(base_dir: str | None) -> None:
    """Show most recent session state (for manual resume)."""
    from autoharness.session.persistence import list_recent_sessions, load_session

    sessions = list_recent_sessions(base_dir=base_dir, days=7)
    if not sessions:
        console.print("[dim]No recent sessions to resume.[/]")
        return

    state = load_session(sessions[0])
    console.print(Panel(
        f"[bold]Session:[/] {state.session_id}\n"
        f"[bold]Date:[/] {state.date}\n"
        f"[bold]Status:[/] {state.status}\n"
        f"[bold]Project:[/] {state.project}\n"
        f"[bold]In Progress:[/] {', '.join(state.in_progress) or 'none'}\n"
        f"[bold]Next Step:[/] {state.next_step or 'none'}",
        title="Most Recent Session",
    ))


# ===================================================================
# autoharness context
# ===================================================================

@cli.group("context")
def context_group() -> None:
    """Context window management."""
    pass


@context_group.command("stats")
@click.option("--model", "-m", default="claude-sonnet-4-6", help="Model to show stats for.")
def context_stats(model: str) -> None:
    """Show token budget statistics for a model."""
    from autoharness.context.models import (
        get_context_window,
        get_max_output_tokens,
        has_1m_context,
        model_supports_1m,
    )
    from autoharness.context.tokens import TokenBudget

    window = get_context_window(model)
    max_output = get_max_output_tokens(model)
    budget = TokenBudget(max_tokens=window)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Property", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Model", model)
    table.add_row("Context Window", f"{window:,} tokens")
    table.add_row("Max Output", f"{max_output:,} tokens")
    table.add_row("Effective Window", f"{budget.effective_window:,} tokens")
    variant = (
        "active" if has_1m_context(model)
        else ("available" if model_supports_1m(model) else "no")
    )
    table.add_row("1M Variant", variant)
    table.add_row("Compact Threshold (93%)", f"{int(budget.effective_window * 0.93):,} tokens")
    table.add_row("Warn Threshold (80%)", f"{int(budget.effective_window * 0.80):,} tokens")

    console.print(Panel(table, title="Context Budget Stats"))


# ===================================================================
# Entry point
# ===================================================================

def main() -> None:
    """Entry point for the autoharness CLI."""
    cli()


if __name__ == "__main__":
    main()
