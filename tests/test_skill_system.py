"""Tests for the autoharness skill system (Phase 4)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from autoharness.skills.frontmatter import ParsedSkill, SkillMetadata, parse_skill_file
from autoharness.skills.loader import (
    SkillRegistry,
    discover_skills,
    load_skills_into_registry,
)
from autoharness.skills.skill_tool import SkillTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SKILL = textwrap.dedent("""\
    ---
    name: test-skill
    description: A test skill
    allowed-tools: [Read, Edit, Bash]
    model: haiku
    effort: 5m
    version: "1.0"
    tags: [testing, demo]
    ---

    # Test Skill

    Do the thing.
""")

MINIMAL_SKILL = textwrap.dedent("""\
    ---
    name: minimal
    ---

    Body text.
""")


def _make_skill_dir(tmp_path: Path, name: str, content: str) -> Path:
    """Create a skills/<name>/SKILL.md structure."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


# ---------------------------------------------------------------------------
# E.1  parse_skill_file
# ---------------------------------------------------------------------------

class TestParseSkillFile:
    def test_valid_frontmatter(self) -> None:
        result = parse_skill_file(VALID_SKILL, "test.md")
        assert result.metadata.name == "test-skill"
        assert result.metadata.description == "A test skill"
        assert result.metadata.allowed_tools == ["Read", "Edit", "Bash"]
        assert result.metadata.model == "haiku"
        assert result.metadata.effort == "5m"
        assert result.metadata.version == "1.0"
        assert result.metadata.tags == ["testing", "demo"]
        assert result.metadata.disabled is False
        assert "# Test Skill" in result.body
        assert result.source_path == "test.md"

    def test_missing_name_raises(self) -> None:
        content = "---\ndescription: no name\n---\n\nbody"
        with pytest.raises(ValueError, match="name"):
            parse_skill_file(content)

    def test_invalid_yaml_raises(self) -> None:
        content = "---\n: invalid: yaml: {{{\n---\n\nbody"
        with pytest.raises(ValueError, match="Invalid YAML"):
            parse_skill_file(content)

    def test_no_frontmatter_raises(self) -> None:
        with pytest.raises(ValueError, match="missing YAML frontmatter"):
            parse_skill_file("Just some text without frontmatter")

    def test_extra_fields_preserved(self) -> None:
        content = "---\nname: x\ncustom_field: 42\nanother: hello\n---\n\nbody"
        result = parse_skill_file(content)
        assert result.metadata.extra == {"custom_field": 42, "another": "hello"}

    def test_allowed_tools_underscore_variant(self) -> None:
        content = "---\nname: x\nallowed_tools: [Grep]\n---\n\nbody"
        result = parse_skill_file(content)
        assert result.metadata.allowed_tools == ["Grep"]

    def test_allowed_tools_hyphen_variant(self) -> None:
        content = "---\nname: x\nallowed-tools: [Read, Write]\n---\n\nbody"
        result = parse_skill_file(content)
        assert result.metadata.allowed_tools == ["Read", "Write"]

    def test_frontmatter_non_dict_raises(self) -> None:
        content = "---\n- list item\n---\n\nbody"
        with pytest.raises(ValueError, match="YAML mapping"):
            parse_skill_file(content)

    def test_source_path_in_error(self) -> None:
        with pytest.raises(ValueError, match=r"myfile\.md"):
            parse_skill_file("no frontmatter", source_path="myfile.md")


# ---------------------------------------------------------------------------
# E.1  SkillMetadata defaults
# ---------------------------------------------------------------------------

class TestSkillMetadata:
    def test_defaults(self) -> None:
        m = SkillMetadata(name="foo")
        assert m.description == ""
        assert m.allowed_tools == []
        assert m.model is None
        assert m.effort is None
        assert m.disabled is False
        assert m.version is None
        assert m.tags == []
        assert m.extra == {}


# ---------------------------------------------------------------------------
# E.2  SkillRegistry
# ---------------------------------------------------------------------------

def _make_parsed_skill(
    name: str, description: str = "",
    disabled: bool = False, body: str = "body",
) -> ParsedSkill:
    return ParsedSkill(
        metadata=SkillMetadata(name=name, description=description, disabled=disabled),
        body=body,
    )


class TestSkillRegistry:
    def test_register_and_get(self) -> None:
        reg = SkillRegistry()
        skill = _make_parsed_skill("alpha")
        reg.register(skill)
        assert reg.get("alpha") is skill
        assert reg.get("nonexistent") is None

    def test_list_all(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("a"))
        reg.register(_make_parsed_skill("b"))
        assert len(reg.list_all()) == 2

    def test_list_enabled(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("a"))
        reg.register(_make_parsed_skill("b", disabled=True))
        enabled = reg.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].metadata.name == "a"

    def test_get_prompt_descriptions_empty(self) -> None:
        reg = SkillRegistry()
        assert reg.get_prompt_descriptions() == ""

    def test_get_prompt_descriptions_format(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("beta", description="Does beta things"))
        reg.register(_make_parsed_skill("alpha", description="Does alpha things"))
        result = reg.get_prompt_descriptions()
        assert "alpha: Does alpha things" in result
        assert "beta: Does beta things" in result
        # alpha should come before beta (sorted)
        assert result.index("alpha") < result.index("beta")

    def test_get_prompt_descriptions_excludes_disabled(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("on", description="enabled"))
        reg.register(_make_parsed_skill("off", description="disabled", disabled=True))
        result = reg.get_prompt_descriptions()
        assert "on" in result
        assert "off" not in result

    def test_get_skill_body_found(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("s", body="the body"))
        assert reg.get_skill_body("s") == "the body"

    def test_get_skill_body_not_found(self) -> None:
        reg = SkillRegistry()
        result = reg.get_skill_body("missing")
        assert "Error" in result and "missing" in result

    def test_get_skill_body_disabled(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("d", disabled=True))
        result = reg.get_skill_body("d")
        assert "disabled" in result

    def test_len(self) -> None:
        reg = SkillRegistry()
        assert len(reg) == 0
        reg.register(_make_parsed_skill("x"))
        assert len(reg) == 1

    def test_contains(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("x"))
        assert "x" in reg
        assert "y" not in reg


# ---------------------------------------------------------------------------
# E.2  discover_skills / load_skills_into_registry
# ---------------------------------------------------------------------------

class TestDiscoverSkills:
    def test_discover_from_temp_dir(self, tmp_path: Path) -> None:
        _make_skill_dir(tmp_path, "my-skill", VALID_SKILL)
        _make_skill_dir(tmp_path, "min-skill", MINIMAL_SKILL)
        skills = discover_skills(tmp_path)
        names = {s.metadata.name for s in skills}
        assert "test-skill" in names
        assert "minimal" in names

    def test_discover_skips_nonexistent_dir(self) -> None:
        skills = discover_skills("/tmp/nonexistent_dir_abc123")
        assert skills == []

    def test_discover_invalid_skill_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        bad = tmp_path / "bad-skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
        import logging
        with caplog.at_level(logging.WARNING):
            skills = discover_skills(tmp_path)
        assert len(skills) == 0
        assert "Failed to load skill" in caplog.text

    def test_later_dir_overrides_earlier(self, tmp_path: Path) -> None:
        dir1 = tmp_path / "global"
        dir2 = tmp_path / "project"
        _make_skill_dir(dir1, "s", "---\nname: s\n---\n\nglobal body")
        _make_skill_dir(dir2, "s", "---\nname: s\n---\n\nproject body")
        skills = discover_skills(dir1, dir2)
        assert len(skills) == 1
        assert skills[0].body == "project body"


class TestLoadSkillsIntoRegistry:
    def test_load_from_project_dir(self, tmp_path: Path) -> None:
        _make_skill_dir(tmp_path, "sk", MINIMAL_SKILL)
        reg = SkillRegistry()
        count = load_skills_into_registry(reg, project_dir=tmp_path)
        assert count == 1
        assert "minimal" in reg


# ---------------------------------------------------------------------------
# E.3  SkillTool
# ---------------------------------------------------------------------------

class TestSkillTool:
    def test_execute_without_args(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("commit", body="Run git commit"))
        tool = SkillTool(reg)
        result = tool.execute("commit")
        assert "<command-name>commit</command-name>" in result
        assert "Run git commit" in result
        assert "<command-args>" not in result

    def test_execute_with_args(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_parsed_skill("commit", body="Run git commit"))
        tool = SkillTool(reg)
        result = tool.execute("commit", args="-m 'fix'")
        assert "<command-name>commit</command-name>" in result
        assert "<command-args>-m 'fix'</command-args>" in result
        assert "Run git commit" in result

    def test_execute_unknown_skill(self) -> None:
        reg = SkillRegistry()
        tool = SkillTool(reg)
        result = tool.execute("nonexistent")
        assert "Error" in result

    def test_to_api_schema(self) -> None:
        reg = SkillRegistry()
        tool = SkillTool(reg)
        schema = tool.to_api_schema()
        assert schema["name"] == "Skill"
        assert "input_schema" in schema
        assert "skill" in schema["input_schema"]["properties"]
        assert schema["input_schema"]["required"] == ["skill"]
