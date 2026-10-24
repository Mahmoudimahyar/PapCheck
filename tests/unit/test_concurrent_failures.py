"""Concurrent verification: per-pair timeout, defaults and failure results."""

import asyncio

import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.concurrent import verify_claims_concurrent
from tests.unit.test_concurrent_verification import _make_pair, _make_result


class TestTimeout:
    """Claims exceeding timeout get cannot_verify."""

    @pytest.mark.asyncio
    async def test_timeout_yields_cannot_verify(self) -> None:
        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            if claim.id == 0:
                await asyncio.sleep(100)
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(3)]
        results = await verify_claims_concurrent(
            pairs=pairs,
            verify_fn=mock_verify,
            max_concurrent=3,
            timeout_seconds=1,
        )
        assert results[0].verdict == "cannot_verify"
        assert "timed out" in results[0].reasoning.lower()


class TestV5Defaults:
    """V5: default concurrency/budget and coverage-preserving failure results."""

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from refcheck.stages.verify_claims.concurrent import get_claim_budget, get_max_concurrent

        monkeypatch.delenv("REFCHECK_MAX_CONCURRENT_CLAIMS", raising=False)
        monkeypatch.delenv("REFCHECK_CLAIM_TIMEOUT_SECONDS", raising=False)
        assert get_max_concurrent() == 12 and get_claim_budget() == 180
        monkeypatch.setenv("REFCHECK_MAX_CONCURRENT_CLAIMS", "oops")
        assert get_max_concurrent() == 12

    @pytest.mark.asyncio
    async def test_on_failure_builds_the_error_result(self) -> None:
        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            raise RuntimeError("bug")

        def on_failure(claim: Claim, ref: Reference, reason: str) -> VerificationResult:
            return VerificationResult(
                claim_id=claim.id, reference_id=ref.id, reasoning=reason,
                source_coverage="full_text", cannot_verify_reason="llm_error",
            )

        results = await verify_claims_concurrent(
            pairs=[_make_pair(1)], verify_fn=mock_verify, on_failure=on_failure,
        )
        assert results[0].source_coverage == "full_text"
        assert "RuntimeError" in results[0].reasoning
