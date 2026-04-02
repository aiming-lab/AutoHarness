#!/usr/bin/env python3
"""Prompt Architecture Demo — section framework and cache boundaries.

Shows how to:
  1. Use SystemPromptRegistry with static and dynamic sections
  2. Understand SYSTEM_PROMPT_DYNAMIC_BOUNDARY
  3. Use ContextManager for user vs system context
  4. Use CacheBreakDetector to track prompt changes
  5. Use McpInstructionManager for delta injection

Run:
    python examples/prompt_architecture_demo.py
"""

from autoharness.prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    CacheBreakDetector,
    ContextManager,
    McpInstructionManager,
    SystemPromptRegistry,
    build_tool_prompt_section,
    system_prompt_section,
    uncached_section,
)


def main() -> None:
    print("=" * 60)
    print("AutoHarness Prompt Architecture Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. SystemPromptRegistry — static/dynamic section framework.
    #
    # The system prompt is split into two zones:
    # - Static prefix: cached across API calls (identity, rules, tools)
    # - Dynamic suffix: recomputed each turn (git status, time, MCP)
    #
    # A boundary marker separates them, enabling prompt caching.
    # ------------------------------------------------------------------
    print("\n1. SystemPromptRegistry:")

    registry = SystemPromptRegistry()

    # Register static (cacheable) sections
    registry.register_static(system_prompt_section(
        "identity",
        lambda: "You are Claude, an AI assistant by Anthropic.",
    ))

    registry.register_static(system_prompt_section(
        "rules",
        lambda: (
            "# Rules\n"
            "- Never commit secrets to git\n"
            "- Always run tests before committing\n"
            "- Prefer editing existing files over creating new ones"
        ),
    ))

    registry.register_static(system_prompt_section(
        "tool_instructions",
        lambda: build_tool_prompt_section({
            "Bash": "Always quote file paths with spaces.",
            "Edit": "Use Edit for targeted changes, Write for new files.",
        }),
    ))

    # Register dynamic (per-session) sections
    registry.register_dynamic(uncached_section(
        "git_context",
        lambda: "Current branch: main | Clean working tree | Last commit: abc1234",
        reason="Git status changes between turns",
    ))

    registry.register_dynamic(uncached_section(
        "current_date",
        lambda: "Today's date is 2026-03-31.",
        reason="Date changes daily",
    ))

    # Resolve all sections
    all_parts = registry.resolve_all()
    print(f"   Total sections: {len(all_parts)}")
    print(f"   Boundary marker present: {SYSTEM_PROMPT_DYNAMIC_BOUNDARY in all_parts}")

    static = registry.resolve_static_prefix()
    dynamic = registry.resolve_dynamic_suffix()
    print(f"   Static sections: {len(static)}")
    print(f"   Dynamic sections: {len(dynamic)}")

    # Build the complete prompt
    prompt = registry.build_system_prompt()
    print(f"   Full prompt length: {len(prompt)} chars")
    print("\n   Preview (first 200 chars):")
    print(f"   {prompt[:200]}...")

    # Cache behavior: static sections are cached
    print("\n   Calling resolve_static_prefix() again uses cache")
    static2 = registry.resolve_static_prefix()
    print(f"   Same result: {static == static2}")

    registry.clear_cache()
    print("   After clear_cache(): cache invalidated")

    # ------------------------------------------------------------------
    # 2. ContextManager — separate user and system context.
    #
    # User context (CLAUDE.md, memory files) and system context (git,
    # env info) are cached independently. Debug injection invalidates both.
    # ------------------------------------------------------------------
    print("\n2. ContextManager:")

    ctx = ContextManager()

    user_ctx = ctx.get_user_context(
        loader=lambda: "# CLAUDE.md\nPrefer TypeScript. Always use ESLint."
    )
    print(f"   User context: {user_ctx[:50]}...")

    sys_ctx = ctx.get_system_context(
        loader=lambda: "Platform: darwin | Shell: zsh | Node: v20.11.0"
    )
    print(f"   System context: {sys_ctx[:50]}...")

    # Cached on second call
    user_ctx2 = ctx.get_user_context(loader=lambda: "SHOULD NOT BE CALLED")
    print(f"   Cached (same result): {user_ctx == user_ctx2}")

    # Debug injection invalidates caches
    ctx.set_injection("DEBUG: force tool error")
    print(f"   Injection set: '{ctx.injection}'")

    # Now loaders will be called again
    user_ctx3 = ctx.get_user_context(
        loader=lambda: "# CLAUDE.md (reloaded)\nNew instructions."
    )
    print(f"   After injection, user context reloaded: {user_ctx3[:50]}...")

    ctx.invalidate()
    print("   After invalidate(): all caches cleared")

    # ------------------------------------------------------------------
    # 3. CacheBreakDetector — detect when prompt changes.
    #
    # Tracks a hash of the system prompt. When the prompt changes,
    # a cache break is detected. This helps monitor cache efficiency.
    # ------------------------------------------------------------------
    print("\n3. CacheBreakDetector:")

    detector = CacheBreakDetector()

    prompt_v1 = "You are Claude. Follow these rules..."
    prompt_v2 = "You are Claude. Follow these updated rules..."

    # First check establishes baseline
    broke = detector.check(prompt_v1)
    print(f"   First check: cache_break={broke} (baseline established)")

    # Same prompt: no break
    broke = detector.check(prompt_v1)
    print(f"   Same prompt: cache_break={broke}")

    # Different prompt: cache break
    broke = detector.check(prompt_v2)
    print(f"   Changed prompt: cache_break={broke}")

    # Track total breaks
    print(f"   Total cache breaks: {detector.break_count}")

    # Manual compaction notification
    detector.notify_compaction()
    print(f"   After compaction: break_count={detector.break_count}")

    # ------------------------------------------------------------------
    # 4. McpInstructionManager — delta injection for MCP servers.
    #
    # Instead of recomputing all MCP instructions every turn (breaking
    # cache), only inject deltas when servers connect/disconnect.
    # ------------------------------------------------------------------
    print("\n4. McpInstructionManager:")

    mcp = McpInstructionManager()

    # Initial server connection
    delta = mcp.update_servers({
        "github": "Use gh CLI for GitHub operations",
        "slack": "Use Slack API for messaging",
    })
    print("   Initial connection delta:")
    print(f"   {delta}")

    # No change: no delta
    delta = mcp.update_servers({
        "github": "Use gh CLI for GitHub operations",
        "slack": "Use Slack API for messaging",
    })
    print(f"\n   Same servers: delta={delta}")

    # New server connects
    delta = mcp.update_servers({
        "github": "Use gh CLI for GitHub operations",
        "slack": "Use Slack API for messaging",
        "notion": "Use Notion API for page management",
    })
    print("\n   New server connected:")
    print(f"   {delta}")

    # Server disconnects
    delta = mcp.update_servers({
        "github": "Use gh CLI for GitHub operations",
    })
    print("\n   Servers disconnected:")
    print(f"   {delta}")

    # Full instructions (for initial prompt or post-compact)
    full = mcp.get_full_instructions()
    print("\n   Full instructions:")
    print(f"   {full}")

    print("\nDone.")


if __name__ == "__main__":
    main()
