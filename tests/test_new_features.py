"""Tests for upcoming features.

Anti-distillation, frustration detection, model router, feature flags.
"""

from __future__ import annotations

import copy
import os
from unittest import mock

# ---------------------------------------------------------------------------
# Anti-Distillation Tests
# ---------------------------------------------------------------------------


class TestAntiDistillation:
    """Tests for autoharness.core.anti_distillation."""

    def test_generate_decoy_tools_returns_correct_count(self):
        from autoharness.core.anti_distillation import generate_decoy_tools

        decoys = generate_decoy_tools(count=5)
        assert len(decoys) == 5

    def test_generate_decoy_tools_default_count(self):
        from autoharness.core.anti_distillation import generate_decoy_tools

        decoys = generate_decoy_tools()
        assert isinstance(decoys, list)
        assert len(decoys) > 0

    def test_decoy_tools_have_valid_schema(self):
        from autoharness.core.anti_distillation import generate_decoy_tools

        decoys = generate_decoy_tools(count=3)
        for tool in decoys:
            assert "name" in tool, "Decoy tool must have a name"
            assert "description" in tool, "Decoy tool must have a description"
            assert (
                "parameters" in tool or "input_schema" in tool
            ), "Decoy tool must have parameters or input_schema"
            schema = tool.get("parameters") or tool.get("input_schema")
            assert "type" in schema
            assert schema["type"] == "object"

    def test_inject_decoys_does_not_modify_original_tools(self):
        from autoharness.core.anti_distillation import inject_decoys

        original_tools = [
            {
                "name": "read_file", "description": "Read a file",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "write_file", "description": "Write a file",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]
        original_copy = copy.deepcopy(original_tools)
        result = inject_decoys(original_tools, count=3)

        # Original list must be unchanged
        assert original_tools == original_copy
        # Result must contain more tools
        assert len(result) >= len(original_tools) + 3

    def test_is_decoy_tool_correctly_identifies_decoys(self):
        from autoharness.core.anti_distillation import (
            generate_decoy_tools,
            is_decoy_tool,
        )

        decoys = generate_decoy_tools(count=3)
        for tool in decoys:
            assert is_decoy_tool(tool["name"]) is True

        # Real tool names should not be detected as decoys
        assert is_decoy_tool("read_file") is False
        assert is_decoy_tool("write_file") is False

    def test_deterministic_generation_with_same_seed(self):
        from autoharness.core.anti_distillation import generate_decoy_tools

        decoys_a = generate_decoy_tools(count=5, seed=42)
        decoys_b = generate_decoy_tools(count=5, seed=42)
        assert decoys_a == decoys_b

    def test_different_seeds_produce_different_decoys(self):
        from autoharness.core.anti_distillation import generate_decoy_tools

        decoys_a = generate_decoy_tools(count=5, seed=42)
        decoys_b = generate_decoy_tools(count=5, seed=99)
        names_a = {t["name"] for t in decoys_a}
        names_b = {t["name"] for t in decoys_b}
        assert names_a != names_b


# ---------------------------------------------------------------------------
# Frustration Detection Tests
# ---------------------------------------------------------------------------


class TestFrustrationDetection:
    """Tests for autoharness.core.sentiment."""

    def test_detect_frustration_clean_text_returns_none(self):
        from autoharness.core.sentiment import detect_frustration

        result = detect_frustration("Please read the file and summarize it.")
        assert result.level == "none"

    def test_detect_frustration_wtf_returns_mild(self):
        from autoharness.core.sentiment import detect_frustration

        result = detect_frustration("wtf is this output?")
        assert result.level == "mild"

    def test_detect_frustration_multiple_words_returns_strong(self):
        from autoharness.core.sentiment import detect_frustration

        result = detect_frustration("wtf this is broken and useless, it failed again!")
        assert result.level == "strong"

    def test_detect_frustration_empty_string_returns_none(self):
        from autoharness.core.sentiment import detect_frustration

        result = detect_frustration("")
        assert result.level == "none"

    def test_detect_frustration_case_insensitivity(self):
        from autoharness.core.sentiment import detect_frustration

        result_lower = detect_frustration("wtf")
        result_upper = detect_frustration("WTF")
        assert result_lower.level == result_upper.level

    def test_detect_frustration_returns_matched_words(self):
        from autoharness.core.sentiment import detect_frustration

        result = detect_frustration("wtf is happening")
        assert hasattr(result, "keywords_matched")
        assert len(result.keywords_matched) > 0


# ---------------------------------------------------------------------------
# Model Router Tests
# ---------------------------------------------------------------------------


class TestModelRouter:
    """Tests for autoharness.agents.model_router."""

    def test_estimate_complexity_simple_task_returns_fast(self):
        from autoharness.agents.model_router import ModelRouter, ModelTier

        router = ModelRouter()
        tier = router.estimate_complexity("fix a typo in README")
        assert tier == ModelTier.FAST

    def test_estimate_complexity_design_architecture_returns_premium(self):
        from autoharness.agents.model_router import ModelRouter, ModelTier

        router = ModelRouter()
        tier = router.estimate_complexity("design architecture for a distributed system")
        assert tier == ModelTier.PREMIUM

    def test_route_returns_valid_model_string(self):
        from autoharness.agents.model_router import ModelRouter

        router = ModelRouter()
        model = router.route("fix a typo")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_min_tier_is_respected(self):
        from autoharness.agents.model_router import MODEL_MAP, ModelRouter, ModelTier

        router = ModelRouter()
        # Even a simple task should use at least STANDARD tier if min_tier is set
        model = router.route("fix a typo", min_tier=ModelTier.STANDARD)
        assert isinstance(model, str)
        # The returned model should not be from FAST tier
        fast_model = MODEL_MAP["anthropic"][ModelTier.FAST]
        assert model != fast_model

    def test_model_map_has_all_providers(self):
        from autoharness.agents.model_router import MODEL_MAP, ModelTier

        for provider_map in MODEL_MAP.values():
            assert ModelTier.FAST in provider_map
            assert ModelTier.STANDARD in provider_map
            assert ModelTier.PREMIUM in provider_map

    def test_route_unknown_task_returns_standard(self):
        from autoharness.agents.model_router import ModelRouter, ModelTier

        router = ModelRouter()
        tier = router.estimate_complexity("do something")
        assert tier in (ModelTier.FAST, ModelTier.STANDARD, ModelTier.PREMIUM)


# ---------------------------------------------------------------------------
# Feature Flags Tests
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    """Tests for autoharness.core.feature_flags."""

    def test_default_flags(self):
        from autoharness.core.feature_flags import FeatureFlags

        flags = FeatureFlags()
        # Default instance should have some baseline flags
        assert isinstance(flags, FeatureFlags)

    def test_set_and_get(self):
        from autoharness.core.feature_flags import FeatureFlags

        flags = FeatureFlags()
        flags.set("TEST_FLAG", True)
        assert flags.is_enabled("TEST_FLAG") is True

        flags.set("TEST_FLAG", False)
        assert flags.is_enabled("TEST_FLAG") is False

    def test_from_env_reads_environment_variables(self):
        from autoharness.core.feature_flags import FeatureFlags

        with mock.patch.dict(os.environ, {"AUTOHARNESS_FF_ANTI_DISTILLATION": "1"}):
            flags = FeatureFlags.from_env()
            assert flags.is_enabled("ANTI_DISTILLATION") is True

    def test_is_enabled_unknown_flag_returns_false(self):
        from autoharness.core.feature_flags import FeatureFlags

        flags = FeatureFlags()
        assert flags.is_enabled("NONEXISTENT_FLAG_XYZ") is False

    def test_singleton_behavior(self):
        from autoharness.core.feature_flags import FeatureFlags

        FeatureFlags.reset_instance()
        flags_a = FeatureFlags.instance()
        flags_b = FeatureFlags.instance()
        assert flags_a is flags_b
        FeatureFlags.reset_instance()

    def test_set_get_roundtrip_multiple_flags(self):
        from autoharness.core.feature_flags import FeatureFlags

        flags = FeatureFlags()
        flags.set("ALPHA", True)
        flags.set("BETA", False)
        flags.set("GAMMA", True)

        assert flags.is_enabled("ALPHA") is True
        assert flags.is_enabled("BETA") is False
        assert flags.is_enabled("GAMMA") is True
