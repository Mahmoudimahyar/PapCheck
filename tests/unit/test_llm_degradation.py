"""V5.8 degraded mode: OpenAI without credits must not stop a run (fakes only)."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm import degradation, keys
from refcheck.llm.client import call_llm_raw
from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.decision_models import DecisionError, DecisionQuestion
from refcheck.llm.decisions import decide
from refcheck.llm.degraded_guard import degraded_cap_usd
from refcheck.llm.embeddings import EmbeddingError, embed
from refcheck.llm.errors import LLMCallError
from refcheck.llm.health import failed_roles, hard_failed_roles, preflight, require_roles
from refcheck.llm.model_registry import REGISTRY
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.roles import resolve_role, role_status
from refcheck.llm.usage import TokenUsage
from tests.unit.llm_fakes import chat_response, isolated_llm_env

_PROBE = "refcheck.llm.health.probe_model"
_OPENAI = ("gpt-6-luna-decisions", "gpt-6-luna", "gpt-6.1-sol", "text-embedding-3-small",
           "text-embedding-3-large")


class Out(BaseModel):
    summary: str
    confidence: float


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def _probe(kind: str) -> AsyncMock:
    async def probe(spec: ModelSpec, role: str, tracker: object = None,
                    timeout: float = 45.0) -> None:
        if spec.id in _OPENAI:
            raise LLMCallError("insufficient_quota", kind, spec.id)  # type: ignore[arg-type]

    return AsyncMock(side_effect=probe)


class TestPreflightDegrades:
    async def test_openai_out_of_credits(self) -> None:
        tracker = CostTracker()
        with patch(_PROBE, _probe("billing")):
            statuses = await require_roles(["verifier", "judge", "confirm", "screen"],
                                           cost_tracker=tracker)
        confirm = statuses["confirm"]
        assert confirm.model_id == "claude-sonnet-5-5" and confirm.reasoning_effort == "low"
        assert confirm.degraded and confirm.cause == "billing" and confirm.persistent
        assert statuses["verifier"].model_id == "claude-haiku-5-5"
        assert not statuses["verifier"].degraded and not statuses["judge"].degraded
        assert failed_roles(statuses) == ["screen"] and hard_failed_roles(statuses) == []
        assert statuses["screen"].degraded_mode == "skipped"
        assert set(tracker.degradations) == {"confirm", "screen"}
        summary = tracker.summary().degraded
        assert "Add credits to the OpenAI account" in summary["confirm"]
        assert set(degradation.current()) == {"confirm", "screen"}

    async def test_cached_preflight_still_records_on_a_new_run(self) -> None:
        with patch(_PROBE, _probe("billing")):
            await preflight(["confirm"], cost_tracker=CostTracker())
            second = CostTracker()
            await preflight(["confirm"], cost_tracker=second)
        assert "confirm" in second.degradations

    async def test_transient_errors_are_not_persistent(self) -> None:
        with patch(_PROBE, _probe("transient")):
            statuses = await preflight(["confirm"])
        confirm = statuses["confirm"]
        assert confirm.model_id == "claude-sonnet-5-5"
        assert confirm.cause == "network" and not confirm.persistent and confirm.action is None

    async def test_recovery_clears_the_registry(self) -> None:
        with patch(_PROBE, _probe("transient")):
            await preflight(["confirm"])
        with patch(_PROBE, AsyncMock(return_value=None)):
            statuses = await preflight(["confirm"], force=True)
        assert statuses["confirm"].model_id == "gpt-6-luna" and not statuses["confirm"].degraded
        assert "confirm" not in degradation.current()

    async def test_dead_verifier_still_raises(self) -> None:
        from refcheck.llm.health import PreflightError

        bad = AsyncMock(side_effect=LLMCallError("gone", "auth", "x"))
        with patch(_PROBE, bad), pytest.raises(PreflightError):
            await require_roles(["verifier"])


class TestResolution:
    def test_normal_path_unchanged(self) -> None:
        status = role_status()["confirm"]
        assert status.model_id == "gpt-6-luna" and not status.degraded

    def test_confirm_fallback_is_never_the_verifier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_VERIFIER_MODEL", "claude-sonnet-5-5")
        keys.rotate("openai", reason="billing")
        spec = resolve_role("confirm")
        assert spec is not None and spec.id == "claude-haiku-5-5"

    def test_switch_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_DEGRADED_FALLBACKS", "off")
        keys.rotate("openai", reason="billing")
        assert resolve_role("confirm") is None

    def test_key_problem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert keys.key_problem("openai") is None
        keys.rotate("openai", reason="billing")
        assert keys.key_problem("openai") == "billing"
        assert keys.key_problem("gemini") == "no_key"


class TestCallsInDegradedMode:
    async def test_confirm_call_falls_back_and_is_recorded(self) -> None:
        keys.rotate("openai", reason="billing")
        tracker = CostTracker()
        mock = MagicMock(return_value=chat_response('{"summary": "s", "confidence": 0.5}'))
        with patch("refcheck.llm.completion._sync_completion", mock):
            result = await call_llm_raw("test_prompt", {"topic": "x"}, Out, role="confirm",
                                        cost_tracker=tracker, use_cache=False)
        assert result.model_id == "claude-sonnet-5-5" and result.reasoning_effort == "low"
        assert tracker.degradations["confirm"].cause == "billing"

    async def test_degraded_spend_is_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_DEGRADED_MAX_USD", "0.01")
        keys.rotate("openai", reason="billing")
        tracker = CostTracker()
        tracker.record_usage(REGISTRY["claude-sonnet-5-5"],
                             TokenUsage(input_tokens=10_000, output_tokens=0), "t", "confirm")
        mock = MagicMock(return_value=chat_response('{"summary": "s", "confidence": 0.5}'))
        with patch("refcheck.llm.completion._sync_completion", mock), \
                pytest.raises(CostLimitExceededError):
            await call_llm_raw("test_prompt", {"topic": "x"}, Out, role="confirm",
                               cost_tracker=tracker, use_cache=False)
        mock.assert_not_called()

    def test_default_cap(self) -> None:
        assert degraded_cap_usd(CostTracker(max_cost=50)) == 2.0
        assert degraded_cap_usd(CostTracker(max_cost=1)) == 0.25

    async def test_embedding_outage_means_bm25_only(self) -> None:
        keys.rotate("openai", reason="billing")
        tracker = CostTracker()
        with pytest.raises(EmbeddingError):
            await embed(["a"], cost_tracker=tracker)
        item = tracker.degradations["embedding"]
        assert item.mode == "bm25_only" and item.cause == "billing" and item.persistent

    async def test_screen_outage_is_skipped(self) -> None:
        keys.rotate("openai", reason="billing")
        tracker = CostTracker()
        with pytest.raises(DecisionError):
            await decide("text", [DecisionQuestion(name="q", instructions="Is it?")],
                         cost_tracker=tracker)
        assert tracker.degradations["screen"].mode == "skipped"


class TestDescribeAndPersist:
    def test_quota_vs_network(self) -> None:
        quota = degradation.build("confirm", "fallback", kind="billing", provider="openai",
                                  fallback_model="claude-sonnet-5-5")
        net = degradation.build("embedding", "bm25_only", kind="timeout", provider="openai")
        assert quota.persistent and "Add credits" in degradation.describe(quota)
        assert not net.persistent and net.action is None
        assert "BM25" in degradation.describe(net)
        assert degradation.cause_of(None, "insufficient_quota for this key") == "billing"

    def test_save_and_load(self, tmp_path: Path) -> None:
        item = degradation.build("screen", "skipped", kind="billing", provider="openai")
        path = tmp_path / "llm_degradations.json"
        degradation.save(path, {"screen": item})
        assert degradation.load(path)["screen"].cause == "billing"
        degradation.save(path, {})
        assert not path.exists() and degradation.load(path) == {}
