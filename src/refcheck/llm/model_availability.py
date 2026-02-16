"""Filter models by available API keys and build tier configs."""

import logging
import os

from refcheck.llm.model_registry import (
    DEFAULT_MODELS,
    ModelConfig,
    TierConfig,
)

logger = logging.getLogger(__name__)

# Maps provider name -> the env key litellm checks
_PROVIDER_ENV_MAP: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "nvidia": "NVIDIA_NIM_API_KEY",
    "xai": "XAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def get_available_models(
    providers: dict[str, bool],
) -> dict[str, ModelConfig]:
    """Return only models whose provider API key is available."""
    available: dict[str, ModelConfig] = {}
    for model in DEFAULT_MODELS:
        provider = model.provider
        if providers.get(provider, False) or _key_exists(model.env_key):
            available[model.alias] = model
    logger.info("Available models: %s", list(available.keys()))
    return available


def _key_exists(env_key: str) -> bool:
    return bool(os.environ.get(env_key))


def build_tier_config(
    available: dict[str, ModelConfig],
) -> TierConfig:
    """Build tiers with graceful degradation.

    If a tier is empty, promote from adjacent tiers.
    If only Anthropic available, all tiers use Sonnet.
    """
    tiers: dict[int, list[ModelConfig]] = {0: [], 1: [], 2: [], 3: []}
    for model in available.values():
        tiers[model.tier].append(model)

    # If only one provider (Anthropic), all tiers use its model
    if len(available) == 1:
        single = list(available.values())[0]
        return TierConfig(
            tier0=[single], tier1=[single],
            tier2=[single], tier3=[single],
        )

    # Promote across tiers to fill gaps
    tiers = _fill_empty_tiers(tiers)

    return TierConfig(
        tier0=tiers[0], tier1=tiers[1],
        tier2=tiers[2], tier3=tiers[3],
    )


def _fill_empty_tiers(
    tiers: dict[int, list[ModelConfig]],
) -> dict[int, list[ModelConfig]]:
    """Fill empty tiers by promoting from adjacent tiers."""
    # Tier 0 empty: pull from Tier 1
    if not tiers[0] and tiers[1]:
        tiers[0] = tiers[1][:2]

    # Tier 1 empty: pull from Tier 0 (strongest) + Tier 2
    if not tiers[1]:
        donors = _sorted_by_tier_desc(tiers[0]) + tiers[2]
        tiers[1] = donors[:2]

    # Tier 2 empty: pull from Tier 1 (strongest) or Tier 3
    if not tiers[2]:
        donors = _sorted_by_tier_desc(tiers[1]) + tiers[3]
        tiers[2] = donors[:1]

    # Tier 3 empty: pull from Tier 2
    if not tiers[3] and tiers[2]:
        tiers[3] = tiers[2][:1]

    return tiers


def _sorted_by_tier_desc(
    models: list[ModelConfig],
) -> list[ModelConfig]:
    """Sort models by tier descending (higher tier = more capable)."""
    return sorted(models, key=lambda m: m.tier, reverse=True)
