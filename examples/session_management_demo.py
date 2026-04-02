#!/usr/bin/env python3
"""Session Management Demo — persist, resume, track costs.

Shows how to:
  1. Create and save a SessionState
  2. Load and resume a session with structured briefing
  3. Track session costs with SessionCost
  4. List and clean up old sessions

Run:
    python examples/session_management_demo.py
"""

import tempfile
from pathlib import Path

from autoharness.session import (
    MODEL_PRICING,
    SESSION_DIR_NAME,
    # Cost tracking
    SessionCost,
    # Persistence
    SessionState,
    cleanup_old_sessions,
    format_briefing,
    list_recent_sessions,
    load_session,
    # Resume
    resume_session,
    save_session,
)


def main() -> None:
    print("=" * 60)
    print("AutoHarness Session Management Demo")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / SESSION_DIR_NAME
        session_dir.mkdir(parents=True)

        # ------------------------------------------------------------------
        # 1. Create and save a SessionState.
        # ------------------------------------------------------------------
        print("\n1. Create and save session state:")

        state = SessionState(
            project="autoharness",
            branch="feature/context-recovery",
            status="in-progress",
            working=[
                "Implemented OutputRecoveryLoop",
                "Added RetryConfig with exponential backoff",
                "Fixed context/__init__.py exports",
            ],
            in_progress=[
                "Writing comprehensive example files",
                "Integration testing with real API calls",
            ],
            not_started=[
                "Performance benchmarking",
                "Documentation update",
            ],
            failed=[
                "Attempted streaming retry with WebSocket — abandoned, too complex",
            ],
            open_questions=[
                "Should circuit breaker auto-reset after a timeout?",
                "What's the right max_retries default for production?",
            ],
            next_step="Complete example files and run full test suite",
        )

        saved_path = save_session(state, base_dir=session_dir)
        print(f"   Session ID: {state.session_id}")
        print(f"   Saved to: {saved_path}")
        print(f"   File size: {saved_path.stat().st_size} bytes")

        # Show what the file looks like
        print("\n   File contents (first 20 lines):")
        lines = saved_path.read_text().split("\n")
        for line in lines[:20]:
            print(f"   | {line}")

        # ------------------------------------------------------------------
        # 2. Load the session back.
        # ------------------------------------------------------------------
        print("\n2. Load session from file:")

        loaded = load_session(saved_path)
        print(f"   Session ID: {loaded.session_id}")
        print(f"   Project: {loaded.project}")
        print(f"   Branch: {loaded.branch}")
        print(f"   Status: {loaded.status}")
        print(f"   Working items: {len(loaded.working)}")
        print(f"   In progress: {len(loaded.in_progress)}")
        print(f"   Not started: {len(loaded.not_started)}")
        print(f"   Next step: {loaded.next_step}")

        # ------------------------------------------------------------------
        # 3. Resume session with structured briefing.
        # ------------------------------------------------------------------
        print("\n3. Session resume briefing:")
        print("-" * 40)

        briefing = format_briefing(loaded)
        print(briefing)
        print("-" * 40)

        # Resume from most recent session in directory
        briefing2 = resume_session(base_dir=session_dir)
        print(f"\n   resume_session() auto-finds most recent: {len(briefing2)} chars")

        # ------------------------------------------------------------------
        # 4. List recent sessions.
        # ------------------------------------------------------------------
        print("\n4. List recent sessions:")

        # Create a second session
        state2 = SessionState(
            project="autoharness",
            branch="main",
            status="completed",
            working=["Merged PR #42"],
        )
        save_session(state2, base_dir=session_dir)

        recent = list_recent_sessions(base_dir=session_dir, days=7)
        print(f"   Found {len(recent)} sessions in last 7 days:")
        for path in recent:
            print(f"     {path.name}")

        # ------------------------------------------------------------------
        # 5. SessionCost — track token usage and estimated cost.
        # ------------------------------------------------------------------
        print("\n5. Session cost tracking:")

        print("   Model pricing (per 1M tokens):")
        for model, pricing in MODEL_PRICING.items():
            print(f"     {model}: input=${pricing['input']}, output=${pricing['output']}")

        cost = SessionCost(
            session_id=state.session_id,
            model="claude-sonnet-4-6",
        )

        # Simulate several turns
        cost.record_turn(input_tokens=50_000, output_tokens=2_000, cache_read=30_000)
        cost.record_turn(input_tokens=55_000, output_tokens=3_000, cache_read=40_000)
        cost.record_turn(
            input_tokens=60_000, output_tokens=5_000,
            cache_read=45_000, cache_write=10_000,
        )

        print("\n   After 3 turns:")
        print(f"     Turns: {cost.turns}")
        print(f"     Total input tokens: {cost.total_input_tokens:,}")
        print(f"     Total output tokens: {cost.total_output_tokens:,}")
        print(f"     Cache read tokens: {cost.total_cache_read_tokens:,}")
        print(f"     Cache write tokens: {cost.total_cache_write_tokens:,}")
        print(f"     Total tokens: {cost.total_tokens:,}")
        print(f"     Estimated cost: ${cost.estimated_cost_usd:.4f}")

        # Save and load cost data
        cost_path = Path(tmpdir) / "session_cost.json"
        cost.save(cost_path)
        loaded_cost = SessionCost.load(cost_path)
        print("\n   Saved and reloaded cost data:")
        print(f"     Turns: {loaded_cost.turns}, Cost: ${loaded_cost.estimated_cost_usd:.4f}")

        # ------------------------------------------------------------------
        # 6. Cleanup old sessions.
        # ------------------------------------------------------------------
        print("\n6. Session cleanup:")
        removed = cleanup_old_sessions(base_dir=session_dir, days=0)
        print(f"   Cleaned up {removed} sessions older than 0 days")
        remaining = list_recent_sessions(base_dir=session_dir, days=7)
        print(f"   Remaining sessions: {len(remaining)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
