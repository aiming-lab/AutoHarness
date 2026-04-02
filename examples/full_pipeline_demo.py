#!/usr/bin/env python3
"""Full Pipeline Demo — all systems working together.

This is the most comprehensive example showing how all AutoHarness
subsystems integrate into a complete agent harness. It walks through
a realistic scenario: setting up governance, registering tools and
skills, running an agent loop with context management, and producing
a session report.

No API keys required — all LLM calls are mocked.

Run:
    python examples/full_pipeline_demo.py
"""

import tempfile
from pathlib import Path

from autoharness import Constitution, ToolGovernancePipeline
from autoharness.agents import (
    BackgroundAgentManager,
    TeamMailbox,
    TeamMessage,
    build_forked_messages,
    get_builtin_agent,
)
from autoharness.context import (
    AutoCompactor,
    OutputRecoveryLoop,
    RetryConfig,
    TokenBudget,
    compute_backoff_ms,
    get_context_window,
    microcompact,
    restore_files_after_compact,
)
from autoharness.core.types import ToolCall
from autoharness.prompt import (
    CacheBreakDetector,
    McpInstructionManager,
    SystemPromptRegistry,
    system_prompt_section,
    uncached_section,
)
from autoharness.session import (
    SessionCost,
    SessionState,
    format_briefing,
    save_session,
)
from autoharness.skills import ParsedSkill, SkillMetadata, SkillRegistry, SkillTool
from autoharness.tools import ToolDefinition, ToolRegistry


def main() -> None:
    print("=" * 60)
    print("AutoHarness Full Pipeline Demo")
    print("All systems working together in a realistic scenario")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # ==============================================================
        # PHASE 1: Setup — Constitution, Pipeline, Tools, Skills, Prompt
        # ==============================================================
        print("\n--- PHASE 1: System Setup ---")

        # 1a. Load governance constitution
        constitution = Constitution.from_yaml("""\
identity:
  name: full-pipeline-demo
  version: "1.0"

rules:
  - id: no-force-push
    description: Block force pushes to main/master
    enforcement: hook
    severity: error

  - id: no-secrets
    description: Block secrets in tool inputs
    enforcement: hook
    severity: error

permissions:
  defaults:
    allow_by_default: true
""")
        pipeline = ToolGovernancePipeline(constitution)
        print(f"  Governance pipeline ready: {pipeline}")

        # 1b. Set up tool registry
        tool_registry = ToolRegistry()
        for name, desc, read_only, destructive, defer in [
            ("Read", "Read a file", True, False, False),
            ("Edit", "Edit a file", False, False, False),
            ("Bash", "Execute shell command", False, True, False),
            ("Grep", "Search file contents", True, False, False),
            ("Glob", "Find files by pattern", True, False, False),
            ("WebFetch", "Fetch URL content", True, False, True),
            ("NotebookEdit", "Edit Jupyter notebook", False, False, True),
        ]:
            tool_registry.register(ToolDefinition(
                name=name,
                description=desc,
                input_schema={"type": "object", "properties": {}},
                is_read_only=read_only,
                is_destructive=destructive,
                should_defer=defer,
            ))
        n_deferred = len(tool_registry.list_deferred())
        print(
            f"  Tool registry: {len(tool_registry)} tools"
            f" ({n_deferred} deferred)"
        )

        # 1c. Set up skill registry
        skill_registry = SkillRegistry()
        skill_registry.register(ParsedSkill(
            metadata=SkillMetadata(
                name="commit",
                description="Create conventional git commits",
                allowed_tools=["Bash", "Read"],
                model="haiku",
            ),
            body="# Commit\n1. git status\n2. Draft message\n3. git commit",
        ))
        skill_registry.register(ParsedSkill(
            metadata=SkillMetadata(
                name="review-pr",
                description="Review pull requests",
                allowed_tools=["Bash", "Read", "Grep"],
                model="sonnet",
            ),
            body="# PR Review\n1. gh pr view\n2. Check diff\n3. Post review",
        ))
        skill_tool = SkillTool(skill_registry)
        print(f"  Skill registry: {len(skill_registry)} skills")

        # 1d. Build system prompt
        prompt_registry = SystemPromptRegistry()
        prompt_registry.register_static(system_prompt_section(
            "identity",
            lambda: "You are a governed AI coding assistant.",
        ))
        prompt_registry.register_static(system_prompt_section(
            "governance",
            lambda: (
                "All tool calls are governed by"
                " AutoHarness. Destructive operations"
                " require approval."
            ),
        ))
        prompt_registry.register_static(system_prompt_section(
            "skills",
            lambda: skill_registry.get_prompt_descriptions(),
        ))
        prompt_registry.register_dynamic(uncached_section(
            "context",
            lambda: "Project: autoharness | Branch: main | Clean tree",
            reason="Changes per turn",
        ))

        system_prompt = prompt_registry.build_system_prompt()
        print(f"  System prompt: {len(system_prompt)} chars")

        # 1e. Initialize context management
        model = "claude-sonnet-4-6"
        budget = TokenBudget(max_tokens=get_context_window(model), reserve=13_000)
        compactor = AutoCompactor(token_budget=budget, model=model)
        recovery = OutputRecoveryLoop(max_retries=3)
        cache_detector = CacheBreakDetector()
        cache_detector.check(system_prompt)  # Establish baseline

        mcp_mgr = McpInstructionManager()
        mcp_mgr.update_servers({"github": "Use gh for GitHub"})

        print(f"  Context budget: {budget.max_tokens:,} tokens, {budget.available:,} available")

        # 1f. Initialize session tracking
        session_cost = SessionCost(session_id="demo-001", model=model)
        print("  Session cost tracker initialized")

        # ==============================================================
        # PHASE 2: Simulated Agent Loop
        # ==============================================================
        print("\n--- PHASE 2: Agent Loop (3 turns) ---")

        messages = []

        # --- Turn 1: User asks to find test files ---
        print("\n  Turn 1: User asks to find test files")
        messages.append({"role": "user", "content": "Find all test files in the project"})

        # Simulate model producing a tool call
        tool_call = ToolCall(tool_name="Bash", tool_input={"command": "find . -name '*test*.py'"})
        decision = pipeline.evaluate(tool_call)
        print(f"    Governance check: {decision.action}")

        result = pipeline.process(tool_call)
        print(f"    Pipeline result: {result.status}")

        # Simulate model response with tool use
        messages.append({"role": "assistant", "content": [
            {"type": "text", "text": "I'll search for test files."},
            {"type": "tool_use", "id": "tu_1",
             "name": "Bash",
             "input": {"command": "find . -name '*test*.py'"}},
        ]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "tool_name": "Bash",
             "content": "tests/test_main.py\ntests/test_context.py\ntests/test_tools.py\n" * 20},
        ]})

        budget.record_usage(input_tokens=20_000, output_tokens=2_000)
        session_cost.record_turn(input_tokens=20_000, output_tokens=2_000)
        print(f"    Budget: {budget.usage_ratio:.1%} used")

        # --- Turn 2: Dangerous command (blocked) ---
        print("\n  Turn 2: Model attempts force push (blocked)")
        messages.append({"role": "user", "content": "Push the changes"})

        bad_call = ToolCall(
            tool_name="Bash",
            tool_input={"command": "git push --force origin main"},
        )
        bad_result = pipeline.process(bad_call)
        print(f"    Governance: {bad_result.status} — {bad_result.blocked_reason}")

        messages.append({"role": "assistant", "content": "I'll push safely instead."})
        safe_call = ToolCall(
            tool_name="Bash",
            tool_input={
                "command": "git push origin feature-branch"
            },
        )
        safe_result = pipeline.process(safe_call)
        print(f"    Safe alternative: {safe_result.status}")

        budget.record_usage(input_tokens=25_000, output_tokens=1_500)
        session_cost.record_turn(input_tokens=25_000, output_tokens=1_500)
        print(f"    Budget: {budget.usage_ratio:.1%} used")

        # --- Turn 3: Skill invocation ---
        print("\n  Turn 3: Model invokes commit skill")
        messages.append({"role": "user", "content": "Now commit the changes"})

        skill_result = skill_tool.execute("commit")
        print(f"    Skill body injected: {len(skill_result)} chars")
        print(f"    Preview: {skill_result[:60]}...")

        budget.record_usage(input_tokens=30_000, output_tokens=3_000)
        session_cost.record_turn(input_tokens=30_000, output_tokens=3_000)
        print(f"    Budget: {budget.usage_ratio:.1%} used")

        # ==============================================================
        # PHASE 3: Context Management
        # ==============================================================
        print("\n--- PHASE 3: Context Management ---")

        # Microcompact old tool results
        compacted_msgs = microcompact(messages, keep_recent=2)
        tokens_saved = getattr(compacted_msgs, 'tokens_saved', 0)
        print(f"  Microcompact: saved ~{tokens_saved} tokens")

        # Check if auto-compact needed
        print(f"  Should compact: {compactor.should_compact(messages)}")
        print(f"  Should warn: {budget.should_warn}")

        # Simulate high usage to show compaction
        budget.record_usage(input_tokens=100_000, output_tokens=5_000)
        print(f"  After simulated load: {budget.usage_ratio:.1%} used")
        print(f"  Should compact now: {budget.should_compact}")

        if budget.should_compact:
            compacted, _summary = compactor.compact(
                messages,
                summarizer=lambda p: (
                    "User searched for test files,"
                    " attempted force push (blocked),"
                    " then committed changes safely."
                ),
            )
            print(f"  Auto-compacted: {len(messages)} -> {len(compacted)} messages")

            # Restore important files
            restored = restore_files_after_compact(
                compacted,
                recent_files=[{"path": "src/main.py", "content": "def main(): pass"}],
            )
            print(f"  Post-compact restoration: {len(restored)} messages")

        # Check cache break
        new_prompt = prompt_registry.build_system_prompt()
        cache_broke = cache_detector.check(new_prompt)
        print(f"  Cache break detected: {cache_broke}")

        # Recovery loop check
        truncated = {"stop_reason": "max_tokens"}
        needs_retry = recovery.should_retry(truncated)
        print(f"  Max-tokens retry needed: {needs_retry}")

        # Backoff calculation
        delay = compute_backoff_ms(0, RetryConfig(initial_backoff_ms=200))
        print(f"  First retry backoff: {delay}ms")

        # ==============================================================
        # PHASE 4: Sub-Agent Orchestration
        # ==============================================================
        print("\n--- PHASE 4: Sub-Agent Orchestration ---")

        # Fork a verification agent
        verifier = get_builtin_agent("Verification")
        print(f"  Forking {verifier.name} agent (model: {verifier.model})")

        fork_msgs = build_forked_messages(
            messages[:4],
            directive="Verify that all test files pass: run pytest and report results.",
        )
        print(f"  Fork messages: {len(fork_msgs)} (inherits parent context)")

        # Background agent
        bg_manager = BackgroundAgentManager(output_dir=str(tmpdir / "bg_outputs"))
        task = bg_manager.register("Run full test suite in background")
        print(f"  Background task: [{task.agent_id}] {task.description}")

        bg_manager.complete(task.agent_id, "All 42 tests passed. 0 failures.")
        notifications = bg_manager.drain_notifications()
        print(f"  Background completed: {notifications[0]['summary']}")

        # Team communication
        mailbox = TeamMailbox(base_dir=str(tmpdir / "team"))
        mailbox.send("reviewer", TeamMessage(
            type="message",
            from_agent="coder",
            content="Changes ready for review in feature-branch",
        ))
        reviewer_msgs = mailbox.read_inbox("reviewer")
        print(f"  Team message delivered: {reviewer_msgs[0].content}")

        # ==============================================================
        # PHASE 5: Session Report
        # ==============================================================
        print("\n--- PHASE 5: Session Report ---")

        # Audit summary
        audit = pipeline.get_audit_summary()
        print("  Governance audit:")
        for k, v in audit.items():
            print(f"    {k}: {v}")

        # Cost summary
        print("\n  Cost summary:")
        print(f"    Turns: {session_cost.turns}")
        print(f"    Total tokens: {session_cost.total_tokens:,}")
        print(f"    Estimated cost: ${session_cost.estimated_cost_usd:.4f}")

        # Save session state
        final_state = SessionState(
            session_id="demo-001",
            project="autoharness",
            branch="main",
            status="completed",
            working=[
                "Found test files",
                "Blocked dangerous force push",
                "Committed changes safely via skill",
            ],
            in_progress=[],
            not_started=["Performance benchmarking"],
            next_step="Run full test suite and deploy",
        )
        session_path = save_session(final_state, base_dir=tmpdir / "sessions")
        print(f"\n  Session saved: {session_path}")

        briefing = format_briefing(final_state)
        print("\n  Resume briefing preview:")
        for line in briefing.split("\n")[:10]:
            print(f"    {line}")

    print("\n" + "=" * 60)
    print("All AutoHarness subsystems demonstrated successfully.")
    print("=" * 60)
    print("\nDone.")


if __name__ == "__main__":
    main()
