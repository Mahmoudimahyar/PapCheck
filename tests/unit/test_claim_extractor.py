"""Tests for claim-citation extraction (V1 + V2 atomic decomposition)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import ManuscriptSection, ParsedManuscript, Reference
from refcheck.stages.extract_claims.claim_parser import (
    AtomicDecompositionResponse,
    ClaimExtractionResponse,
    apply_priority,
    assign_sequential_ids,
    deduplicate_claims,
    filter_invalid_refs,
)
from refcheck.stages.extract_claims.extractor import extract_claims

FIXTURES = Path(__file__).parent.parent / "fixtures" / "llm_responses" / "claim_extraction"


def _load_fixture(name: str) -> ClaimExtractionResponse:
    """Load an LLM response fixture and parse as ClaimExtractionResponse."""
    data = json.loads((FIXTURES / name).read_text())
    return ClaimExtractionResponse.model_validate(data)


def _make_manuscript(
    sections: list[ManuscriptSection] | None = None,
    ref_count: int = 10,
) -> ParsedManuscript:
    """Create a test manuscript with references and sections."""
    refs = [
        Reference(id=i, title=f"Paper {i}", authors=[f"Author{i}"])
        for i in range(1, ref_count + 1)
    ]
    return ParsedManuscript(
        filename="test.docx",
        sections=sections or [],
        references=refs,
        citation_style="numbered",
    )


# --- Parser unit tests ---


class TestClaimParser:
    def test_apply_priority_factual(self) -> None:
        claim = Claim(id=1, claim_type="factual", priority="low")
        result = apply_priority(claim)
        assert result.priority == "high"

    def test_apply_priority_background(self) -> None:
        claim = Claim(id=1, claim_type="background", priority="high")
        result = apply_priority(claim)
        assert result.priority == "low"

    def test_apply_priority_contrast(self) -> None:
        claim = Claim(id=1, claim_type="contrast", priority="low")
        result = apply_priority(claim)
        assert result.priority == "high"

    def test_filter_invalid_refs(self) -> None:
        claims = [
            Claim(id=1, reference_ids=[1, 2, 99]),
            Claim(id=2, reference_ids=[99]),
        ]
        result = filter_invalid_refs(claims, {1, 2, 3})
        assert len(result) == 1
        assert result[0].reference_ids == [1, 2]

    def test_deduplicate_claims(self) -> None:
        claims = [
            Claim(id=1, extracted_claim="Drug X works", reference_ids=[1]),
            Claim(id=2, extracted_claim="Drug X works", reference_ids=[1]),
        ]
        result = deduplicate_claims(claims)
        assert len(result) == 1

    def test_assign_sequential_ids(self) -> None:
        claims = [Claim(id=0), Claim(id=0), Claim(id=0)]
        result = assign_sequential_ids(claims, start_id=5)
        assert [c.id for c in result] == [5, 6, 7]


# --- Extractor integration tests (mocked LLM) ---


class TestExtractClaims:
    @pytest.mark.asyncio
    async def test_ce01_single_factual_claim(self) -> None:
        """CE-01: Single factual claim extracts correctly."""
        fixture = _load_fixture("single_factual.json")
        section = ManuscriptSection(
            heading="Results",
            text="Drug X reduced mortality by 30% in elderly patients [7].",
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert claims[0].claim_type == "factual"
        assert claims[0].priority == "high"
        assert 7 in claims[0].reference_ids

    @pytest.mark.asyncio
    async def test_ce02_multiple_refs_grouped(self) -> None:
        """CE-02: Multiple refs for one claim groups correctly."""
        fixture = _load_fixture("multiple_refs.json")
        section = ManuscriptSection(
            heading="Introduction",
            text="Several studies have demonstrated the efficacy of nanoparticle delivery [1, 2, 3].",
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert sorted(claims[0].reference_ids) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_ce03_compound_citation_separated(self) -> None:
        """CE-03: Different sub-claims separated correctly."""
        fixture = _load_fixture("compound_citation.json")
        section = ManuscriptSection(
            heading="Results",
            text="Drug X reduces pain [1] and improves joint mobility [2].",
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 2
        ref_id_sets = [set(c.reference_ids) for c in claims]
        assert {1} in ref_id_sets
        assert {2} in ref_id_sets

    @pytest.mark.asyncio
    async def test_ce04_background_citation(self) -> None:
        """CE-04: Background citation classified correctly."""
        fixture = _load_fixture("background.json")
        section = ManuscriptSection(
            heading="Introduction",
            text="Cancer is a leading cause of death worldwide [4].",
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert claims[0].claim_type == "background"
        assert claims[0].priority == "low"

    @pytest.mark.asyncio
    async def test_ce05_contrast_citation(self) -> None:
        """CE-05: Contrast citation classified correctly."""
        fixture = _load_fixture("contrast.json")
        section = ManuscriptSection(
            heading="Discussion",
            text="Unlike Jones et al. [5] who reported no significant effect, our study found clear benefit.",
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert claims[0].claim_type == "contrast"
        assert claims[0].priority == "high"

    @pytest.mark.asyncio
    async def test_ce07_full_section_extraction(self) -> None:
        """CE-07: Full section extracts multiple claims without crash."""
        fixture = _load_fixture("full_section.json")
        section = ManuscriptSection(
            heading="Introduction",
            text=(
                "Osteoarthritis is a chronic condition [1-3] affecting millions. "
                "Recent studies [4, 5] have shown that nanoparticles can deliver "
                "drugs directly to joints [6, 7]."
            ),
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) >= 2
        # All claims should have sequential IDs
        ids = [c.id for c in claims]
        assert ids == list(range(1, len(claims) + 1))

    @pytest.mark.asyncio
    async def test_empty_section_no_llm_call(self) -> None:
        """Empty section (no citations) returns empty, no LLM call."""
        section = ManuscriptSection(
            heading="Acknowledgements",
            text="The authors thank their colleagues.",
        )
        manuscript = _make_manuscript(sections=[section])

        mock_llm = AsyncMock()
        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            mock_llm,
        ):
            claims = await extract_claims(manuscript)

        assert claims == []
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_invalid_json_graceful(self) -> None:
        """LLM returning invalid JSON is handled gracefully."""
        from refcheck.llm.client import LLMResponseInvalidError

        section = ManuscriptSection(
            heading="Results",
            text="Drug X works [1].",
        )
        manuscript = _make_manuscript(sections=[section])

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            side_effect=LLMResponseInvalidError("bad json"),
        ):
            claims = await extract_claims(manuscript)

        assert claims == []

    @pytest.mark.asyncio
    async def test_nonexistent_ref_ids_filtered(self) -> None:
        """Claims with nonexistent reference IDs are filtered out."""
        response = ClaimExtractionResponse(
            claims=[
                Claim(
                    id=0,
                    extracted_claim="Test claim",
                    reference_ids=[999],
                    claim_type="factual",
                ),
            ]
        )
        section = ManuscriptSection(
            heading="Results",
            text="Something [999].",
        )
        manuscript = _make_manuscript(sections=[section], ref_count=5)

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=response,
        ):
            claims = await extract_claims(manuscript)

        assert claims == []

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        """Duplicate claims across sections are deduplicated."""
        fixture = _load_fixture("single_factual.json")
        sections = [
            ManuscriptSection(
                heading="Abstract",
                text="Drug X reduced mortality by 30% in elderly patients [7].",
            ),
            ManuscriptSection(
                heading="Results",
                text="As mentioned, Drug X reduced mortality by 30% in elderly patients [7].",
            ),
        ]
        manuscript = _make_manuscript(sections=sections)

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            new_callable=AsyncMock,
            return_value=fixture,
        ):
            claims = await extract_claims(manuscript)

        # Dedup should merge the identical claims
        assert len(claims) == 1


# --- V2: Atomic decomposition tests ---


class TestAtomicDecomposition:
    @pytest.mark.asyncio
    async def test_factual_high_priority_gets_decomposition(self) -> None:
        """CE-06: High-priority factual claim gets atomic decomposition."""
        extraction_fixture = _load_fixture("single_factual.json")
        decomposition = AtomicDecompositionResponse(
            atoms=[
                "Drug X was studied for its effect on mortality",
                "The mortality reduction was 30%",
                "The study population was elderly patients",
            ],
        )
        section = ManuscriptSection(
            heading="Results",
            text="Drug X reduced mortality by 30% in elderly patients [7].",
        )
        manuscript = _make_manuscript(sections=[section])

        async def mock_call_llm(
            template: str, **kwargs: object,
        ) -> ClaimExtractionResponse | AtomicDecompositionResponse:
            if template == "claim_extraction":
                return extraction_fixture
            if template == "atomic_decomposition":
                return decomposition
            raise ValueError(f"Unexpected template: {template}")

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            side_effect=mock_call_llm,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert len(claims[0].atomic_claims) == 3
        assert "mortality reduction was 30%" in claims[0].atomic_claims[1]

    @pytest.mark.asyncio
    async def test_background_claim_skips_decomposition(self) -> None:
        """Background claims are not decomposed."""
        extraction_fixture = _load_fixture("background.json")
        section = ManuscriptSection(
            heading="Introduction",
            text="Cancer is a leading cause of death worldwide [4].",
        )
        manuscript = _make_manuscript(sections=[section])

        call_count = 0

        async def mock_call_llm(
            template: str, **kwargs: object,
        ) -> ClaimExtractionResponse:
            nonlocal call_count
            call_count += 1
            if template == "claim_extraction":
                return extraction_fixture
            raise ValueError(f"Unexpected template: {template}")

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            side_effect=mock_call_llm,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert claims[0].atomic_claims == []
        # Only the extraction call, no decomposition call
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_low_priority_factual_skips_decomposition(self) -> None:
        """Factual claims that end up low priority skip decomposition."""
        # Create a factual claim that has low priority explicitly
        response = ClaimExtractionResponse(
            claims=[
                Claim(
                    id=0,
                    extracted_claim="Drug Y exists",
                    reference_ids=[1],
                    claim_type="background",
                    priority="low",
                ),
            ]
        )
        section = ManuscriptSection(
            heading="Introduction",
            text="Drug Y exists as a treatment option [1].",
        )
        manuscript = _make_manuscript(sections=[section])

        call_count = 0

        async def mock_call_llm(
            template: str, **kwargs: object,
        ) -> ClaimExtractionResponse:
            nonlocal call_count
            call_count += 1
            if template == "claim_extraction":
                return response
            raise ValueError(f"Unexpected: {template}")

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            side_effect=mock_call_llm,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert claims[0].atomic_claims == []
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_decomposition_failure_leaves_atoms_empty(self) -> None:
        """Decomposition LLM failure leaves atoms empty (graceful)."""
        from refcheck.llm.client import LLMResponseInvalidError

        extraction_fixture = _load_fixture("single_factual.json")
        section = ManuscriptSection(
            heading="Results",
            text="Drug X reduced mortality by 30% in elderly patients [7].",
        )
        manuscript = _make_manuscript(sections=[section])

        async def mock_call_llm(
            template: str, **kwargs: object,
        ) -> ClaimExtractionResponse:
            if template == "claim_extraction":
                return extraction_fixture
            if template == "atomic_decomposition":
                raise LLMResponseInvalidError("bad json")
            raise ValueError(f"Unexpected: {template}")

        with patch(
            "refcheck.stages.extract_claims.extractor.call_llm",
            side_effect=mock_call_llm,
        ):
            claims = await extract_claims(manuscript)

        assert len(claims) == 1
        assert claims[0].atomic_claims == []
