"""Integration tests for concurrent verification pipeline."""

import asyncio
import time

import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services.progress import ProgressSnapshot
from refcheck.stages.verify_claims.concurrent import verify_claims_concurrent


def _make_claim(cid: int) -> Claim:
    return Claim(
        id=cid,
        manuscript_text=f"Test claim {cid}",
        extracted_claim=f"Extracted claim {cid}",
        reference_ids=[cid],
    )


def _make_ref(rid: int) -> Reference:
    return Reference(
        id=rid,
        raw_text=f"Raw text {rid}",
        title=f"Reference {rid}",
        number=rid,
    )


def _make_pair(pid: int) -> tuple[Claim, Reference]:
    return (_make_claim(pid), _make_ref(pid))


def _make_result(cid: int, rid: int) -> VerificationResult:
    return VerificationResult(
        claim_id=cid, reference_id=rid,
        verdict="supported", confidence=0.85, tier=1,
    )


class TestConcurrentIsFaster:
    """Concurrent must be measurably faster than sequential."""

    @pytest.mark.asyncio
    async def test_concurrent_faster_than_sequential(self) -> None:
        """With 20 items and 50ms per call, concurrent should be >=3x faster."""
        delay = 0.05

        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            await asyncio.sleep(delay)
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(20)]

        # Sequential timing
        seq_start = time.monotonic()
        for claim, ref in pairs:
            await mock_verify(claim, ref)
        sequential_time = time.monotonic() - seq_start

        # Concurrent timing
        conc_start = time.monotonic()
        await verify_claims_concurrent(
            pairs=pairs, verify_fn=mock_verify, max_concurrent=10,
        )
        concurrent_time = time.monotonic() - conc_start

        # Should be at least 3x faster
        assert concurrent_time < sequential_time / 3, (
            f"Concurrent ({concurrent_time:.2f}s) not 3x faster "
            f"than sequential ({sequential_time:.2f}s)"
        )


class TestFullBatchWithProgress:
    """End-to-end: concurrent verification with progress tracking."""

    @pytest.mark.asyncio
    async def test_all_results_with_progress(self) -> None:
        snapshots: list[ProgressSnapshot] = []

        async def on_progress(snap: ProgressSnapshot) -> None:
            snapshots.append(snap)

        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            await asyncio.sleep(0.01)
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(50)]
        results = await verify_claims_concurrent(
            pairs=pairs,
            verify_fn=mock_verify,
            max_concurrent=10,
            progress_callback=on_progress,
        )

        assert len(results) == 50
        assert len(snapshots) == 50
        # Verify snapshots are monotonically increasing
        for i in range(1, len(snapshots)):
            assert snapshots[i].current >= snapshots[i - 1].current
        # Last snapshot should be 100%
        assert snapshots[-1].percent == 100.0
        assert snapshots[-1].estimated_remaining_seconds == 0.0


class TestMixedSuccessAndFailure:
    """Batch with mix of successes, failures, and timeouts."""

    @pytest.mark.asyncio
    async def test_mixed_batch(self) -> None:
        async def mock_verify(claim: Claim, ref: Reference) -> VerificationResult:
            if claim.id % 10 == 0:
                raise RuntimeError("LLM error")
            if claim.id % 15 == 0:
                await asyncio.sleep(100)
            await asyncio.sleep(0.01)
            return _make_result(claim.id, ref.id)

        pairs = [_make_pair(i) for i in range(30)]
        results = await verify_claims_concurrent(
            pairs=pairs,
            verify_fn=mock_verify,
            max_concurrent=10,
            timeout_seconds=1,
        )

        assert len(results) == 30
        error_indices = [i for i in range(30) if i % 10 == 0]
        for i in error_indices:
            assert results[i].verdict == "cannot_verify"
        # Normal results should be supported
        for i in range(30):
            if i % 10 != 0 and i % 15 != 0:
                assert results[i].verdict == "supported"
