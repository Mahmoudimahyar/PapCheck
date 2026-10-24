"""Tests for concurrent claim verification engine."""

import asyncio

import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services.progress import ProgressSnapshot
from refcheck.stages.verify_claims.concurrent import (
    verify_claims_concurrent,
)


def _make_claim(claim_id: int) -> Claim:
    return Claim(
        id=claim_id,
        manuscript_text=f"Claim text {claim_id}",
        extracted_claim=f"Claim {claim_id}",
        reference_ids=[claim_id],
    )


def _make_ref(ref_id: int) -> Reference:
    return Reference(
        id=ref_id,
        raw_text=f"Raw text {ref_id}",
        title=f"Reference title {ref_id}",
        number=ref_id,
    )


def _make_pair(pair_id: int) -> tuple[Claim, Reference]:
    return (_make_claim(pair_id), _make_ref(pair_id))


def _make_result(claim_id: int, ref_id: int, verdict: str = "supported") -> VerificationResult:
    return VerificationResult(
        claim_id=claim_id,
        reference_id=ref_id,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=0.85,
        tier=1,
    )


class TestConcurrentProcessing:
    """Core concurrent processing behaviour."""

    @pytest.mark.asyncio
    async def test_processes_all_pairs(self) -> None:
        call_count = 0

        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(20)]
        results = await verify_claims_concurrent(
            pairs=pairs, verify_fn=mock_verify, max_concurrent=5,
        )
        assert len(results) == 20
        assert call_count == 20

    @pytest.mark.asyncio
    async def test_empty_pairs_returns_empty(self) -> None:
        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            raise AssertionError("Should not be called")

        results = await verify_claims_concurrent(
            pairs=[], verify_fn=mock_verify,
        )
        assert results == []


class TestSemaphoreLimits:
    """Concurrency respects semaphore limits."""

    @pytest.mark.asyncio
    async def test_respects_semaphore_limit(self) -> None:
        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                peak_concurrent = max(peak_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                current_concurrent -= 1
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(30)]
        await verify_claims_concurrent(
            pairs=pairs, verify_fn=mock_verify, max_concurrent=5,
        )
        assert peak_concurrent <= 5


class TestErrorIsolation:
    """One failure does not crash the batch."""

    @pytest.mark.asyncio
    async def test_single_failure_doesnt_crash_batch(self) -> None:
        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            if claim.id == 5:
                raise RuntimeError("LLM exploded")
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(10)]
        results = await verify_claims_concurrent(
            pairs=pairs, verify_fn=mock_verify, max_concurrent=5,
        )
        assert len(results) == 10
        assert results[5].verdict == "cannot_verify"
        assert all(
            r.verdict == "supported" for i, r in enumerate(results) if i != 5
        )


class TestProgressCallback:
    """Progress callback is called for each completed pair."""

    @pytest.mark.asyncio
    async def test_callback_called_for_each_pair(self) -> None:
        snapshots: list[ProgressSnapshot] = []

        async def on_progress(snap: ProgressSnapshot) -> None:
            snapshots.append(snap)

        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(10)]
        await verify_claims_concurrent(
            pairs=pairs,
            verify_fn=mock_verify,
            max_concurrent=5,
            progress_callback=on_progress,
        )
        assert len(snapshots) == 10
        # Last snapshot should show 100%
        assert snapshots[-1].current == 10
        assert snapshots[-1].percent == 100.0


class TestOrderPreservation:
    """Results must be in the same order as input pairs."""

    @pytest.mark.asyncio
    async def test_preserves_order(self) -> None:
        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            # Reverse timing to verify order is maintained
            await asyncio.sleep(0.01 * (10 - claim.id))
            return _make_result(claim.id, ref.id, verdict="supported")

        pairs = [_make_pair(i) for i in range(10)]
        results = await verify_claims_concurrent(
            pairs=pairs, verify_fn=mock_verify, max_concurrent=10,
        )
        for i, r in enumerate(results):
            assert r.claim_id == i
            assert r.reference_id == i
