"""Tests for Tier 2 dual-strategy verification (V2)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from refcheck.llm.client import LLMResponseInvalidError
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.tier2_verifier import verify_tier2

FIXTURES = Path(__file__).parent.parent / "fixtures" / "llm_responses" / "verification"


def _load(name: str) -> VerificationResult:
    data = json.loads((FIXTURES / name).read_text())
    return VerificationResult.model_validate(data)


def _claim(claim_type: str = "factual") -> Claim:
    return Claim(
        id=1,
        extracted_claim="Drug X reduced mortality by 30%",
        reference_ids=[1],
        claim_type=claim_type,  # type: ignore[arg-type]
        priority="high",
    )


def _ref() -> Reference:
    return Reference(id=1, title="Drug X Study", authors=["Smith J"])


def _tier1(confidence: float = 0.65) -> VerificationResult:
    return VerificationResult(
        claim_id=1, reference_id=1, verdict="supported",
        confidence=confidence, tier=1,
    )


class TestTier2Verifier:
    @pytest.mark.asyncio
    async def test_both_agree_supported(self) -> None:
        """Both strategies agree 'supported' → verdict supported, tier=2."""
        strict = _load("strict_supported.json")
        generous = _load("generous_supported.json")

        call_count = 0

        async def mock_llm(template: str, **kw: object) -> VerificationResult:
            nonlocal call_count
            call_count += 1
            if "strict" in template:
                return strict
            return generous

        # Source text must contain the evidence quotes from fixtures
        source = ["Drug X was associated with a 30% reduction in all-cause mortality"]

        with patch(
            "refcheck.stages.verify_claims.tier2_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier2(
                _claim(), _ref(), source, _tier1(),
            )

        assert result.verdict == "supported"
        assert result.tier == 2
        assert result.confidence > 0.85
        assert result.needs_user_review is False
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_both_agree_contradicted(self) -> None:
        """Both strategies agree 'contradicted' → verdict contradicted."""
        strict = _load("strict_not_supported.json").model_copy(
            update={"verdict": "contradicted", "confidence": 0.85}
        )
        generous = _load("generous_contradicted.json")

        async def mock_llm(template: str, **kw: object) -> VerificationResult:
            if "strict" in template:
                return strict
            return generous

        # Source containing evidence quotes from both fixtures
        source = [
            "The study focused on younger patients aged 18-40",
            "Drug X showed no significant effect on mortality (p=0.45)",
        ]
        with patch(
            "refcheck.stages.verify_claims.tier2_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier2(
                _claim(), _ref(), source, _tier1(),
            )

        assert result.verdict == "contradicted"
        assert result.tier == 2

    @pytest.mark.asyncio
    async def test_disagree_flags_review(self) -> None:
        """Strict=not_supported, generous=supported → needs review."""
        strict = _load("strict_not_supported.json")
        generous = _load("generous_supported.json")

        async def mock_llm(template: str, **kw: object) -> VerificationResult:
            if "strict" in template:
                return strict
            return generous

        source = [
            "The study focused on younger patients aged 18-40",
            "Drug X was associated with a 30% reduction in all-cause mortality",
        ]
        with patch(
            "refcheck.stages.verify_claims.tier2_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier2(
                _claim(), _ref(), source, _tier1(),
            )

        assert result.needs_user_review is True
        assert result.tier == 2
        # Factual claim → conservative (strict) verdict
        assert result.verdict == "not_supported"

    @pytest.mark.asyncio
    async def test_disagree_partial_vs_supported(self) -> None:
        """Strict=partial, generous=supported → partial, tier=2."""
        strict = _load("strict_supported.json").model_copy(
            update={"verdict": "partially_supported", "confidence": 0.7}
        )
        generous = _load("generous_supported.json")

        async def mock_llm(template: str, **kw: object) -> VerificationResult:
            if "strict" in template:
                return strict
            return generous

        source = ["Drug X was associated with a 30% reduction in all-cause mortality"]
        with patch(
            "refcheck.stages.verify_claims.tier2_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier2(
                _claim(), _ref(), source, _tier1(),
            )

        assert result.verdict == "partially_supported"
        assert result.tier == 2

    @pytest.mark.asyncio
    async def test_one_strategy_fails_uses_other(self) -> None:
        """LLM error on one strategy → falls back to the other."""

        async def mock_llm(template: str, **kw: object) -> VerificationResult:
            if "strict" in template:
                raise LLMResponseInvalidError("broken")
            return _load("generous_supported.json")

        source = ["Drug X was associated with a 30% reduction in all-cause mortality"]
        with patch(
            "refcheck.stages.verify_claims.tier2_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier2(
                _claim(), _ref(), source, _tier1(),
            )

        assert result.verdict == "supported"
        assert result.tier == 2
