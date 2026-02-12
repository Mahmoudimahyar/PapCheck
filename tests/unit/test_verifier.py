"""Tests for LLM-based claim verification (V1)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.verifier import verify_claims

FIXTURES = Path(__file__).parent.parent / "fixtures" / "llm_responses" / "verification"


def _load_fixture(name: str) -> VerificationResult:
    data = json.loads((FIXTURES / name).read_text())
    return VerificationResult.model_validate(data)


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
    @pytest.mark.asyncio
    async def test_v01_clearly_supported(self, tmp_path: Path) -> None:
        """V-01: Clearly supported claim returns supported verdict."""
        fixture = _load_fixture("supported.json")
        source_text = "Drug X was associated with a 30% reduction in all-cause mortality"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "supported"
        assert results[0].confidence >= 0.85

    @pytest.mark.asyncio
    async def test_v02_clearly_contradicted(self, tmp_path: Path) -> None:
        """V-02: Clearly contradicted claim returns contradicted verdict."""
        fixture = _load_fixture("contradicted.json")
        source_text = "Drug X showed a non-significant 12% reduction (p=0.08)"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "contradicted"
        assert results[0].confidence >= 0.80

    @pytest.mark.asyncio
    async def test_v03_partially_supported(self, tmp_path: Path) -> None:
        """V-03: Partially supported (wrong number) verdict."""
        fixture = _load_fixture("partial.json")
        source_text = "Drug X showed a 25% reduction in mortality"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "partially_supported"

    @pytest.mark.asyncio
    async def test_v04_unrelated_paper(self, tmp_path: Path) -> None:
        """V-04: Unrelated paper cited returns not_supported."""
        fixture = _load_fixture("not_supported.json")
        source_text = "This paper discusses quantum computing algorithms"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "not_supported"

    @pytest.mark.asyncio
    async def test_v05_forced_grounding_quotes_present(self, tmp_path: Path) -> None:
        """V-05: Forced grounding produces evidence quotes."""
        fixture = _load_fixture("supported.json")
        source_text = "Drug X was associated with a 30% reduction in all-cause mortality"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        assert len(results[0].evidence_quotes) > 0

    @pytest.mark.asyncio
    async def test_v09_background_claim_light_check(self, tmp_path: Path) -> None:
        """V-09: Background claim accepted more easily."""
        fixture = _load_fixture("background.json")
        # Override to partially_supported to test the upgrade behavior
        fixture = fixture.model_copy(update={
            "verdict": "partially_supported",
            "confidence": 0.55,
        })
        source_text = "Osteoarthritis remains a major health burden worldwide"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim(claim_type="background", text="OA is a common condition")
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        # Background claim with confidence >= 0.5 should be upgraded to supported
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
    async def test_hallucinated_quote_flags_review(self, tmp_path: Path) -> None:
        """Quote validation catches hallucinated quote."""
        fixture = _load_fixture("supported.json")
        # Source text does NOT contain the quote from the fixture
        source_text = "This paper is about completely different results"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref])

        assert results[0].needs_user_review is True
        # Confidence should be penalized
        assert results[0].confidence < fixture.confidence

    @pytest.mark.asyncio
    async def test_llm_invalid_json_graceful(self, tmp_path: Path) -> None:
        """LLM returning invalid JSON handled gracefully."""
        from refcheck.llm.client import LLMResponseInvalidError

        source_text = "Some source text"
        pdf_path = _create_source_pdf(tmp_path, source_text)

        claim = _make_claim()
        ref = _make_ref(pdf_path=pdf_path)

        with patch(
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            side_effect=LLMResponseInvalidError("bad json"),
        ):
            results = await verify_claims([claim], [ref])

        assert len(results) == 1
        assert results[0].verdict == "cannot_verify"

    @pytest.mark.asyncio
    async def test_multiple_reference_ids(self, tmp_path: Path) -> None:
        """Multiple reference_ids produce separate verifications."""
        fixture = _load_fixture("supported.json")
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
            "refcheck.stages.verify_claims.verifier.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            results = await verify_claims([claim], [ref1, ref2])

        assert len(results) == 2
        ref_ids = {r.reference_id for r in results}
        assert ref_ids == {1, 2}
