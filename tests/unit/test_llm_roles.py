"""Role resolution: defaults, fallback, env overrides, privacy profile."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from refcheck.llm import keys
from refcheck.llm.model_registry import REGISTRY
from refcheck.llm.roles import (
    mark_available,
    mark_unavailable,
    privacy_profile,
    resolve_role,
    role_candidates,
    role_status,
    same_family,
    screen_enabled,
    unavailable_models,
)
from tests.unit.llm_fakes import isolated_llm_env


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def _resolved(role: str) -> str | None:
    spec = resolve_role(role)  # type: ignore[arg-type]
    return spec.id if spec else None


class TestDefaults:
    def test_standard_profile_resolution(self) -> None:
        assert _resolved("screen") == "gpt-6-luna-decisions"
        assert _resolved("verifier") == "claude-haiku-5-5"
        assert _resolved("judge") == "claude-sonnet-5-5"
        assert _resolved("confirm") == "gpt-6-luna"
        assert _resolved("utility") == "gpt-6-luna"
        assert _resolved("embedding") == "text-embedding-3-small"

    def test_role_effort_applied_to_resolved_spec(self) -> None:
        assert resolve_role("verifier").reasoning_effort == "low"  # type: ignore[union-attr]
        assert resolve_role("judge").reasoning_effort == "low"  # type: ignore[union-attr]
        assert resolve_role("confirm").reasoning_effort == "low"  # type: ignore[union-attr]
        assert resolve_role("utility").reasoning_effort == "none"  # type: ignore[union-attr]

    def test_registry_spec_not_mutated_by_role_effort(self) -> None:
        assert resolve_role("judge").reasoning_effort == "low"  # type: ignore[union-attr]
        assert resolve_role("confirm").reasoning_effort == "low"  # type: ignore[union-attr]
        assert REGISTRY["claude-sonnet-5-5"].reasoning_effort == "medium"
        assert REGISTRY["gpt-6-luna"].reasoning_effort == "none"


class TestFallback:
    def test_missing_openai_key_falls_back_to_anthropic(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY")
        keys.reset_keys()
        assert _resolved("verifier") == "claude-haiku-5-5"
        assert _resolved("utility") == "claude-haiku-5-5"
        assert _resolved("judge") == "claude-sonnet-5-5"
        # Every normal confirm candidate is OpenAI (cross-family from the Claude verifier);
        # V5.8: without an OpenAI key confirm degrades to Sonnet (same family -> review).
        assert _resolved("confirm") == "claude-sonnet-5-5"
        assert _resolved("screen") is None
        assert _resolved("embedding") is None

    def test_mark_unavailable_moves_to_next_candidate(self) -> None:
        mark_unavailable("claude-sonnet-5-5", "not_found: gone")
        assert _resolved("judge") == "gpt-6.1-sol"
        assert "claude-sonnet-5-5" in unavailable_models()
        mark_available("claude-sonnet-5-5")
        assert _resolved("judge") == "claude-sonnet-5-5"

    def test_exhausted_anthropic_keys_fall_back_to_openai_judge(self) -> None:
        keys.rotate("anthropic", reason="billing")
        assert _resolved("judge") == "claude-sonnet-5-5"  # backup key still usable
        keys.rotate("anthropic", reason="billing")
        assert _resolved("judge") == "gpt-6.1-sol"

    def test_exclude_skips_candidates(self) -> None:
        spec = resolve_role("judge", exclude=["claude-sonnet-5-5"])
        assert spec is not None and spec.id == "gpt-6.1-sol"
        spec = resolve_role("confirm", exclude=["gpt-6-luna"])
        assert spec is not None and spec.id == "gpt-6.1-sol"
        spec = resolve_role("confirm", exclude=["gpt-6-luna", "gpt-6.1-sol"])
        assert spec is not None and spec.id == "claude-sonnet-5-5"  # V5.8 degraded fallback
        assert resolve_role("confirm", exclude=["gpt-6-luna", "gpt-6.1-sol",
                                                "claude-sonnet-5-5"]) is None

    def test_status_reports_reason_when_role_dead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY")
        keys.reset_keys()
        status = role_status()["embedding"]
        assert not status.available
        assert "no usable openai API key" in (status.reason or "")
        assert role_status()["utility"].fallback_index == 1
        assert role_status()["verifier"].fallback_index == 0
        confirm = role_status()["confirm"]
        assert confirm.available and confirm.model_id == "claude-sonnet-5-5"
        assert confirm.degraded and confirm.cause == "no_key" and confirm.persistent
        assert "gpt-6.1-sol" in (confirm.reason or "")


class TestEnvOverrides:
    def test_single_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An override may pick a registry model that is no longer a default.
        monkeypatch.setenv("REFCHECK_JUDGE_MODEL", "claude-opus-5-5")
        assert [s.id for s in role_candidates("judge")] == ["claude-opus-5-5"]
        assert resolve_role("judge").reasoning_effort == "low"  # type: ignore[union-attr]

    def test_comma_list_override_keeps_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_VERIFIER_MODEL", "claude-haiku-5-5, gpt-6-luna")
        assert [s.id for s in role_candidates("verifier")] == ["claude-haiku-5-5", "gpt-6-luna"]

    def test_override_with_litellm_id_and_unknown_model(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REFCHECK_UTILITY_MODEL", "openai/gpt-6-luna,openai/some-new-model")
        ids = [s.id for s in role_candidates("utility")]
        assert ids == ["gpt-6-luna", "openai/some-new-model"]

    def test_effort_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_VERIFIER_EFFORT", "medium")
        monkeypatch.setenv("REFCHECK_CONFIRM_EFFORT", "none")
        assert resolve_role("verifier").reasoning_effort == "medium"  # type: ignore[union-attr]
        assert resolve_role("confirm").reasoning_effort == "none"  # type: ignore[union-attr]

    def test_effort_override_adapted_per_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # "none" is not a Claude effort, so the haiku verifier gets "low".
        monkeypatch.setenv("REFCHECK_VERIFIER_EFFORT", "none")
        assert resolve_role("verifier").reasoning_effort == "low"  # type: ignore[union-attr]

    def test_screen_disabled_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_SCREEN_ENABLED", "false")
        assert not screen_enabled()
        assert resolve_role("screen") is None
        assert role_status()["screen"].reason == "role disabled"

    def test_screen_override_uses_decision_kind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_SCREEN_MODEL", "openai/gpt-6-luna")
        spec = resolve_role("screen")
        assert spec is not None and spec.kind == "decision"


class TestPrivacyProfile:
    def test_anthropic_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
        assert privacy_profile() == "anthropic_only"
        assert not screen_enabled()
        assert _resolved("screen") is None
        assert _resolved("embedding") is None
        assert _resolved("verifier") == "claude-haiku-5-5"
        assert _resolved("judge") == "claude-sonnet-5-5"
        assert _resolved("confirm") == "claude-sonnet-5-5"
        assert _resolved("utility") == "claude-haiku-5-5"
        # The cross-check is same-family under this profile (cascade flags it for review).
        assert same_family(resolve_role("verifier"), resolve_role("confirm"))
        assert same_family(resolve_role("judge"), resolve_role("confirm"))

    def test_anthropic_only_ignores_non_anthropic_override(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
        monkeypatch.setenv("REFCHECK_JUDGE_MODEL", "gpt-6.1-sol,claude-opus-5-5")
        assert [s.id for s in role_candidates("judge")] == ["claude-opus-5-5"]

    def test_invalid_profile_falls_back_to_standard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "paranoid")
        assert privacy_profile() == "standard"

    def test_standard_judge_and_confirm_are_different_families(self) -> None:
        assert not same_family(resolve_role("verifier"), resolve_role("confirm"))
        assert not same_family(resolve_role("judge"), resolve_role("confirm"))
        assert not same_family(resolve_role("judge"), None)
