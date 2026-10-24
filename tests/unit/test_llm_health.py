"""Preflight: probes per role, fallback, caching, failure reporting."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from refcheck.llm import keys
from refcheck.llm.decision_models import DecisionAnswer, DecisionResult
from refcheck.llm.errors import LLMCallError, LLMError
from refcheck.llm.health import (
    PreflightError,
    PreflightReply,
    failed_roles,
    preflight,
    probe_model,
    require_roles,
)
from refcheck.llm.model_registry import REGISTRY
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.roles import resolve_role, unavailable_models
from tests.unit.llm_fakes import chat_response, isolated_llm_env

_PROBE = "refcheck.llm.health.probe_model"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def _failing(bad: dict[str, LLMCallError]) -> AsyncMock:
    async def probe(spec: ModelSpec, role: str, tracker: object = None,
                    timeout: float = 45.0) -> None:
        if spec.id in bad:
            raise bad[spec.id]

    return AsyncMock(side_effect=probe)


class TestPreflight:
    async def test_all_roles_ok(self) -> None:
        with patch(_PROBE, _failing({})):
            statuses = await preflight()
        assert set(statuses) == {"screen", "verifier", "judge", "confirm", "adjudicator", "utility",
                                 "embedding"}
        assert all(s.available and s.probe_ok for s in statuses.values())
        assert statuses["judge"].model_id == "claude-sonnet-5-5"
        assert failed_roles(statuses) == []

    async def test_hard_failure_falls_back_and_marks_unavailable(self) -> None:
        bad = {"claude-sonnet-5-5": LLMCallError("billing", "billing", "claude-sonnet-5-5")}
        with patch(_PROBE, _failing(bad)):
            statuses = await preflight(["judge"])
        judge = statuses["judge"]
        assert judge.model_id == "gpt-6.1-sol" and judge.fallback_index == 1
        assert judge.tried == ["claude-sonnet-5-5"] and "billing" in (judge.reason or "")
        assert "claude-sonnet-5-5" in unavailable_models()

    async def test_soft_failure_benches_model_until_next_probe(self) -> None:
        bad = {"gpt-6-luna": LLMCallError("overloaded", "transient", "gpt-6-luna")}
        with patch(_PROBE, _failing(bad)):
            statuses = await preflight(["confirm"])
        assert statuses["confirm"].model_id == "gpt-6.1-sol"
        # Real calls must use the fallback the probe found, not the model that failed it.
        assert "gpt-6-luna" in unavailable_models()
        assert resolve_role("confirm") is not None
        assert resolve_role("confirm").id == "gpt-6.1-sol"  # type: ignore[union-attr]
        with patch(_PROBE, _failing({})):
            statuses = await preflight(["confirm"], force=True)
        assert statuses["confirm"].model_id == "gpt-6-luna"  # re-probed and recovered
        assert "gpt-6-luna" not in unavailable_models()

    async def test_soft_mark_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_PREFLIGHT_TTL_SECONDS", "0")
        bad = {"gpt-6-luna": LLMCallError("bad param", "bad_request", "gpt-6-luna")}
        with patch(_PROBE, _failing(bad)):
            statuses = await preflight(["confirm"])
        assert statuses["confirm"].tried == ["gpt-6-luna"]
        assert "gpt-6-luna" not in unavailable_models()

    async def test_role_with_no_working_model(self) -> None:
        bad = {m: LLMCallError("gone", "not_found", m)
               for m in ("text-embedding-3-small", "text-embedding-3-large")}
        with patch(_PROBE, _failing(bad)):
            statuses = await preflight(["embedding", "verifier"])
        emb = statuses["embedding"]
        assert not emb.available and emb.probe_ok is False
        assert emb.tried == ["text-embedding-3-small", "text-embedding-3-large"]
        assert failed_roles(statuses) == ["embedding"]

    async def test_results_cached_until_forced(self) -> None:
        probe = _failing({})
        with patch(_PROBE, probe):
            await preflight(["utility"])
            await preflight(["utility"])
            assert probe.await_count == 1
            await preflight(["utility"], force=True)
            assert probe.await_count == 2

    async def test_disabled_screen_is_not_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_SCREEN_ENABLED", "false")
        with patch(_PROBE, _failing({})):
            statuses = await preflight(["screen", "verifier"])
        assert not statuses["screen"].available and statuses["screen"].probed is False
        assert failed_roles(statuses) == []

    async def test_anthropic_only_disabled_roles_are_not_failures(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
        with patch(_PROBE, _failing({})):
            statuses = await preflight(["screen", "embedding", "judge", "confirm"])
        assert statuses["judge"].model_id == "claude-sonnet-5-5"
        assert statuses["confirm"].model_id == "claude-sonnet-5-5"
        assert not statuses["embedding"].available
        assert failed_roles(statuses) == []

    async def test_require_roles_raises_only_for_the_verifier(self) -> None:
        bad = {m: LLMCallError("gone", "auth", m) for m in ("claude-haiku-5-5", "gpt-6-luna")}
        with patch(_PROBE, _failing(bad)), pytest.raises(PreflightError) as info:
            await require_roles(["verifier", "judge"])
        assert "verifier" in str(info.value) and "judge" not in str(info.value).split("—")[0]


class TestLiveCheckRevivesExhaustedKeys:
    async def test_credits_added_since(self) -> None:
        keys.rotate("openai", reason="billing")  # marked exhausted (persisted)
        with patch(_PROBE, _failing({})):
            assert (await preflight(["confirm"]))["confirm"].model_id == "claude-sonnet-5-5"
            statuses = await preflight(["confirm"], retry_exhausted=True)
        assert statuses["confirm"].model_id == "gpt-6-luna" and not statuses["confirm"].degraded
        assert keys.key_problem("openai") is None

    async def test_healthy_cache_is_kept(self) -> None:
        probe = _failing({})
        with patch(_PROBE, probe):
            await preflight(["utility"])
            await preflight(["utility"], retry_exhausted=True)
        assert probe.await_count == 1


class TestProbeModel:
    async def test_chat_probe_uses_preflight_template(self) -> None:
        mock = MagicMock(return_value=chat_response('{"ok": true}'))
        with patch("refcheck.llm.completion._sync_completion", mock):
            await probe_model(REGISTRY["claude-sonnet-5-5"], "judge")
        kwargs = mock.call_args.args[0]
        assert kwargs["model"] == "anthropic/claude-sonnet-5-5"
        # The probe uses the role's effort (judge: low), not the registry default (medium).
        assert REGISTRY["claude-sonnet-5-5"].reasoning_effort == "medium"
        assert kwargs["reasoning_effort"] == "low"
        assert "connectivity check" in str(kwargs["messages"])

    async def test_chat_probe_ok_false_fails(self) -> None:
        with patch("refcheck.llm.completion._sync_completion",
                   MagicMock(return_value=chat_response('{"ok": false}'))), \
                pytest.raises(LLMError):
            await probe_model(REGISTRY["gpt-6-luna"], "utility")

    async def test_decision_probe_refusal_fails(self) -> None:
        refused = DecisionResult(model="gpt-6-luna-decisions", answers={
            "probe": DecisionAnswer(name="probe", type="refusal", refused=True)})
        with patch("refcheck.llm.probe.decide", AsyncMock(return_value=refused)), \
                pytest.raises(LLMError):
            await probe_model(REGISTRY["gpt-6-luna-decisions"], "screen")

    async def test_embedding_probe(self) -> None:
        embed = AsyncMock(return_value=[[0.1, 0.2]])
        with patch("refcheck.llm.probe.embed", embed):
            await probe_model(REGISTRY["text-embedding-3-small"], "embedding")
        assert embed.await_args is not None
        assert embed.await_args.kwargs["use_cache"] is False

    def test_reply_model(self) -> None:
        assert PreflightReply(ok=True).ok
