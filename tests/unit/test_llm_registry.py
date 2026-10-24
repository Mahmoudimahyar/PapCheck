"""Model registry: MODEL_SELECTION defaults, prices, efforts, lookups."""

import pytest

from refcheck.llm.model_lookup import spec_for
from refcheck.llm.model_registry import (
    PROFILE_ROLE_DEFAULTS,
    REGISTRY,
    ROLE_DEFAULTS,
    ROLE_EFFORT,
    get_spec,
)
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.types import ALL_ROLES

_ROLE_KIND = {"screen": "decision", "embedding": "embedding"}


class TestRoleDefaults:
    def test_every_role_has_defaults_in_every_profile(self) -> None:
        for profile in PROFILE_ROLE_DEFAULTS.values():
            assert set(profile) == set(ALL_ROLES)

    def test_defaults_reference_registry_models_of_the_right_kind(self) -> None:
        for profile in PROFILE_ROLE_DEFAULTS.values():
            for role, ids in profile.items():
                for model_id in ids:
                    spec = REGISTRY[model_id]
                    assert spec.kind == _ROLE_KIND.get(role, "chat"), (role, model_id)
                    assert not spec.optional, f"optional model {model_id} used as default"

    def test_model_selection_standard_profile(self) -> None:
        assert ROLE_DEFAULTS["screen"] == ["gpt-6-luna-decisions"]
        assert ROLE_DEFAULTS["verifier"] == ["claude-haiku-5-5", "gpt-6-luna"]
        assert ROLE_DEFAULTS["judge"] == ["claude-sonnet-5-5", "gpt-6.1-sol"]
        assert ROLE_DEFAULTS["confirm"] == ["gpt-6-luna", "gpt-6.1-sol"]
        assert ROLE_DEFAULTS["utility"] == ["gpt-6-luna", "claude-haiku-5-5"]
        assert ROLE_DEFAULTS["embedding"] == ["text-embedding-3-small", "text-embedding-3-large"]

    def test_opus_is_never_a_default(self) -> None:
        # claude-opus-5-5 refused ~24% of biomedical pairs (content filter).
        for profile in PROFILE_ROLE_DEFAULTS.values():
            for ids in profile.values():
                assert "claude-opus-5-5" not in ids

    def test_confirm_is_cross_family_from_verifier(self) -> None:
        # The blind cross-check of a negative verdict must not share the
        # verifier's family; every confirm default differs from the primary verifier.
        verifier = REGISTRY[ROLE_DEFAULTS["verifier"][0]]
        assert all(REGISTRY[i].provider != verifier.provider for i in ROLE_DEFAULTS["confirm"])

    def test_role_efforts(self) -> None:
        assert ROLE_EFFORT["screen"] is None
        assert ROLE_EFFORT["verifier"] == "low"
        assert ROLE_EFFORT["judge"] == "low"
        assert ROLE_EFFORT["confirm"] == "low"
        assert ROLE_EFFORT["utility"] == "none"
        assert ROLE_EFFORT["embedding"] is None

    def test_anthropic_only_profile_stays_on_anthropic(self) -> None:
        profile = PROFILE_ROLE_DEFAULTS["anthropic_only"]
        assert profile["screen"] == [] and profile["embedding"] == []
        assert profile["verifier"] == ["claude-haiku-5-5"]
        assert profile["judge"] == ["claude-sonnet-5-5"]
        assert profile["confirm"] == ["claude-sonnet-5-5"]
        assert profile["utility"] == ["claude-haiku-5-5"]
        for ids in profile.values():
            assert all(REGISTRY[i].provider == "anthropic" for i in ids)


class TestPricesAndLimits:
    @pytest.mark.parametrize(("model_id", "inp", "out"), [
        ("gpt-6-luna-decisions", 0.10, 0.0), ("gpt-6-luna", 0.10, 0.50),
        ("gpt-6.1-sol", 2.0, 10.0), ("claude-sonnet-5-5", 2.0, 10.0),
        ("claude-haiku-5-5", 0.10, 0.50), ("claude-opus-5-5", 4.0, 20.0),
        ("gpt-6-astra", 10.0, 50.0), ("text-embedding-3-small", 0.02, 0.0),
        ("gemini-3.8-flash", 0.75, 3.75), ("gemini-3.5-flash-lite", 0.30, 2.50),
        ("grok-4.3", 1.25, 2.50),
    ])
    def test_prices(self, model_id: str, inp: float, out: float) -> None:
        spec = REGISTRY[model_id]
        assert spec.input_cost_per_m == inp
        assert spec.output_cost_per_m == out

    def test_no_model_supports_temperature(self) -> None:
        assert not any(spec.supports_temperature for spec in REGISTRY.values())

    def test_large_embedding_uses_1024_dimensions(self) -> None:
        assert REGISTRY["text-embedding-3-large"].dimensions == 1024

    def test_env_keys_filled_from_provider(self) -> None:
        assert REGISTRY["claude-sonnet-5-5"].env_keys == [
            "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_BACKUP",
        ]
        assert "GROK_API_KEY" in REGISTRY["grok-4.3"].env_keys


class TestEffortMapping:
    def test_sol_rejects_none_so_none_maps_to_low(self) -> None:
        assert REGISTRY["gpt-6.1-sol"].effective_effort("none") == "low"

    def test_claude_none_maps_to_low(self) -> None:
        # "none" on Claude would mean the server default (medium/high).
        assert REGISTRY["claude-haiku-5-5"].effective_effort("none") == "low"

    def test_luna_accepts_none_and_low(self) -> None:
        luna = REGISTRY["gpt-6-luna"]
        assert luna.effective_effort("none") == "none"
        assert luna.effective_effort("low") == "low"

    def test_non_reasoning_models_never_get_effort(self) -> None:
        assert REGISTRY["grok-4.3"].effective_effort("medium") is None
        assert REGISTRY["text-embedding-3-small"].effective_effort("low") is None

    def test_with_effort_returns_copy(self) -> None:
        sonnet = REGISTRY["claude-sonnet-5-5"]
        low = sonnet.with_effort("low")
        assert low.reasoning_effort == "low"
        assert sonnet.reasoning_effort == "medium"

    def test_unknown_effort_goes_up_to_next_supported(self) -> None:
        spec = ModelSpec(id="x", litellm_id="x/x", provider="x", allowed_efforts=["high"])
        assert spec.effective_effort("minimal") == "high"


class TestLookup:
    def test_litellm_id_prefers_chat_model(self) -> None:
        spec = get_spec("openai/gpt-6-luna")
        assert spec is not None and spec.kind == "chat"

    def test_kind_filter_finds_decision_model(self) -> None:
        spec = get_spec("openai/gpt-6-luna", "decision")
        assert spec is not None and spec.id == "gpt-6-luna-decisions"

    def test_spec_for_unknown_model_builds_adhoc_spec(self) -> None:
        spec = spec_for("anthropic/claude-new-model")
        assert spec.provider == "anthropic"
        assert spec.litellm_id == "anthropic/claude-new-model"
        assert spec.env_keys[0] == "ANTHROPIC_API_KEY"

    def test_spec_for_bare_name_guesses_provider(self) -> None:
        spec = spec_for("gpt-4o-mini")
        assert spec.provider == "openai" and spec.litellm_id == "openai/gpt-4o-mini"
        assert spec.input_cost_per_m > 0  # priced from litellm's cost map
