"""Stage 5 runner: error handling, circuit breaker, cost summary."""

import sys
import types
from collections.abc import Awaitable, Callable, Iterator
from unittest.mock import MagicMock, patch

import pytest

from refcheck.llm.cost_tracker import CostSummary
from refcheck.models.claim import Claim
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services import verify_runner
from refcheck.services.verify_outcome import (
    VerificationStageError,
    assess_verifications,
    cost_by_role,
    describe_exception,
    format_cost,
)

VerifyFn = Callable[..., Awaitable[list[VerificationResult]]]


def _result(i: int, coverage: str = "full_text", reason: str | None = None) -> VerificationResult:
    return VerificationResult.model_validate({
        "claim_id": i, "reference_id": 1, "source_coverage": coverage,
        "verdict": "cannot_verify" if reason else "supported",
        "cannot_verify_reason": reason,
    })


def _state() -> PipelineState:
    return PipelineState(
        session_id="s1",
        claims=[Claim(id=1, extracted_claim="X works.", reference_ids=[1])],
        references=[Reference(id=1, title="T")],
    )


class _Env:
    def __init__(self) -> None:
        self.events: list[PipelineEvent] = []
        self.persist = MagicMock()
        self.update_stage = MagicMock()
        self.session_error = MagicMock()


@pytest.fixture
def env() -> Iterator[_Env]:
    e = _Env()

    async def _emit(session_id: str, event: PipelineEvent) -> None:
        e.events.append(event)

    with (
        patch.object(verify_runner, "emit_event", _emit),
        patch.object(verify_runner, "persist_verifications", e.persist),
        patch.object(verify_runner, "update_stage", e.update_stage),
        patch.object(verify_runner, "record_session_error", e.session_error),
    ):
        yield e


def _install_verifier(monkeypatch: pytest.MonkeyPatch, fn: VerifyFn) -> None:
    """Stand-in for refcheck.stages.verify_claims (owned by another package)."""
    module = types.ModuleType("refcheck.stages.verify_claims")
    module.verify_claims = fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "refcheck.stages.verify_claims", module)


@pytest.mark.asyncio
async def test_exception_is_stage_error_not_complete(
    env: _Env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(*args: object, **kwargs: object) -> list[VerificationResult]:
        raise RuntimeError("preflight: role 'judge' has no working model")

    _install_verifier(monkeypatch, _boom)
    with pytest.raises(VerificationStageError, match="role 'judge' has no working model"):
        await verify_runner.run_verify("s1", _state())
    last = env.events[-1]
    assert last.stage == 5 and last.status == "error"
    assert "role 'judge' has no working model" in last.message
    assert all(ev.status != "complete" for ev in env.events)
    env.update_stage.assert_not_called()
    env.persist.assert_not_called()


@pytest.mark.asyncio
async def test_circuit_breaker_persists_and_errors(
    env: _Env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [_result(i) for i in range(1, 9)] + [
        _result(9, reason="llm_error"), _result(10, reason="llm_error"),
        _result(11, coverage="no_source", reason="no_pdf_not_found"),
    ]

    async def _verify(*args: object, **kwargs: object) -> list[VerificationResult]:
        return results

    _install_verifier(monkeypatch, _verify)
    state = await verify_runner.run_verify("s1", _state())
    env.persist.assert_called_once_with("s1", results)
    last = env.events[-1]
    assert last.status == "error"
    assert "2 of 10 sourced" in last.message
    assert last.progress is not None and last.progress["llm_errors"] == 2.0
    env.session_error.assert_called_once()
    env.update_stage.assert_called_once_with("s1", 5)
    assert state.verification_results == results


@pytest.mark.asyncio
async def test_success_complete_with_cost(
    env: _Env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _verify(*args: object, **kwargs: object) -> list[VerificationResult]:
        return [_result(1), _result(2)]

    _install_verifier(monkeypatch, _verify)
    await verify_runner.run_verify("s1", _state())
    last = env.events[-1]
    assert last.status == "complete"
    assert last.message.startswith("2 verifications, $")
    assert last.progress is not None and "cost_usd" in last.progress
    env.session_error.assert_not_called()


class TestOutcomeHelpers:
    def test_threshold_is_strictly_above_five_percent(self) -> None:
        ok = [_result(i) for i in range(1, 20)] + [_result(20, reason="llm_error")]
        assert not assess_verifications(ok).breaker_tripped  # exactly 5%
        assert assess_verifications(ok + [_result(21, reason="llm_error")]).breaker_tripped

    def test_no_sourced_pairs(self) -> None:
        out = assess_verifications([_result(1, coverage="no_source", reason="no_pdf_paywalled")])
        assert out.sourced == 0 and not out.breaker_tripped

    def test_short_circuited_sources_do_not_dilute_the_rate(self) -> None:
        # 2 llm_errors among 10 cascade pairs = 20%, even with 40 scanned PDFs alongside.
        cascade = [_result(i) for i in range(1, 9)] + [
            _result(9, reason="llm_error"), _result(10, reason="llm_error")]
        scanned = [_result(100 + i, reason="pdf_scanned") for i in range(40)]
        out = assess_verifications(cascade + scanned)
        assert out.sourced == 10 and out.breaker_tripped

    def test_describe_exception(self) -> None:
        assert describe_exception(ValueError("bad key")) == "ValueError: bad key"
        assert describe_exception(TimeoutError()) == "TimeoutError"

    def test_cost_by_role_and_format(self) -> None:
        summary = CostSummary.model_validate({
            "total_usd": 0.42,
            "by_role": {"judge": 0.36, "verifier": 0.05, "screen": 0.01},
        })
        assert cost_by_role(summary)["judge"] == 0.36
        assert format_cost(summary) == "$0.42 (judge $0.36, verifier $0.05, screen $0.01)"
