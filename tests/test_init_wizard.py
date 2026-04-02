"""Tests for the autoharness init wizard — project detection, constitution
templates, and end-to-end generation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from autoharness.cli.main import _detect_project_type
from autoharness.core.constitution import Constitution
from autoharness.templates.constitutions import (
    MINIMAL_CONSTITUTION,
    SECURITY_TEMPLATES,
    STANDARD_CONSTITUTION,
    STRICT_CONSTITUTION,
    get_example_script,
    render_constitution,
)

# -----------------------------------------------------------------------
# Project type detection
# -----------------------------------------------------------------------


class TestDetectProjectType:
    """Verify _detect_project_type for various language ecosystems."""

    def test_python_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "python"
        assert info["language"] == "Python"

    def test_python_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").touch()
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "python"

    def test_python_requirements(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").touch()
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "python"

    def test_node_project(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "node"
        assert "JavaScript" in info["language"]

    def test_go_project(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").touch()
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "go"
        assert info["language"] == "Go"

    def test_rust_project(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").touch()
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "rust"
        assert info["language"] == "Rust"

    def test_unknown_project(self, tmp_path: Path) -> None:
        info = _detect_project_type(tmp_path)
        assert info["project_type"] == "unknown"
        assert info["language"] == "unknown"


class TestDetectGitInfo:
    """Verify git repository detection."""

    def test_detects_git_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        info = _detect_project_type(tmp_path)
        assert info["has_git"] is True
        assert any("Git" in m for m in info["markers"])

    def test_no_git(self, tmp_path: Path) -> None:
        info = _detect_project_type(tmp_path)
        assert info["has_git"] is False


class TestDetectClaudeCodeProject:
    """Verify Claude Code project detection."""

    def test_detects_claude_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        info = _detect_project_type(tmp_path)
        assert info["has_claude"] is True

    def test_detects_claude_md(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").touch()
        info = _detect_project_type(tmp_path)
        assert info["has_claude"] is True

    def test_no_claude(self, tmp_path: Path) -> None:
        info = _detect_project_type(tmp_path)
        assert info["has_claude"] is False


# -----------------------------------------------------------------------
# Constitution templates — valid YAML
# -----------------------------------------------------------------------


class TestTemplatesValidYaml:
    """Each template must parse as valid YAML after variable substitution."""

    @pytest.mark.parametrize("name,template", [
        ("minimal", MINIMAL_CONSTITUTION),
        ("standard", STANDARD_CONSTITUTION),
        ("strict", STRICT_CONSTITUTION),
    ])
    def test_template_is_valid_yaml(self, name: str, template: str) -> None:
        rendered = render_constitution(template, "test-project", "Python")
        data = yaml.safe_load(rendered)
        assert isinstance(data, dict), f"{name} template did not produce a YAML dict"
        assert "version" in data
        assert "identity" in data
        assert "rules" in data
        assert "permissions" in data

    @pytest.mark.parametrize("name,template", [
        ("minimal", MINIMAL_CONSTITUTION),
        ("standard", STANDARD_CONSTITUTION),
        ("strict", STRICT_CONSTITUTION),
    ])
    def test_constitution_from_yaml(self, name: str, template: str) -> None:
        rendered = render_constitution(template, "test-project", "Python")
        c = Constitution.from_yaml(rendered)
        assert c is not None
        assert len(c.rules) > 0
        assert c.identity["name"] == "test-project"

    @pytest.mark.parametrize("name,template", [
        ("minimal", MINIMAL_CONSTITUTION),
        ("standard", STANDARD_CONSTITUTION),
        ("strict", STRICT_CONSTITUTION),
    ])
    def test_constitution_validates_cleanly(self, name: str, template: str) -> None:
        rendered = render_constitution(template, "test-project", "Python")
        c = Constitution.from_yaml(rendered)
        warnings = c.validate()
        assert warnings == [], f"{name} template produced validation warnings: {warnings}"


# -----------------------------------------------------------------------
# Template variable substitution
# -----------------------------------------------------------------------


class TestTemplateSubstitution:
    """Verify that project_name and project_type are injected correctly."""

    def test_project_name_substituted(self) -> None:
        rendered = render_constitution(MINIMAL_CONSTITUTION, "acme-bot", "Go")
        assert "acme-bot" in rendered
        assert "{project_name}" not in rendered

    def test_project_type_substituted(self) -> None:
        rendered = render_constitution(STANDARD_CONSTITUTION, "x", "Rust")
        assert "Rust" in rendered
        assert "{project_type}" not in rendered

    def test_both_substituted(self) -> None:
        rendered = render_constitution(STRICT_CONSTITUTION, "my-app", "Node.js")
        assert "my-app" in rendered
        assert "Node.js" in rendered
        assert "{project_name}" not in rendered
        assert "{project_type}" not in rendered


# -----------------------------------------------------------------------
# Security level mapping
# -----------------------------------------------------------------------


class TestSecurityTemplatesMapping:
    """SECURITY_TEMPLATES must contain all three tiers."""

    def test_keys(self) -> None:
        assert set(SECURITY_TEMPLATES.keys()) == {"minimal", "standard", "strict"}

    def test_minimal_has_few_rules(self) -> None:
        rendered = render_constitution(SECURITY_TEMPLATES["minimal"], "p", "Python")
        data = yaml.safe_load(rendered)
        assert len(data["rules"]) <= 2

    def test_strict_has_many_rules(self) -> None:
        rendered = render_constitution(SECURITY_TEMPLATES["strict"], "p", "Python")
        data = yaml.safe_load(rendered)
        assert len(data["rules"]) >= 5


# -----------------------------------------------------------------------
# Example script generation
# -----------------------------------------------------------------------


class TestExampleScript:
    """Verify that the starter example script is generated correctly."""

    def test_contains_project_name(self) -> None:
        script = get_example_script("my-proj", "coding", "anthropic")
        assert "my-proj" in script

    def test_anthropic_provider(self) -> None:
        script = get_example_script("p", "coding", "anthropic")
        assert "anthropic" in script.lower()

    def test_openai_provider(self) -> None:
        script = get_example_script("p", "rag", "openai")
        assert "openai" in script.lower()

    def test_both_providers(self) -> None:
        script = get_example_script("p", "pipeline", "both")
        assert "anthropic" in script.lower()
        assert "openai" in script.lower()

    def test_is_valid_python(self) -> None:
        script = get_example_script("test", "custom", "anthropic")
        # Should not raise SyntaxError
        compile(script, "<example>", "exec")


# -----------------------------------------------------------------------
# CLI integration (non-interactive end-to-end)
# -----------------------------------------------------------------------


class TestInitCLI:
    """End-to-end tests exercising the Click command via CliRunner."""

    def test_non_interactive_creates_files(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--non-interactive",
            "--security", "standard",
            "--directory", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "constitution.yaml").exists()
        assert (tmp_path / ".autoharness").is_dir()
        assert (tmp_path / ".autoharness" / "skills").is_dir()
        assert (tmp_path / ".autoharness" / "sessions").is_dir()
        assert (tmp_path / "autoharness_example.py").exists()

    def test_non_interactive_minimal(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--non-interactive",
            "--security", "minimal",
            "--directory", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        content = (tmp_path / "constitution.yaml").read_text()
        assert "Minimal governance" in content

    def test_non_interactive_strict(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--non-interactive",
            "--security", "strict",
            "--directory", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        content = (tmp_path / "constitution.yaml").read_text()
        assert "Strict governance" in content

    def test_refuses_overwrite_non_interactive(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        (tmp_path / "constitution.yaml").write_text("existing")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--non-interactive",
            "--security", "standard",
            "--directory", str(tmp_path),
        ])
        assert result.exit_code != 0

    def test_generated_constitution_loads(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--non-interactive",
            "--security", "standard",
            "--directory", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        c = Constitution.load(tmp_path / "constitution.yaml")
        assert c is not None
        assert len(c.rules) > 0

    def test_legacy_template_flag(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--template", "default",
            "--non-interactive",
            "--directory", str(tmp_path),
            "--output", "constitution.yaml",
        ])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "constitution.yaml").exists()

    def test_no_session_persistence(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from autoharness.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "init",
            "--non-interactive",
            "--security", "minimal",
            "--no-session-persistence",
            "--directory", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        assert not (tmp_path / ".autoharness" / "sessions").exists()
