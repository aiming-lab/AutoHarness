"""Tests for Phase 5: Agent Orchestration Engine."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from autoharness.agents.background import BackgroundAgentManager
from autoharness.agents.builtin import (
    BUILTIN_AGENTS,
    EXPLORE_AGENT,
    GENERAL_PURPOSE_AGENT,
    PLAN_AGENT,
    VERIFICATION_AGENT,
    get_builtin_agent,
)
from autoharness.agents.definition import AgentDefinition, parse_agent_file
from autoharness.agents.fork import (
    FORK_BOILERPLATE_TAG,
    FORK_PLACEHOLDER_RESULT,
    build_forked_messages,
    is_in_fork_child,
)
from autoharness.agents.swarm import (
    TeamConfig,
    TeamMailbox,
    TeamMember,
    TeamMessage,
)
from autoharness.agents.worktree import WorktreeEntry, WorktreeManager

# ── C.1 Agent Definition ──────────────────────────────────────────

VALID_AGENT_FILE = """\
---
name: TestAgent
description: A test agent
tools:
  - Read
  - Grep
model: sonnet
max_iterations: 10
---
You are a test agent. Do test things.
"""


def test_parse_agent_file_valid():
    defn = parse_agent_file(VALID_AGENT_FILE)
    assert defn.name == "TestAgent"
    assert defn.description == "A test agent"
    assert defn.tools == ["Read", "Grep"]
    assert defn.model == "sonnet"
    assert defn.max_iterations == 10
    assert "test agent" in defn.prompt.lower()


def test_parse_agent_file_missing_name():
    content = "---\ndescription: no name\n---\nPrompt here."
    with pytest.raises(ValueError, match="name"):
        parse_agent_file(content)


def test_parse_agent_file_invalid_yaml():
    content = "---\n: : : bad yaml\n---\nPrompt."
    with pytest.raises(ValueError, match="Invalid YAML"):
        parse_agent_file(content)


def test_parse_agent_file_no_frontmatter():
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        parse_agent_file("No frontmatter here")


def test_parse_agent_file_non_mapping_frontmatter():
    content = "---\n- list item\n---\nPrompt."
    with pytest.raises(ValueError, match="mapping"):
        parse_agent_file(content)


def test_agent_definition_defaults():
    defn = AgentDefinition(name="minimal")
    assert defn.description == ""
    assert defn.tools == []
    assert defn.model is None
    assert defn.permission_mode == "default"
    assert defn.max_iterations == 30
    assert defn.is_read_only is False
    assert defn.prompt == ""
    assert defn.extra == {}


def test_parse_agent_file_extra_fields():
    content = "---\nname: X\ncustom_field: hello\n---\nPrompt."
    defn = parse_agent_file(content)
    assert defn.extra == {"custom_field": "hello"}


def test_parse_agent_file_mode_alias():
    content = "---\nname: X\nmode: plan\n---\nPrompt."
    defn = parse_agent_file(content)
    assert defn.permission_mode == "plan"


def test_parse_agent_file_read_only_alias():
    content = "---\nname: X\nread_only: true\n---\nPrompt."
    defn = parse_agent_file(content)
    assert defn.is_read_only is True


# ── C.2 Built-in Agents ───────────────────────────────────────────

def test_builtin_agents_count():
    assert len(BUILTIN_AGENTS) == 4


def test_builtin_explore_properties():
    assert EXPLORE_AGENT.name == "Explore"
    assert EXPLORE_AGENT.is_read_only is True
    assert EXPLORE_AGENT.model == "haiku"
    assert "Read" in EXPLORE_AGENT.tools


def test_builtin_plan_properties():
    assert PLAN_AGENT.name == "Plan"
    assert PLAN_AGENT.is_read_only is True
    assert PLAN_AGENT.model == "opus"


def test_builtin_verification_properties():
    assert VERIFICATION_AGENT.name == "Verification"
    assert VERIFICATION_AGENT.max_iterations == 50
    assert VERIFICATION_AGENT.model == "sonnet"


def test_builtin_general_purpose_properties():
    assert GENERAL_PURPOSE_AGENT.name == "GeneralPurpose"
    assert "*" in GENERAL_PURPOSE_AGENT.tools


def test_get_builtin_agent_exact():
    assert get_builtin_agent("Explore") is EXPLORE_AGENT


def test_get_builtin_agent_case_insensitive():
    assert get_builtin_agent("explore") is EXPLORE_AGENT
    assert get_builtin_agent("PLAN") is PLAN_AGENT
    assert get_builtin_agent("verification") is VERIFICATION_AGENT


def test_get_builtin_agent_nonexistent():
    assert get_builtin_agent("DoesNotExist") is None


# ── C.3 Fork Semantics ────────────────────────────────────────────

def test_is_in_fork_child_positive_string():
    msgs = [{"role": "user", "content": f"{FORK_BOILERPLATE_TAG}\ndo stuff"}]
    assert is_in_fork_child(msgs) is True


def test_is_in_fork_child_positive_list():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": f"{FORK_BOILERPLATE_TAG}\ndo stuff"}
    ]}]
    assert is_in_fork_child(msgs) is True


def test_is_in_fork_child_negative():
    msgs = [{"role": "user", "content": "normal message"}]
    assert is_in_fork_child(msgs) is False


def test_is_in_fork_child_empty():
    assert is_in_fork_child([]) is False


def test_build_forked_messages_empty():
    result = build_forked_messages([], "do task")
    assert len(result) == 1
    assert FORK_BOILERPLATE_TAG in result[0]["content"]
    assert "do task" in result[0]["content"]


def test_build_forked_messages_assistant_last():
    parent = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "I'll help."},
    ]
    result = build_forked_messages(parent, "child directive")
    # Should have: user, assistant, user(directive)
    assert len(result) == 3
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "user"
    assert "child directive" in str(result[2]["content"])


def test_build_forked_messages_user_last():
    parent = [
        {"role": "user", "content": "hello"},
    ]
    result = build_forked_messages(parent, "child directive")
    # Should have: user, assistant(bridge), user(directive)
    assert len(result) == 3
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "user"
    assert "child directive" in result[2]["content"]


def test_build_forked_messages_preserves_tool_use():
    parent = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "id": "tool_123", "name": "Grep", "input": {}},
        ]},
    ]
    result = build_forked_messages(parent, "child directive")
    assert len(result) == 3
    # The user message should contain tool_result placeholders
    user_content = result[2]["content"]
    assert isinstance(user_content, list)
    tool_results = [b for b in user_content if b.get("type") == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["tool_use_id"] == "tool_123"
    assert tool_results[0]["content"] == FORK_PLACEHOLDER_RESULT


# ── C.4 Background Agent Manager ──────────────────────────────────

def test_background_register(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("test task")
    assert task.status == "running"
    assert task.description == "test task"
    assert task.agent_id


def test_background_complete(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("task1")
    mgr.complete(task.agent_id, "done output")
    assert task.status == "completed"
    assert task.output == "done output"


def test_background_fail(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("task2")
    mgr.fail(task.agent_id, "something broke")
    assert task.status == "failed"
    assert task.error == "something broke"


def test_background_drain_notifications(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("task3")
    mgr.complete(task.agent_id, "output")
    notifs = mgr.drain_notifications()
    assert len(notifs) == 1
    assert notifs[0]["status"] == "completed"
    # Second drain should be empty
    assert mgr.drain_notifications() == []


def test_background_list_running(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    t1 = mgr.register("running task")
    t2 = mgr.register("done task")
    mgr.complete(t2.agent_id, "done")
    running = mgr.list_running()
    assert len(running) == 1
    assert running[0].agent_id == t1.agent_id


def test_background_list_all(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    mgr.register("a")
    mgr.register("b")
    assert len(mgr.list_all()) == 2


def test_background_get_output(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("task")
    mgr.complete(task.agent_id, "full output text")
    output = mgr.get_output(task.agent_id)
    assert output == "full output text"


def test_background_get_output_not_completed(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("task")
    assert mgr.get_output(task.agent_id) is None


def test_background_get_task(tmp_path):
    mgr = BackgroundAgentManager(output_dir=str(tmp_path / "outputs"))
    task = mgr.register("task")
    assert mgr.get_task(task.agent_id) is task
    assert mgr.get_task("nonexistent") is None


# ── C.5 Swarm / Team ──────────────────────────────────────────────

def test_team_message_creation():
    msg = TeamMessage(type="message", from_agent="Alice", content="hello")
    assert msg.type == "message"
    assert msg.from_agent == "Alice"
    assert msg.timestamp > 0


def test_team_mailbox_send_and_read(tmp_path):
    mailbox = TeamMailbox(base_dir=str(tmp_path / "team"))
    msg = TeamMessage(type="message", from_agent="Alice", content="hello Bob")
    mailbox.send("Bob", msg)
    messages = mailbox.read_inbox("Bob")
    assert len(messages) == 1
    assert messages[0].content == "hello Bob"
    assert messages[0].from_agent == "Alice"


def test_team_mailbox_drain(tmp_path):
    mailbox = TeamMailbox(base_dir=str(tmp_path / "team"))
    msg = TeamMessage(type="message", from_agent="A", content="x")
    mailbox.send("B", msg)
    mailbox.read_inbox("B")
    # Second read should be empty (drained)
    assert mailbox.read_inbox("B") == []


def test_team_mailbox_broadcast(tmp_path):
    mailbox = TeamMailbox(base_dir=str(tmp_path / "team"))
    mailbox.broadcast("Leader", "all hands", ["Leader", "Worker1", "Worker2"])
    # Leader should NOT receive own broadcast
    assert mailbox.read_inbox("Leader") == []
    assert len(mailbox.read_inbox("Worker1")) == 1
    assert len(mailbox.read_inbox("Worker2")) == 1


def test_team_mailbox_empty_inbox(tmp_path):
    mailbox = TeamMailbox(base_dir=str(tmp_path / "team"))
    assert mailbox.read_inbox("nobody") == []


def test_team_config_save_load(tmp_path):
    mailbox = TeamMailbox(base_dir=str(tmp_path / "team"))
    config = TeamConfig(
        team_name="alpha",
        members=[
            TeamMember(name="A", role="lead"),
            TeamMember(name="B", role="worker"),
        ],
    )
    mailbox.save_config(config)
    loaded = mailbox.load_config()
    assert loaded is not None
    assert loaded.team_name == "alpha"
    assert len(loaded.members) == 2
    assert loaded.members[0].name == "A"


def test_team_config_load_missing(tmp_path):
    mailbox = TeamMailbox(base_dir=str(tmp_path / "team"))
    assert mailbox.load_config() is None


# ── C.7 Worktree ──────────────────────────────────────────────────

def test_worktree_entry_creation():
    entry = WorktreeEntry(name="feat-1", path="/tmp/wt/feat-1", branch="wt/feat-1")
    assert entry.status == "active"
    assert entry.task_id is None


def test_worktree_manager_save_load_index(tmp_path):
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    # Manually insert an entry and save
    entry = WorktreeEntry(name="test", path=str(tmp_path / "wt/test"), branch="wt/test", task_id=42)
    mgr._index["test"] = entry
    mgr._save_index()

    # Load in a new manager
    mgr2 = WorktreeManager(base_dir=str(tmp_path / "wt"))
    assert "test" in mgr2._index
    assert mgr2._index["test"].task_id == 42
    assert mgr2._index["test"].branch == "wt/test"


@patch("autoharness.agents.worktree.subprocess.run")
def test_worktree_create(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    entry = mgr.create("feature-x", task_id=7)
    assert entry.name == "feature-x"
    assert entry.branch == "wt/feature-x"
    assert entry.task_id == 7
    assert entry.status == "active"
    mock_run.assert_called_once()
    # Should be persisted
    assert mgr.get("feature-x") is entry


@patch("autoharness.agents.worktree.subprocess.run")
def test_worktree_create_duplicate(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    mgr.create("dup")
    with pytest.raises(ValueError, match="already exists"):
        mgr.create("dup")


@patch("autoharness.agents.worktree.subprocess.run")
def test_worktree_create_git_failure(mock_run, tmp_path):
    mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="error")
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    with pytest.raises(RuntimeError, match="Failed to create"):
        mgr.create("fail-wt")


@patch("autoharness.agents.worktree.subprocess.run")
def test_worktree_remove(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    mgr.create("removable")
    mgr.remove("removable")
    assert mgr.get("removable").status == "removed"


@patch("autoharness.agents.worktree.subprocess.run")
def test_worktree_keep(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    mgr.create("keepme", task_id=5)
    mgr.keep("keepme")
    entry = mgr.get("keepme")
    assert entry.status == "kept"
    assert entry.task_id is None


@patch("autoharness.agents.worktree.subprocess.run")
def test_worktree_list_active(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    mgr.create("a1")
    mgr.create("a2")
    mgr.create("a3")
    mgr.remove("a2")
    active = mgr.list_active()
    assert len(active) == 2
    assert {e.name for e in active} == {"a1", "a3"}


def test_worktree_remove_unknown(tmp_path):
    mgr = WorktreeManager(base_dir=str(tmp_path / "wt"))
    with pytest.raises(ValueError, match="Unknown worktree"):
        mgr.remove("nope")
