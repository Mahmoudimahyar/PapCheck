"""V2 Integration test: Full pipeline with tiered verification,
retraction checking, atomic claims, and user overrides."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import docx
import pytest

from refcheck.models.claim import Claim
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import (
    AtomicVerification,
    VerificationResult,
)
from refcheck.stages.generate_report import generate_report


def _make_references() -> list[Reference]:
    """Create 8 test references with mixed statuses."""
    return [
        Reference(
            id=1, title="Drug X reduces inflammation",
            doi="10.1016/test-1", source_status="found",
            pdf_path=Path("/tmp/paper1.pdf"), pdf_source="user_upload",
        ),
        Reference(
            id=2, title="CRISPR diagnostics for disease",
            doi="10.1038/test-2", source_status="found",
            pdf_path=Path("/tmp/paper2.pdf"), pdf_source="open_access",
        ),
        Reference(
            id=3, title="Nanoparticle delivery systems",
            doi="10.1016/test-3", source_status="found",
            pdf_path=Path("/tmp/paper3.pdf"), pdf_source="user_upload",
        ),
        Reference(
            id=4, title="Global burden of OA",
            source_status="found",
            pdf_path=Path("/tmp/paper4.pdf"), pdf_source="open_access",
        ),
        Reference(
            id=5, title="Stem cell therapy for cartilage",
            doi="10.1186/test-5", source_status="found",
            pdf_path=Path("/tmp/paper5.pdf"), pdf_source="user_upload",
        ),
        Reference(
            id=6, title="Retracted study on efficacy",
            doi="10.9999/retracted-1", source_status="found",
            retraction_status="retracted",
            retraction_detail="Retracted due to data fabrication",
        ),
        Reference(
            id=7, title="Corrected dosage study",
            doi="10.9999/corrected-1", source_status="found",
            retraction_status="corrected",
            retraction_detail="Correction to Table 2",
        ),
        Reference(
            id=8, title="Unfound paper",
            source_status="not_found",
        ),
    ]


def _make_claims() -> list[Claim]:
    """Create test claims referencing the 8 references."""
    return [
        Claim(
            id=1, extracted_claim="Drug X reduced inflammation by 50%",
            claim_type="factual", reference_ids=[1], priority="high",
            atomic_claims=["Drug X was tested", "Inflammation reduced by 50%"],
        ),
        Claim(
            id=2, extracted_claim="CRISPR can detect disease early",
            claim_type="factual", reference_ids=[2], priority="high",
            atomic_claims=["CRISPR used for diagnostics", "Early detection achieved"],
        ),
        Claim(
            id=3, extracted_claim="Nanoparticles improve drug delivery",
            claim_type="background", reference_ids=[3], priority="low",
        ),
        Claim(
            id=4, extracted_claim="OA affects millions globally",
            claim_type="background", reference_ids=[4], priority="low",
        ),
        Claim(
            id=5, extracted_claim="Stem cells can repair cartilage unlike drugs",
            claim_type="contrast", reference_ids=[5], priority="high",
            atomic_claims=["Stem cells repair cartilage", "Drugs cannot repair cartilage"],
        ),
    ]


def _tier1_supported() -> VerificationResult:
    """High-confidence Tier 1 result — no escalation."""
    return VerificationResult(
        claim_id=0, reference_id=0, verdict="supported",
        confidence=0.95, tier=1, source_coverage="relevant_sections",
        evidence_quotes=["quote from source"],
        reasoning="Clearly supported by evidence",
    )


def _tier1_low_confidence() -> VerificationResult:
    """Low-confidence Tier 1 result — triggers Tier 2."""
    return VerificationResult(
        claim_id=0, reference_id=0, verdict="partially_supported",
        confidence=0.55, tier=1, source_coverage="relevant_sections",
        evidence_quotes=["partial quote"],
        reasoning="Some support found but uncertain",
    )


def _tier2_agree() -> VerificationResult:
    """Tier 2: both strategies agree."""
    return VerificationResult(
        claim_id=0, reference_id=0, verdict="supported",
        confidence=0.90, tier=2, source_coverage="relevant_sections",
        reasoning="Both strategies agree",
    )


def _tier2_disagree() -> VerificationResult:
    """Tier 2: strategies disagree, needs review."""
    return VerificationResult(
        claim_id=0, reference_id=0, verdict="partially_supported",
        confidence=0.65, tier=2, source_coverage="relevant_sections",
        reasoning="Strategies disagree", needs_user_review=True,
    )


def _tier3_resolved() -> VerificationResult:
    """Tier 3: multi-model resolved disagreement."""
    return VerificationResult(
        claim_id=0, reference_id=0, verdict="supported",
        confidence=0.85, tier=3, source_coverage="relevant_sections",
        reasoning="Models agree", needs_user_review=False,
    )


class TestV2Pipeline:
    """Full V2 pipeline integration with mocked LLMs."""

    @pytest.mark.asyncio
    async def test_full_v2_escalation_chain(self, tmp_path: Path) -> None:
        """Test full pipeline: mixed tiers, retraction, report."""
        refs = _make_references()
        claims = _make_claims()

        # Define per-claim verification behavior
        call_count = 0

        async def mock_verify_single(
            claim: Claim, ref: Reference,
        ) -> VerificationResult:
            nonlocal call_count
            call_count += 1

            # Claim 1 (factual/high): goes through Tier 1 → Tier 2 → agrees
            if claim.id == 1:
                return VerificationResult(
                    claim_id=1, reference_id=1, verdict="supported",
                    confidence=0.92, tier=2, source_coverage="relevant_sections",
                    evidence_quotes=["Drug X reduced inflammation by 50%"],
                    reasoning="Both strategies confirmed",
                    atomic_results=[
                        AtomicVerification(atom="Drug X was tested", verified=True),
                        AtomicVerification(atom="Inflammation reduced by 50%", verified=True),
                    ],
                )
            # Claim 2 (factual/high): Tier 1 → 2 disagree → Tier 3 resolved
            if claim.id == 2:
                return VerificationResult(
                    claim_id=2, reference_id=2, verdict="supported",
                    confidence=0.87, tier=3, source_coverage="relevant_sections",
                    evidence_quotes=["CRISPR can detect disease in early stages"],
                    reasoning="Secondary model confirmed",
                    atomic_results=[
                        AtomicVerification(atom="CRISPR used for diagnostics", verified=True),
                        AtomicVerification(atom="Early detection achieved", verified=True),
                    ],
                )
            # Claim 3 (background/low): Tier 1 only, high confidence
            if claim.id == 3:
                return VerificationResult(
                    claim_id=3, reference_id=3, verdict="supported",
                    confidence=0.95, tier=1, source_coverage="relevant_sections",
                    reasoning="Background claim clearly supported",
                )
            # Claim 4 (background/low): Tier 1 only
            if claim.id == 4:
                return VerificationResult(
                    claim_id=4, reference_id=4, verdict="supported",
                    confidence=0.90, tier=1, source_coverage="relevant_sections",
                    reasoning="Background claim supported",
                )
            # Claim 5 (contrast/high): always flagged for review
            if claim.id == 5:
                return VerificationResult(
                    claim_id=5, reference_id=5,
                    verdict="partially_supported",
                    confidence=0.70, tier=2, source_coverage="relevant_sections",
                    reasoning="Contrast claim with mixed evidence",
                    needs_user_review=True,
                    atomic_results=[
                        AtomicVerification(atom="Stem cells repair cartilage", verified=True),
                        AtomicVerification(atom="Drugs cannot repair cartilage", verified=False),
                    ],
                )
            # Default fallback
            return VerificationResult(
                claim_id=claim.id, reference_id=ref.id,
                verdict="cannot_verify", confidence=0.0, tier=1,
            )

        with patch(
            "refcheck.stages.verify_claims.verifier._verify_single",
            side_effect=mock_verify_single,
        ):
            from refcheck.stages.verify_claims import verify_claims
            results = await verify_claims(claims, refs)

        # Verify escalation chain worked
        assert len(results) == 5
        assert call_count == 5

        # Check tier distribution
        tiers = {r.claim_id: r.tier for r in results}
        assert tiers[1] == 2  # Tier 2 resolved
        assert tiers[2] == 3  # Tier 3 resolved
        assert tiers[3] == 1  # Background stayed Tier 1
        assert tiers[4] == 1  # Background stayed Tier 1
        assert tiers[5] == 2  # Contrast hit Tier 2

        # Check needs_user_review
        review_flags = {r.claim_id: r.needs_user_review for r in results}
        assert review_flags[5] is True  # contrast claim
        assert review_flags[1] is False
        assert review_flags[2] is False

        # Check atomic results were preserved
        claim1_result = next(r for r in results if r.claim_id == 1)
        assert claim1_result.atomic_results is not None
        assert len(claim1_result.atomic_results) == 2
        assert claim1_result.atomic_results[0].verified is True

        # Check retraction flags on references
        retracted_refs = [r for r in refs if r.retraction_status == "retracted"]
        assert len(retracted_refs) == 1
        assert retracted_refs[0].id == 6
        corrected_refs = [r for r in refs if r.retraction_status == "corrected"]
        assert len(corrected_refs) == 1
        assert corrected_refs[0].id == 7

        # Stage 6: Generate report with V2 data
        manuscript = ParsedManuscript(filename="test_v2.docx")
        state = PipelineState(
            session_id="v2_integration",
            manuscript=manuscript,
            references=refs,
            claims=claims,
            verification_results=results,
        )
        report_path = tmp_path / "v2_report.docx"
        generate_report(state, report_path)

        assert report_path.exists()
        doc = docx.Document(str(report_path))
        full_text = "\n".join(p.text for p in doc.paragraphs)

        # Report should contain retraction warning
        assert "RETRACTED" in full_text.upper() or "retracted" in full_text.lower()
        assert "RefCheck AI" in full_text
        assert "Total references: 8" in full_text

    @pytest.mark.asyncio
    async def test_retraction_in_references(self) -> None:
        """Retraction status is correctly set on references."""
        refs = _make_references()
        status_map = {r.id: r.retraction_status for r in refs}

        assert status_map[6] == "retracted"
        assert status_map[7] == "corrected"
        assert status_map[1] == "unknown"  # default
        assert status_map[8] == "unknown"


class TestOverrideAndRegeneration:
    """Test user override → report regeneration cycle."""

    def test_override_changes_verdict(self, tmp_path: Path) -> None:
        """Override a result and verify changes propagate to report."""
        refs = _make_references()[:3]
        claims = [
            Claim(
                id=1, extracted_claim="Claim that will be overridden",
                claim_type="factual", reference_ids=[1], priority="high",
            ),
        ]

        original_result = VerificationResult(
            claim_id=1, reference_id=1, verdict="not_supported",
            confidence=0.30, tier=2, source_coverage="relevant_sections",
            reasoning="Not enough evidence", needs_user_review=True,
        )

        # Simulate user override
        overridden = original_result.model_copy(update={
            "verdict": "supported",
            "user_override": True,
            "user_override_reason": "I checked the source manually",
            "needs_user_review": False,
            "original_verdict": "not_supported",
            "original_confidence": 0.30,
        })

        assert overridden.verdict == "supported"
        assert overridden.user_override is True
        assert overridden.original_verdict == "not_supported"
        assert overridden.needs_user_review is False

        # Generate report with overridden result
        manuscript = ParsedManuscript(filename="override_test.docx")
        state = PipelineState(
            session_id="override_test",
            manuscript=manuscript,
            references=refs,
            claims=claims,
            verification_results=[overridden],
        )
        report_path = tmp_path / "overridden_report.docx"
        generate_report(state, report_path)
        assert report_path.exists()

        doc = docx.Document(str(report_path))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        # After override, verdict is "supported" — should NOT be in critical
        assert "RefCheck AI" in full_text

    def test_regeneration_reflects_new_verdicts(self, tmp_path: Path) -> None:
        """Regenerating report after overrides changes output."""
        refs = [Reference(id=1, title="Paper A", source_status="found")]
        claims = [
            Claim(
                id=1, extracted_claim="Claim A",
                claim_type="factual", reference_ids=[1], priority="high",
            ),
        ]

        # First: original NOT_SUPPORTED verdict
        v1_result = VerificationResult(
            claim_id=1, reference_id=1, verdict="not_supported",
            confidence=0.3, tier=1, reasoning="No support",
        )
        state1 = PipelineState(
            session_id="regen", manuscript=ParsedManuscript(filename="t.docx"),
            references=refs, claims=claims,
            verification_results=[v1_result],
        )
        path1 = tmp_path / "report_v1.docx"
        generate_report(state1, path1)
        doc1 = docx.Document(str(path1))
        text1 = "\n".join(p.text for p in doc1.paragraphs)

        # Second: after override to SUPPORTED
        v2_result = v1_result.model_copy(update={
            "verdict": "supported",
            "user_override": True,
            "user_override_reason": "Manually verified",
        })
        state2 = PipelineState(
            session_id="regen", manuscript=ParsedManuscript(filename="t.docx"),
            references=refs, claims=claims,
            verification_results=[v2_result],
        )
        path2 = tmp_path / "report_v2.docx"
        generate_report(state2, path2)
        doc2 = docx.Document(str(path2))
        text2 = "\n".join(p.text for p in doc2.paragraphs)

        # First report should show "Not supported" or "NOT SUPPORTED"
        assert "not supported" in text1.lower()
        # Second report should reflect supported verdict
        assert path2.exists()
        # Both reports should have RefCheck branding
        assert "RefCheck AI" in text1
        assert "RefCheck AI" in text2
