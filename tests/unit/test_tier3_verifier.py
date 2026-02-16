"""Tests for Tier 3 multi-model voting (V2)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from refcheck.llm.client import LLMResponseInvalidError
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.tier3_verifier import verify_tier3

FIXTURES = Path(__file__).parent.parent / "fixtures" / "llm_responses" / "verification"


def _load(name: str) -> VerificationResult:
    data = json.loads((FIXTURES / name).read_text())
    return VerificationResult.model_validate(data)


def _claim() -> Claim:
    return Claim(
        id=1, extracted_claim="Drug X reduced mortality by 30%",
        reference_ids=[1], claim_type="factual", priority="high",
    )


def _ref() -> Reference:
    return Reference(id=1, title="Drug X Study", authors=["Smith J"])


def _tier2(needs_review: bool = True) -> VerificationResult:
    return VerificationResult(
        claim_id=1, reference_id=1, verdict="not_supported",
        confidence=0.7, tier=2, needs_user_review=needs_review,
        reasoning="Tier 2 disagreed",
    )


class TestTier3Verifier:
    @pytest.mark.asyncio
    async def test_both_models_agree(self) -> None:
        """Both models agree → verdict accepted, tier=3, higher confidence."""
        secondary = VerificationResult(
            claim_id=1, reference_id=1, verdict="not_supported",
            confidence=0.75, evidence_quotes=["no evidence found"],
            reasoning="Secondary model agrees",
        )

        async def mock_llm(**kw: object) -> VerificationResult:
            return secondary

        source = ["no evidence found in this section"]
        with patch(
            "refcheck.stages.verify_claims.tier3_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier3(
                _claim(), _ref(), source, _tier2(),
            )

        assert result.verdict == "not_supported"
        assert result.tier == 3
        assert result.needs_user_review is False

    @pytest.mark.asyncio
    async def test_models_disagree(self) -> None:
        """Models disagree → needs_user_review, both reasonings in output."""
        secondary = VerificationResult(
            claim_id=1, reference_id=1, verdict="supported",
            confidence=0.8,
            evidence_quotes=["Drug X reduced mortality by 30%"],
            reasoning="Secondary model found support",
        )

        async def mock_llm(**kw: object) -> VerificationResult:
            return secondary

        source = ["Drug X reduced mortality by 30%"]
        with patch(
            "refcheck.stages.verify_claims.tier3_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier3(
                _claim(), _ref(), source, _tier2(),
            )

        assert result.needs_user_review is True
        assert result.tier == 3
        assert "Secondary" in result.reasoning

    @pytest.mark.asyncio
    async def test_secondary_fails_graceful_fallback(self) -> None:
        """Secondary model call fails → falls back to Tier 2 result."""

        async def mock_llm(**kw: object) -> VerificationResult:
            raise LLMResponseInvalidError("secondary broken")

        with patch(
            "refcheck.stages.verify_claims.tier3_verifier.call_llm",
            side_effect=mock_llm,
        ):
            result = await verify_tier3(
                _claim(), _ref(), ["source text"], _tier2(),
            )

        # Falls back to tier2 result with needs_user_review=True
        assert result.needs_user_review is True
        assert result.tier == 2
        assert result.verdict == "not_supported"

    def test_tier3_model_availability(self) -> None:
        """V4: Tier 3 uses Anthropic (not OpenAI) via model registry."""
        from refcheck.llm.model_registry import DEFAULT_MODELS

        tier3_models = [m for m in DEFAULT_MODELS if m.tier == 3]
        assert len(tier3_models) == 1
        assert tier3_models[0].provider == "anthropic"
