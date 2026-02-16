"""Tests for model registry and availability."""

import os
from unittest.mock import patch

import pytest

from refcheck.llm.model_availability import (
    build_tier_config,
    get_available_models,
)
from refcheck.llm.model_registry import DEFAULT_MODELS, ModelConfig


class TestDefaultModels:
    """Validate DEFAULT_MODELS integrity."""

    def test_all_models_have_short_abbreviation(self) -> None:
        for m in DEFAULT_MODELS:
            assert 2 <= len(m.abbreviation) <= 3, (
                f"{m.alias} abbreviation '{m.abbreviation}' not 2-3 chars"
            )

    def test_unique_aliases(self) -> None:
        aliases = [m.alias for m in DEFAULT_MODELS]
        assert len(aliases) == len(set(aliases))

    def test_unique_abbreviations(self) -> None:
        abbrevs = [m.abbreviation for m in DEFAULT_MODELS]
        assert len(abbrevs) == len(set(abbrevs))

    def test_seven_models_defined(self) -> None:
        assert len(DEFAULT_MODELS) == 7

    def test_tiers_correct(self) -> None:
        tier0 = [m for m in DEFAULT_MODELS if m.tier == 0]
        tier1 = [m for m in DEFAULT_MODELS if m.tier == 1]
        tier2 = [m for m in DEFAULT_MODELS if m.tier == 2]
        tier3 = [m for m in DEFAULT_MODELS if m.tier == 3]
        assert len(tier0) == 3
        assert len(tier1) == 2
        assert len(tier2) == 1
        assert len(tier3) == 1


class TestGetAvailableModels:
    """Test model filtering by provider availability."""

    def test_all_providers_available(self) -> None:
        providers = {
            "gemini": True, "nvidia": True,
            "xai": True, "anthropic": True,
        }
        available = get_available_models(providers)
        assert len(available) == 7

    def test_only_anthropic(self) -> None:
        providers = {
            "gemini": False, "nvidia": False,
            "xai": False, "anthropic": True,
        }
        # Clear env keys to prevent fallback detection
        with patch.dict(os.environ, {}, clear=True):
            os.environ["ANTHROPIC_API_KEY"] = "test"
            available = get_available_models(providers)
        assert len(available) == 1
        assert "sonnet" in available

    def test_nvidia_only_gets_four_models(self) -> None:
        providers = {
            "gemini": False, "nvidia": True,
            "xai": False, "anthropic": False,
        }
        with patch.dict(os.environ, {}, clear=True):
            os.environ["NVIDIA_NIM_API_KEY"] = "test"
            available = get_available_models(providers)
        # llama_8b, qwq_32b, llama_70b, deepseek_v3
        assert len(available) == 4

    def test_no_providers_returns_empty(self) -> None:
        providers = {
            "gemini": False, "nvidia": False,
            "xai": False, "anthropic": False,
        }
        with patch.dict(os.environ, {}, clear=True):
            available = get_available_models(providers)
        assert len(available) == 0


class TestBuildTierConfig:
    """Test tier configuration and graceful degradation."""

    def test_full_config_populates_all_tiers(self) -> None:
        providers = {
            "gemini": True, "nvidia": True,
            "xai": True, "anthropic": True,
        }
        available = get_available_models(providers)
        tc = build_tier_config(available)
        assert len(tc.tier0) == 3
        assert len(tc.tier1) == 2
        assert len(tc.tier2) == 1
        assert len(tc.tier3) == 1

    def test_single_provider_all_tiers_same(self) -> None:
        sonnet = DEFAULT_MODELS[-1]  # Sonnet is last
        available = {sonnet.alias: sonnet}
        tc = build_tier_config(available)
        assert len(tc.tier0) == 1
        assert tc.tier0[0].alias == "sonnet"
        assert tc.tier3[0].alias == "sonnet"

    def test_graceful_degradation_fills_empty_tiers(self) -> None:
        # Only Tier 0 models
        tier0_models = {
            m.alias: m for m in DEFAULT_MODELS if m.tier == 0
        }
        tc = build_tier_config(tier0_models)
        # Tier 1, 2, 3 should be filled from Tier 0
        assert len(tc.tier1) > 0
        assert len(tc.tier2) > 0
        assert len(tc.tier3) > 0
