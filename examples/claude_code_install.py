#!/usr/bin/env python3
"""Claude Code Installation — install AutoHarness as Claude Code hooks.

This example shows how to:
  1. Check if AutoHarness is already installed in Claude Code
  2. Install AutoHarness hooks (PreToolUse + PostToolUse)
  3. Copy a constitution file to the Claude Code config directory
  4. Check installation status
  5. Uninstall cleanly

What gets installed:
  ~/.claude/hooks.json — Claude Code lifecycle hooks configuration
    PreToolUse:  autoharness check --stdin --format hook
    PostToolUse: autoharness audit --stdin --format hook

  ~/.claude/autoharness/constitution.yaml — your governance rules
  ~/.claude/autoharness/audit/ — audit log directory

Prerequisites:
    pip install autoharness
    # The autoharness CLI must be on your PATH

Run:
    python examples/claude_code_install.py
"""

import json
from pathlib import Path

from autoharness.integrations.claude_code import ClaudeCodeInstaller


def main() -> None:
    print("=" * 60)
    print("AutoHarness Claude Code Installation Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Create an installer instance.
    #    By default it targets ~/.claude, but you can override for testing.
    # ------------------------------------------------------------------
    installer = ClaudeCodeInstaller()

    # ------------------------------------------------------------------
    # 2. Check current status before installation.
    # ------------------------------------------------------------------
    print("\n--- Pre-installation status ---")
    status = installer.status()
    for key, value in status.items():
        print(f"  {key}: {value}")

    if status["installed"]:
        print("\n  AutoHarness is already installed in Claude Code.")
        print("  To reinstall, run with --force or uninstall first.")

    # ------------------------------------------------------------------
    # 3. Install AutoHarness hooks.
    #
    #    This is safe to run multiple times — it replaces existing
    #    AutoHarness hooks while preserving any other hooks in hooks.json.
    #
    #    Pass a constitution_path to copy your rules into the
    #    config directory. If omitted, the CLI uses its default constitution.
    # ------------------------------------------------------------------
    print("\n--- Installing ---")

    # Check if we have a constitution file to install
    constitution_path = None
    candidates = [
        Path("./constitution.yaml"),
        Path("./examples/constitution.yaml"),
        Path(__file__).parent / "constitution.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            constitution_path = str(candidate)
            break

    result = installer.install(constitution_path=constitution_path)

    print(f"  Installed: {result['installed']}")
    print(f"  Hooks JSON: {result['hooks_json']}")
    print(f"  Hooks added: {result['hooks_added']}")
    print(f"  Constitution copied: {result['constitution_copied']}")
    if result["constitution_path"]:
        print(f"  Constitution path: {result['constitution_path']}")
    print(f"  Audit directory: {result['audit_dir']}")

    # ------------------------------------------------------------------
    # 4. Verify installation by checking status again.
    # ------------------------------------------------------------------
    print("\n--- Post-installation status ---")
    status = installer.status()
    for key, value in status.items():
        print(f"  {key}: {value}")

    # ------------------------------------------------------------------
    # 5. Show what hooks.json looks like.
    # ------------------------------------------------------------------
    hooks_path = Path(status["hooks_json_path"])
    if hooks_path.exists():
        print(f"\n--- {hooks_path} ---")
        content = json.loads(hooks_path.read_text())
        print(json.dumps(content, indent=2))

    # ------------------------------------------------------------------
    # 6. Demonstrate uninstall (commented out to avoid disrupting
    #    an actual installation — uncomment to test).
    # ------------------------------------------------------------------
    # print("\n--- Uninstalling ---")
    # uninstall_result = installer.uninstall()
    # print(f"  Hooks removed: {uninstall_result['hooks_removed']}")
    # print(f"  Config removed: {uninstall_result['config_removed']}")

    # ------------------------------------------------------------------
    # How it works at runtime
    # ------------------------------------------------------------------
    print("\n--- How it works ---")
    print("""
When Claude Code makes a tool call, it runs the hooks in hooks.json:

  1. PreToolUse hook runs:
     $ autoharness check --stdin --format hook
     - Reads the tool call from stdin (JSON)
     - Evaluates it against your constitution
     - Returns "allow", "deny", or "ask" to Claude Code

  2. If allowed, Claude Code executes the tool.

  3. PostToolUse hook runs:
     $ autoharness audit --stdin --format hook
     - Logs the tool execution to the audit trail
     - Scans output for leaked secrets (redacts them)

This all happens transparently — you use Claude Code as normal,
and AutoHarness enforces your governance rules in the background.
""")

    print("Done.")


if __name__ == "__main__":
    main()
