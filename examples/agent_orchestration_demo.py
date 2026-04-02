#!/usr/bin/env python3
"""Agent Orchestration Demo — built-in agents, fork, background.

Shows how to:
  1. Use built-in agent types (Explore, Plan, Verification)
  2. Parse agent definition files
  3. Build forked messages for sub-agents
  4. Use BackgroundAgentManager for async tasks
  5. Use TeamMailbox for inter-agent communication

Run:
    python examples/agent_orchestration_demo.py
"""

import tempfile

from autoharness.agents import (
    # Built-in agents
    BUILTIN_AGENTS,
    BackgroundAgentManager,
    # Team/swarm
    TeamConfig,
    TeamMailbox,
    TeamMember,
    TeamMessage,
    # Fork semantics
    build_forked_messages,
    get_builtin_agent,
    is_in_fork_child,
    parse_agent_file,
)


def main() -> None:
    print("=" * 60)
    print("AutoHarness Agent Orchestration Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Built-in agent types.
    # ------------------------------------------------------------------
    print("\n1. Built-in agent types:")
    for name, agent in BUILTIN_AGENTS.items():
        print(f"\n   {name}:")
        print(f"     Description: {agent.description}")
        print(f"     Model: {agent.model}")
        print(f"     Tools: {agent.tools}")
        print(f"     Read-only: {agent.is_read_only}")
        print(f"     Max iterations: {agent.max_iterations}")

    # Look up by name
    agent = get_builtin_agent("explore")  # Case-insensitive
    print(f"\n   get_builtin_agent('explore') -> {agent.name}")
    print(f"   get_builtin_agent('nonexistent') -> {get_builtin_agent('nonexistent')}")

    # ------------------------------------------------------------------
    # 2. Parse a custom agent definition file.
    # ------------------------------------------------------------------
    print("\n2. Custom agent definition file:")

    agent_content = """\
---
name: SecurityAuditor
description: Specialized agent for security vulnerability scanning
tools: [Bash, Read, Grep, Glob]
model: opus
permission_mode: plan
max_iterations: 50
is_read_only: true
---

# Security Auditor Agent

You are a security-focused agent. Scan the codebase for:

1. Hardcoded secrets (API keys, passwords, tokens)
2. SQL injection vulnerabilities
3. Path traversal risks
4. Insecure dependencies (check package.json, requirements.txt)
5. Missing input validation

Report findings in a structured format with severity levels.
"""

    custom_agent = parse_agent_file(agent_content, source_path="agents/security.md")
    print(f"   Name: {custom_agent.name}")
    print(f"   Description: {custom_agent.description}")
    print(f"   Model: {custom_agent.model}")
    print(f"   Tools: {custom_agent.tools}")
    print(f"   Prompt preview: {custom_agent.prompt[:80]}...")

    # ------------------------------------------------------------------
    # 3. Fork message building — cache-sharing sub-agents.
    # ------------------------------------------------------------------
    print("\n3. Fork message building:")

    parent_messages = [
        {"role": "user", "content": "Refactor the authentication module"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "I'll analyze the auth module first."},
            {"type": "tool_use", "id": "tu_001", "name": "Grep",
             "input": {"pattern": "def authenticate", "path": "src/"}},
        ]},
    ]

    # Build messages for a fork child
    child_messages = build_forked_messages(
        parent_messages,
        directive="Focus on the JWT token validation logic. Check for expiry handling.",
    )

    print(f"   Parent messages: {len(parent_messages)}")
    print(f"   Child messages: {len(child_messages)}")
    print(f"   Fork detected in parent: {is_in_fork_child(parent_messages)}")
    print(f"   Fork detected in child: {is_in_fork_child(child_messages)}")

    # Show the child's directive message
    last_msg = child_messages[-1]
    if isinstance(last_msg.get("content"), list):
        for block in last_msg["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                print(f"   Child directive: {block['text'][:80]}...")
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                print(f"   Placeholder result: '{block['content']}'")

    # ------------------------------------------------------------------
    # 4. BackgroundAgentManager — async agent lifecycle.
    # ------------------------------------------------------------------
    print("\n4. BackgroundAgentManager:")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = BackgroundAgentManager(output_dir=f"{tmpdir}/agent_outputs")

        # Register background tasks
        task1 = manager.register("Run full test suite")
        task2 = manager.register("Lint all Python files")
        manager.register("Check for security vulnerabilities")

        print("   Registered 3 tasks:")
        for task in manager.list_all():
            print(f"     [{task.agent_id}] {task.description} ({task.status})")

        print(f"\n   Running tasks: {len(manager.list_running())}")

        # Complete one task
        manager.complete(task1.agent_id, "All 42 tests passed. Coverage: 87%.")
        print(f"\n   Completed task {task1.agent_id}")

        # Fail another
        manager.fail(task2.agent_id, "Lint config not found: .flake8 missing")
        print(f"   Failed task {task2.agent_id}")

        # Drain notifications
        notifications = manager.drain_notifications()
        print(f"\n   Notifications ({len(notifications)}):")
        for notif in notifications:
            detail = notif.get(
                'summary', notif.get('error', '')
            )[:60]
            print(
                f"     [{notif['agent_id']}] "
                f"{notif['status']}: {detail}"
            )

        # Get output of completed task
        output = manager.get_output(task1.agent_id)
        print(f"\n   Task {task1.agent_id} output: {output}")

        # Check that draining cleared notifications
        print(f"   Notifications after drain: {len(manager.drain_notifications())}")

    # ------------------------------------------------------------------
    # 5. TeamMailbox — inter-agent communication.
    # ------------------------------------------------------------------
    print("\n5. TeamMailbox — inter-agent communication:")

    with tempfile.TemporaryDirectory() as tmpdir:
        mailbox = TeamMailbox(base_dir=f"{tmpdir}/team")

        # Set up a team
        config = TeamConfig(
            team_name="refactor-squad",
            members=[
                TeamMember(name="planner", role="architect"),
                TeamMember(name="coder", role="implementer"),
                TeamMember(name="reviewer", role="verifier"),
            ],
        )
        mailbox.save_config(config)

        # Load it back
        loaded = mailbox.load_config()
        print(f"   Team: {loaded.team_name}")
        print(f"   Members: {[m.name for m in loaded.members]}")

        # Send messages between agents
        mailbox.send("coder", TeamMessage(
            type="message",
            from_agent="planner",
            content="Start implementing the new auth flow. See plan in /docs/auth-plan.md",
        ))

        mailbox.send("coder", TeamMessage(
            type="message",
            from_agent="reviewer",
            content="Make sure to add tests for edge cases.",
        ))

        # Broadcast from planner to all
        mailbox.broadcast(
            from_agent="planner",
            content="Sprint goal: Complete auth refactor by end of session.",
            members=["planner", "coder", "reviewer"],
        )

        # Read inbox
        coder_msgs = mailbox.read_inbox("coder")
        print(f"\n   Coder's inbox ({len(coder_msgs)} messages):")
        for msg in coder_msgs:
            print(f"     [{msg.type}] from {msg.from_agent}: {msg.content[:50]}...")

        reviewer_msgs = mailbox.read_inbox("reviewer")
        print(f"\n   Reviewer's inbox ({len(reviewer_msgs)} messages):")
        for msg in reviewer_msgs:
            print(f"     [{msg.type}] from {msg.from_agent}: {msg.content[:50]}...")

        # Inbox is drained after reading
        print(f"\n   Coder's inbox after drain: {len(mailbox.read_inbox('coder'))} messages")

    print("\nDone.")


if __name__ == "__main__":
    main()
