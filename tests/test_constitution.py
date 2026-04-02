"""Tests for autoharness.core.constitution — Constitution loading, merging, validation."""

from __future__ import annotations

import warnings

import pytest

from autoharness.core.constitution import Constitution, ConstitutionError
from autoharness.core.types import (
    Enforcement,
)

# -----------------------------------------------------------------------
# Default constitution
# -----------------------------------------------------------------------


class TestConstitutionDefault:
    def test_creates_successfully(self):
        c = Constitution.default()
        assert c is not None

    def test_has_rules(self):
        c = Constitution.default()
        assert len(c.rules) > 0

    def test_has_identity(self):
        c = Constitution.default()
        assert c.identity["name"] == "autoharness-default"

    def test_has_permissions(self):
        c = Constitution.default()
        assert "tools" in c.permissions
        assert "bash" in c.permissions["tools"]

    def test_has_risk_config(self):
        c = Constitution.default()
        assert c.risk_config["classifier"] == "rules"
        thresholds = c.risk_config["thresholds"]
        assert thresholds["low"] == "allow"
        assert thresholds["critical"] == "deny"

    def test_has_hook_config(self):
        c = Constitution.default()
        assert c.hook_config["profile"] == "standard"

    def test_has_audit_config(self):
        c = Constitution.default()
        assert c.audit_config["enabled"] is True
        assert c.audit_config["format"] == "jsonl"

    def test_repr(self):
        c = Constitution.default()
        r = repr(c)
        assert "autoharness-default" in r

    def test_validate_clean(self):
        c = Constitution.default()
        issues = c.validate()
        assert issues == []


# -----------------------------------------------------------------------
# Load from YAML string
# -----------------------------------------------------------------------


class TestConstitutionFromYaml:
    def test_minimal_yaml(self):
        yaml_str = """
version: "1.0"
identity:
  name: test
  description: Test constitution
rules: []
"""
        c = Constitution.from_yaml(yaml_str)
        assert c.identity["name"] == "test"

    def test_empty_yaml_uses_defaults(self):
        c = Constitution.from_yaml("")
        assert c is not None
        assert c.config.version == "1.0"

    def test_yaml_with_rules(self):
        yaml_str = """
rules:
  - id: no-rm
    description: Do not use rm
    severity: error
    enforcement: hook
"""
        c = Constitution.from_yaml(yaml_str)
        assert len(c.rules) == 1
        assert c.rules[0].id == "no-rm"
        assert c.rules[0].enforcement == Enforcement.hook

    def test_invalid_yaml_raises(self):
        with pytest.raises(ConstitutionError, match="Invalid YAML"):
            Constitution.from_yaml("{{{\n  bad: [yaml: {unterminated")

    def test_non_mapping_yaml_raises(self):
        with pytest.raises(ConstitutionError, match="mapping"):
            Constitution.from_yaml("- a list\n- not a dict")


# -----------------------------------------------------------------------
# Load from dict
# -----------------------------------------------------------------------


class TestConstitutionFromDict:
    def test_empty_dict(self):
        c = Constitution.from_dict({})
        assert c is not None

    def test_with_identity(self):
        c = Constitution.from_dict({"identity": {"name": "my-agent"}})
        assert c.identity["name"] == "my-agent"

    def test_unknown_keys_warn(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Constitution.from_dict({"unknown_field": "value"})
            assert len(w) == 1
            assert "unknown_field" in str(w[0].message).lower()

    def test_invalid_data_raises(self):
        with pytest.raises(ConstitutionError, match="validation failed"):
            Constitution.from_dict({
                "risk": {
                    "thresholds": {"low": "invalid_action_xyz"},
                    "classifier": "rules",
                    "custom_rules": [],
                }
            })


# -----------------------------------------------------------------------
# Load from file
# -----------------------------------------------------------------------


class TestConstitutionLoad:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Constitution.load("/nonexistent/path/constitution.yaml")

    def test_load_from_file(self, tmp_path):
        yaml_content = """
version: "1.0"
identity:
  name: file-test
rules:
  - id: test-rule
    description: Test
"""
        f = tmp_path / "constitution.yaml"
        f.write_text(yaml_content)
        c = Constitution.load(f)
        assert c.identity["name"] == "file-test"
        assert len(c.rules) == 1

    def test_load_directory_raises(self, tmp_path):
        with pytest.raises(ConstitutionError, match="not a file"):
            Constitution.load(tmp_path)


# -----------------------------------------------------------------------
# Merge
# -----------------------------------------------------------------------


class TestConstitutionMerge:
    def test_merge_identity_override(self):
        base = Constitution.from_dict({"identity": {"name": "base"}})
        override = Constitution.from_dict({"identity": {"name": "override"}})
        merged = Constitution.merge(base, override)
        assert merged.identity["name"] == "override"

    def test_merge_rules_by_id(self):
        base = Constitution.from_dict({
            "rules": [
                {"id": "rule-1", "description": "Base version"},
                {"id": "rule-2", "description": "Only in base"},
            ]
        })
        override = Constitution.from_dict({
            "rules": [
                {"id": "rule-1", "description": "Override version"},
                {"id": "rule-3", "description": "Only in override"},
            ]
        })
        merged = Constitution.merge(base, override)
        rule_ids = {r.id for r in merged.rules}
        assert rule_ids == {"rule-1", "rule-2", "rule-3"}
        # Override version wins for rule-1
        rule1 = next(r for r in merged.rules if r.id == "rule-1")
        assert rule1.description == "Override version"

    def test_merge_tool_permissions(self):
        base = Constitution.from_dict({
            "permissions": {
                "defaults": {"unknown_tool": "ask"},
                "tools": {
                    "bash": {"policy": "restricted", "deny_patterns": [r"rm"]},
                },
            }
        })
        override = Constitution.from_dict({
            "permissions": {
                "defaults": {"unknown_tool": "deny"},
                "tools": {
                    "file_write": {"policy": "restricted"},
                },
            }
        })
        merged = Constitution.merge(base, override)
        tools = merged.permissions["tools"]
        assert "bash" in tools
        assert "file_write" in tools

    def test_merge_preserves_base_when_no_override(self):
        base = Constitution.default()
        empty = Constitution.from_dict({})
        merged = Constitution.merge(base, empty)
        assert len(merged.rules) == len(base.rules)


# -----------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------


class TestConstitutionValidation:
    def test_duplicate_rule_ids(self):
        c = Constitution.from_dict({
            "rules": [
                {"id": "dup", "description": "First"},
                {"id": "dup", "description": "Second"},
            ]
        })
        issues = c.validate()
        assert any("Duplicate rule ID" in i for i in issues)

    def test_no_identity_name(self):
        c = Constitution.from_dict({"identity": {"name": "", "description": "x"}})
        issues = c.validate()
        assert any("identity name" in i.lower() for i in issues)


# -----------------------------------------------------------------------
# Query methods
# -----------------------------------------------------------------------


class TestConstitutionQueries:
    def test_get_rules_for_enforcement_hook(self):
        c = Constitution.default()
        hook_rules = c.get_rules_for_enforcement("hook")
        for r in hook_rules:
            assert r.enforcement == Enforcement.hook

    def test_get_rules_for_enforcement_prompt(self):
        c = Constitution.default()
        prompt_rules = c.get_rules_for_enforcement("prompt")
        for r in prompt_rules:
            assert r.enforcement == Enforcement.prompt

    def test_get_rules_for_enforcement_unknown(self):
        c = Constitution.default()
        result = c.get_rules_for_enforcement("nonexistent")
        assert result == []

    def test_get_tool_permission_exists(self):
        c = Constitution.default()
        tp = c.get_tool_permission("bash")
        assert tp is not None
        assert tp.policy == "restricted"

    def test_get_tool_permission_missing(self):
        c = Constitution.default()
        tp = c.get_tool_permission("nonexistent_tool")
        assert tp is None

    def test_equality(self):
        c1 = Constitution.default()
        c2 = Constitution.default()
        assert c1 == c2

    def test_not_equal_to_other_type(self):
        c = Constitution.default()
        assert c != "not a constitution"
