"""Model registry: defines all available LLM models and tier configs."""

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Configuration for a single LLM model."""

    alias: str
    name: str
    abbreviation: str
    litellm_id: str
    tier: int
    input_cost_per_m: float
    output_cost_per_m: float
    max_context: int
    provider: str
    env_key: str
    max_output_tokens: int = 4096


class TierConfig(BaseModel):
    """Tier layout for the voting system."""

    tier0: list[ModelConfig] = Field(default_factory=list)
    tier1: list[ModelConfig] = Field(default_factory=list)
    tier2: list[ModelConfig] = Field(default_factory=list)
    tier3: list[ModelConfig] = Field(default_factory=list)


# All verified model IDs from Phase 0 connectivity test
DEFAULT_MODELS: list[ModelConfig] = [
    ModelConfig(
        alias="gemini_flash", name="Gemini 2.0 Flash",
        abbreviation="GF", litellm_id="gemini/gemini-2.0-flash",
        tier=0, input_cost_per_m=0.10, output_cost_per_m=0.40,
        max_context=1_048_576, provider="gemini",
        env_key="GEMINI_API_KEY",
    ),
    ModelConfig(
        alias="llama_8b", name="Llama 3.1 8B",
        abbreviation="L8", litellm_id="nvidia_nim/meta/llama-3.1-8b-instruct",
        tier=0, input_cost_per_m=0.0, output_cost_per_m=0.0,
        max_context=128_000, provider="nvidia",
        env_key="NVIDIA_NIM_API_KEY",
    ),
    ModelConfig(
        alias="qwq_32b", name="QwQ 32B",
        abbreviation="QwQ", litellm_id="nvidia_nim/qwen/qwq-32b",
        tier=0, input_cost_per_m=0.0, output_cost_per_m=0.0,
        max_context=32_768, provider="nvidia",
        env_key="NVIDIA_NIM_API_KEY",
    ),
    ModelConfig(
        alias="llama_70b", name="Llama 3.3 70B",
        abbreviation="L70", litellm_id="nvidia_nim/meta/llama-3.3-70b-instruct",
        tier=1, input_cost_per_m=0.0, output_cost_per_m=0.0,
        max_context=128_000, provider="nvidia",
        env_key="NVIDIA_NIM_API_KEY",
    ),
    ModelConfig(
        alias="grok_mini", name="Grok 3 Mini",
        abbreviation="GRK", litellm_id="xai/grok-3-mini-fast-beta",
        tier=1, input_cost_per_m=0.30, output_cost_per_m=0.50,
        max_context=131_072, provider="xai",
        env_key="XAI_API_KEY",
    ),
    ModelConfig(
        alias="deepseek_v3", name="DeepSeek V3.1",
        abbreviation="DS", litellm_id="nvidia_nim/deepseek-ai/deepseek-v3.1",
        tier=2, input_cost_per_m=0.0, output_cost_per_m=0.0,
        max_context=32_768, provider="nvidia",
        env_key="NVIDIA_NIM_API_KEY",
    ),
    ModelConfig(
        alias="sonnet", name="Claude Sonnet 4.5",
        abbreviation="SON", litellm_id="anthropic/claude-sonnet-4-5-20250929",
        tier=3, input_cost_per_m=3.0, output_cost_per_m=15.0,
        max_context=200_000, provider="anthropic",
        env_key="ANTHROPIC_API_KEY",
    ),
]
