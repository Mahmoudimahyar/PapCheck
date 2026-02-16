"""Tests for LLM-based claim verification (V4 multi-model voting)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.verifier import verify_claims

FIXTURES = Path(__file__).parent.parent / "fixtures" / "llm_responses" / "verification"


def _mock_llm_response(
    verdict: str = "supported",
    confidence: float = 0.90,
    reasoning: str = "Evidence supports this",
    evidence_quotes: list[str] | None = None,
) -> SimpleNamespace:
    """Create a mock litellm response matching the verification schema."""
    content = json.dumps({
        "claim_id": 0,
        "reference_id": 0,
        "verdict": verdict,
        "confidence": confidence,
        "evidence_quotes": evidence_quotes or ["Drug X was associated with a 30% reduction"],
        "reasoning": reasoning,
        "tier": 1,
        "source_coverage": "relevant_sections",
        "needs_user_review": False,
    })
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=200, completion_tokens=100)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_claim(
    claim_id: int = 1,
    ref_ids: list[int] | None = None,
    claim_type: str = "factual",
    text: str = "Drug X reduced mortality by 30%",
) -> Claim:
    return Claim(
        id=claim_id,
        extracted_claim=text,
        reference_ids=ref_ids or [1],
        claim_type=claim_type,  # type: ignore[arg-type]
    )


def _make_ref(
    ref_id: int = 1,
    pdf_path: Path | None = None,
    title: str = "Drug X Study",
) -> Reference:
    return Reference(
        id=ref_id,
        title=title,
        authors=["Smith J", "Doe A"],
        source_status="found",
        pdf_path=pdf_path,
    )


def _create_source_pdf(tmp_path: Path, content: str) -> Path:
    """Create a PDF with known content for testing."""
    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), content, fontsize=10)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestVerifyClaims:
    """V4: Multi-model verification tests."""

    @pytest.mark.asyncio
    async def test_v01_clearly_supported(self, tmp_path: Path) -> None:
        """V-01: Clearly supported claim returns supported verdict."""
        source_text = "Drug X was associated with a 30% reduction in all-cause mortality"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            return_value=_mock_llm_response("supported", 0.90),
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "supported"
        assert results[0].confidence >= 0.85

    @pytest.mark.asyncio
    async def test_v02_clearly_contradicted(self, tmp_path: Path) -> None:
        """V-02: Contradicted claim triggers escalation due to safety rule."""
        source_text = "Drug X showed a non-significant 12% reduction (p=0.08)"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)
        call_count = 0

        def mock_completion(
            model_id: str,
            messages: list[dict[str, str]],
            timeout: int,
            max_tokens: int,
        ) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            # Tier 0: one says contradicted -> escalate
            # All tiers eventually say contradicted
            return _mock_llm_response("contradicted", 0.88)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            side_effect=mock_completion,
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "contradicted"

    @pytest.mark.asyncio
    async def test_v04_unrelated_paper(self, tmp_path: Path) -> None:
        """V-04: Unrelated paper cited returns not_supported."""
        source_text = "This paper discusses quantum computing algorithms"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            return_value=_mock_llm_response("not_supported", 0.85),
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "not_supported"

    @pytest.mark.asyncio
    async def test_v09_background_claim_light_check(self, tmp_path: Path) -> None:
        """V-09: Background claim with partial_support gets upgraded."""
        source_text = "Osteoarthritis remains a major health burden worldwide"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim(claim_type="background", text="OA is a common condition")
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            return_value=_mock_llm_response("partially_supported", 0.55),
        ):
            results = await verify_claims([claim], [ref])

        # Background claim with confidence >= 0.5 should be upgraded
        assert results[0].verdict == "supported"

    @pytest.mark.asyncio
    async def test_v10_no_pdf_cannot_verify(self) -> None:
        """V-10: Reference with no PDF returns cannot_verify."""
        claim = _make_claim()
        ref = _make_ref(pdf_path=None)

        results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "cannot_verify"
        assert results[0].source_coverage == "no_source"

    @pytest.mark.asyncio
    async def test_multiple_reference_ids(self, tmp_path: Path) -> None:
        """Multiple reference_ids produce separate verifications."""
        source_text = "Some relevant content about drug efficacy"
        pdf1 = _create_source_pdf(tmp_path, source_text)
        pdf2_path = tmp_path / "source2.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), source_text, fontsize=10)
        doc.save(str(pdf2_path))
        doc.close()

        claim = _make_claim(ref_ids=[1, 2])
        ref1 = _make_ref(ref_id=1, pdf_path=pdf1)
        ref2 = _make_ref(ref_id=2, pdf_path=pdf2_path, title="Another Study")

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            return_value=_mock_llm_response("supported", 0.90),
        ):
            results = await verify_claims([claim], [ref1, ref2])

        assert len(results) == 2
        ref_ids = {r.reference_id for r in results}
        assert ref_ids == {1, 2}

    @pytest.mark.asyncio
    async def test_voting_fields_populated(self, tmp_path: Path) -> None:
        """V4: Voting fields are populated on results."""
        source_text = "Drug X was tested in clinical trials"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            return_value=_mock_llm_response("supported", 0.85),
        ):
            results = await verify_claims([claim], [ref])

        result = results[0]
        assert result.consensus_type != ""
        assert result.total_models_consulted > 0
        assert result.agreement_ratio > 0

    @pytest.mark.asyncio
    async def test_llm_errors_handled_gracefully(self, tmp_path: Path) -> None:
        """All models failing produces cannot_verify, not a crash."""
        source_text = "Some source text"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            side_effect=RuntimeError("API down"),
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "cannot_verify"
