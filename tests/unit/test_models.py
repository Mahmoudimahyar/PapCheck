"""Tests for all Pydantic data models."""

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from refcheck.models.claim import AtomicClaim, Claim
from refcheck.models.evidence import ClaimLocation, EvidenceSection, QuoteHighlight
from refcheck.models.matching import MatchResult
from refcheck.models.pipeline import (
    Intervention,
    PipelineEvent,
    PipelineState,
    Session,
    StageStatus,
)
from refcheck.models.reference import (
    InTextCitation,
    ManuscriptSection,
    ParsedManuscript,
    Reference,
)
from refcheck.models.verification import (
    AtomicVerification,
    VerificationResult,
)


# --- Reference models ---


class TestReference:
    def test_minimal_reference(self) -> None:
        ref = Reference(id=1)
        assert ref.id == 1
        assert ref.title == ""
        assert ref.source_status == "pending"
        assert ref.pdf_path is None

    def test_full_reference(self) -> None:
        ref = Reference(
            id=1,
            raw_text="Smith J. Drug X. Lancet. 2020;1:1-5.",
            title="Drug X",
            authors=["Smith J"],
            year=2020,
            doi="10.1234/test",
            journal="Lancet",
            pmid="12345678",
            source_status="found",
            pdf_path=Path("/tmp/test.pdf"),
            pdf_source="user_upload",
        )
        assert ref.year == 2020
        assert ref.doi == "10.1234/test"
        assert ref.pdf_source == "user_upload"

    def test_reference_json_roundtrip(self) -> None:
        ref = Reference(id=1, title="Test", doi="10.1234/test")
        data = ref.model_dump_json()
        restored = Reference.model_validate_json(data)
        assert restored.id == ref.id
        assert restored.doi == ref.doi

    def test_reference_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            Reference(id=1, source_status="invalid_status")  # type: ignore[arg-type]


class TestInTextCitation:
    def test_basic_citation(self) -> None:
        cite = InTextCitation(raw_text="[1-3]", position=100, reference_ids=[1, 2, 3])
        assert cite.reference_ids == [1, 2, 3]

    def test_default_reference_ids(self) -> None:
        cite = InTextCitation(raw_text="[1]", position=0)
        assert cite.reference_ids == []


class TestManuscriptSection:
    def test_section_with_heading(self) -> None:
        sec = ManuscriptSection(heading="Introduction", text="Some text.")
        assert sec.heading == "Introduction"
        assert sec.citations == []

    def test_section_no_heading(self) -> None:
        sec = ManuscriptSection(text="Body text")
        assert sec.heading is None


class TestParsedManuscript:
    def test_minimal_manuscript(self) -> None:
        ms = ParsedManuscript(filename="test.docx")
        assert ms.filename == "test.docx"
        assert ms.references == []
        assert ms.citation_style == "unknown"
        assert ms.has_field_codes is False

    def test_manuscript_with_data(self) -> None:
        ref = Reference(id=1, title="Test Ref")
        sec = ManuscriptSection(heading="Intro", text="Hello [1]")
        ms = ParsedManuscript(
            filename="paper.docx",
            sections=[sec],
            references=[ref],
            citation_style="numbered",
            warnings=["Missing DOIs"],
        )
        assert len(ms.references) == 1
        assert ms.citation_style == "numbered"


# --- Matching models ---


class TestMatchResult:
    def test_valid_match(self) -> None:
        m = MatchResult(
            reference_id=1,
            pdf_path="/tmp/test.pdf",
            confidence=0.95,
            match_method="doi",
        )
        assert m.confidence == 0.95
        assert not m.needs_user_confirmation

    def test_unmatched_default(self) -> None:
        m = MatchResult(reference_id=1, confidence=0.0)
        assert m.match_method == "unmatched"

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            MatchResult(reference_id=1, confidence=1.5)
        with pytest.raises(ValidationError):
            MatchResult(reference_id=1, confidence=-0.1)

    def test_json_roundtrip(self) -> None:
        m = MatchResult(reference_id=1, confidence=0.9, match_method="title_fuzzy")
        data = m.model_dump_json()
        restored = MatchResult.model_validate_json(data)
        assert restored.match_method == "title_fuzzy"


# --- Claim models (V1) ---


class TestClaim:
    def test_minimal_claim(self) -> None:
        c = Claim(id=1)
        assert c.claim_type == "factual"
        assert c.priority == "medium"
        assert c.reference_ids == []
        assert c.section_heading == ""

    def test_full_claim(self) -> None:
        c = Claim(
            id=1,
            manuscript_text="Drug X reduces mortality [5]",
            extracted_claim="Drug X reduces mortality",
            claim_type="factual",
            reference_ids=[5],
            priority="high",
            section_heading="Results",
        )
        assert c.claim_type == "factual"
        assert c.reference_ids == [5]
        assert c.section_heading == "Results"

    def test_claim_type_validation(self) -> None:
        """Reject invalid claim types."""
        with pytest.raises(ValidationError):
            Claim(id=1, claim_type="invalid_type")  # type: ignore[arg-type]

    def test_claim_priority_validation(self) -> None:
        """Reject invalid priority values."""
        with pytest.raises(ValidationError):
            Claim(id=1, priority="urgent")  # type: ignore[arg-type]

    def test_claim_multiple_references(self) -> None:
        """Claim can reference multiple sources."""
        c = Claim(id=1, reference_ids=[1, 2, 3])
        assert len(c.reference_ids) == 3

    def test_all_claim_types(self) -> None:
        """All six claim types are valid."""
        valid_types = [
            "factual", "methodological", "background",
            "attribution", "contrast", "interpretive",
        ]
        for ct in valid_types:
            c = Claim(id=1, claim_type=ct)  # type: ignore[arg-type]
            assert c.claim_type == ct


class TestAtomicClaim:
    def test_atomic_claim(self) -> None:
        ac = AtomicClaim(id=1, parent_claim_id=1, text="Drug X reduces mortality")
        assert ac.verifiable is True
        assert ac.tags == []


# --- Verification models (V1) ---


class TestVerificationResult:
    def test_default_verdict(self) -> None:
        vr = VerificationResult(claim_id=1, reference_id=1)
        assert vr.verdict == "cannot_verify"
        assert vr.confidence == 0.0

    def test_full_result(self) -> None:
        vr = VerificationResult(
            claim_id=1,
            reference_id=1,
            verdict="contradicted",
            confidence=0.91,
            evidence_quotes=["12% reduction (p=0.08)"],
            reasoning="Source shows non-significant result",
            tier=1,
            source_coverage="full_text",
        )
        assert vr.verdict == "contradicted"

    def test_verdict_literal_validation(self) -> None:
        """Reject invalid verdict values."""
        with pytest.raises(ValidationError):
            VerificationResult(
                claim_id=1, reference_id=1, verdict="invalid_verdict"  # type: ignore[arg-type]
            )

    def test_confidence_bounds_upper(self) -> None:
        """Reject confidence > 1.0."""
        with pytest.raises(ValidationError):
            VerificationResult(claim_id=1, reference_id=1, confidence=1.5)

    def test_confidence_bounds_lower(self) -> None:
        """Reject confidence < 0.0."""
        with pytest.raises(ValidationError):
            VerificationResult(claim_id=1, reference_id=1, confidence=-0.1)

    def test_source_coverage_values(self) -> None:
        """All source_coverage options are valid."""
        for cov in ["full_text", "abstract_only", "relevant_sections", "no_source"]:
            vr = VerificationResult(
                claim_id=1, reference_id=1, source_coverage=cov  # type: ignore[arg-type]
            )
            assert vr.source_coverage == cov

    def test_tier_values(self) -> None:
        """Tier must be 1, 2, or 3."""
        for t in [1, 2, 3]:
            vr = VerificationResult(claim_id=1, reference_id=1, tier=t)  # type: ignore[arg-type]
            assert vr.tier == t

    def test_needs_user_review_default(self) -> None:
        """needs_user_review defaults to False."""
        vr = VerificationResult(claim_id=1, reference_id=1)
        assert vr.needs_user_review is False

    def test_all_verdicts(self) -> None:
        """All five verdict values are valid."""
        valid = [
            "supported", "partially_supported", "not_supported",
            "contradicted", "cannot_verify",
        ]
        for v in valid:
            vr = VerificationResult(
                claim_id=1, reference_id=1, verdict=v  # type: ignore[arg-type]
            )
            assert vr.verdict == v


class TestAtomicVerification:
    def test_atomic_verification(self) -> None:
        av = AtomicVerification()
        assert av.atom == ""
        assert av.verified is None


# --- Pipeline models ---


class TestStageStatus:
    def test_default_stage(self) -> None:
        ss = StageStatus(stage=1, name="Parse Manuscript")
        assert ss.status == "pending"
        assert ss.elapsed_seconds == 0.0


class TestPipelineEvent:
    def test_event(self) -> None:
        ev = PipelineEvent(stage=1, status="running", message="Parsing...")
        assert ev.stage == 1

    def test_event_with_progress(self) -> None:
        ev = PipelineEvent(
            stage=3,
            status="running",
            progress={"current": 10, "total": 50},
        )
        assert ev.progress is not None
        assert ev.progress["current"] == 10


class TestIntervention:
    def test_intervention(self) -> None:
        iv = Intervention(
            intervention_type="confirm_match",
            reference_id=2,
            details="82% title match",
        )
        assert iv.intervention_type == "confirm_match"


class TestPipelineState:
    def test_empty_state(self) -> None:
        ps = PipelineState(session_id="sess_123")
        assert ps.status == "created"
        assert ps.references == []
        assert ps.claims == []
        assert ps.verification_results == []
        assert ps.manuscript is None

    def test_state_with_data(self) -> None:
        ref = Reference(id=1, title="Test")
        claim = Claim(id=1, reference_ids=[1], extracted_claim="Test claim")
        vr = VerificationResult(claim_id=1, reference_id=1, verdict="supported")
        ps = PipelineState(
            session_id="sess_123",
            references=[ref],
            claims=[claim],
            verification_results=[vr],
            current_stage=5,
            status="running",
        )
        assert len(ps.references) == 1
        assert len(ps.claims) == 1
        assert len(ps.verification_results) == 1


class TestSession:
    def test_session_creation(self) -> None:
        s = Session(id="sess_abc", manuscript_filename="paper.docx", pdf_count=10)
        assert s.status == "created"
        assert isinstance(s.created_at, datetime)

    def test_session_json_roundtrip(self) -> None:
        s = Session(id="sess_abc", manuscript_filename="test.docx")
        data = s.model_dump_json()
        restored = Session.model_validate_json(data)
        assert restored.id == "sess_abc"


# --- Evidence models (V2: Manuscript Viewer) ---


class TestClaimLocation:
    def test_valid_location(self) -> None:
        loc = ClaimLocation(paragraph_index=2, char_start=10, char_end=50)
        assert loc.paragraph_index == 2
        assert loc.char_start == 10
        assert loc.char_end == 50
        assert loc.citation_markers == []
        assert loc.section_heading == ""
        assert loc.in_figure_or_table is False

    def test_paragraph_index_nonnegative(self) -> None:
        with pytest.raises(ValidationError):
            ClaimLocation(paragraph_index=-1, char_start=0, char_end=10)

    def test_char_start_nonnegative(self) -> None:
        with pytest.raises(ValidationError):
            ClaimLocation(paragraph_index=0, char_start=-5, char_end=10)

    def test_full_location(self) -> None:
        loc = ClaimLocation(
            paragraph_index=3,
            char_start=5,
            char_end=40,
            citation_markers=["[7]", "[8]"],
            section_heading="Results",
            in_figure_or_table=True,
        )
        assert loc.citation_markers == ["[7]", "[8]"]
        assert loc.section_heading == "Results"
        assert loc.in_figure_or_table is True

    def test_json_roundtrip(self) -> None:
        loc = ClaimLocation(
            paragraph_index=1, char_start=0, char_end=20,
            citation_markers=["[3]"],
        )
        data = loc.model_dump_json()
        restored = ClaimLocation.model_validate_json(data)
        assert restored.paragraph_index == 1
        assert restored.citation_markers == ["[3]"]


class TestQuoteHighlight:
    def test_valid_highlight(self) -> None:
        qh = QuoteHighlight(
            quote="28% reduction", char_start=42, char_end=55,
        )
        assert qh.match_type == "direct"
        assert qh.manuscript_element == ""

    def test_match_type_literal(self) -> None:
        for mt in ["direct", "paraphrased", "numeric_mismatch", "absent"]:
            qh = QuoteHighlight(quote="t", match_type=mt)  # type: ignore[arg-type]
            assert qh.match_type == mt

    def test_invalid_match_type(self) -> None:
        with pytest.raises(ValidationError):
            QuoteHighlight(quote="t", match_type="wrong")  # type: ignore[arg-type]


class TestEvidenceSection:
    def test_minimal_section(self) -> None:
        es = EvidenceSection()
        assert es.section_heading == ""
        assert es.full_text == ""
        assert es.page_number is None
        assert es.quote_highlights == []

    def test_full_section(self) -> None:
        es = EvidenceSection(
            section_heading="Results",
            full_text="Drug X resulted in a 28% reduction...",
            page_number=4,
            quote_highlights=[
                QuoteHighlight(quote="28% reduction", char_start=22, char_end=35),
            ],
        )
        assert len(es.quote_highlights) == 1
        assert es.quote_highlights[0].quote == "28% reduction"

    def test_json_roundtrip(self) -> None:
        es = EvidenceSection(
            section_heading="Discussion",
            full_text="Significant findings.",
            quote_highlights=[
                QuoteHighlight(
                    quote="Significant", char_start=0, char_end=11,
                    match_type="direct", manuscript_element="significance",
                ),
            ],
        )
        data = es.model_dump_json()
        restored = EvidenceSection.model_validate_json(data)
        assert restored.section_heading == "Discussion"
        assert len(restored.quote_highlights) == 1
        assert restored.quote_highlights[0].match_type == "direct"


class TestClaimWithLocation:
    def test_claim_location_none_default(self) -> None:
        c = Claim(id=1)
        assert c.location is None

    def test_claim_with_location(self) -> None:
        loc = ClaimLocation(paragraph_index=2, char_start=5, char_end=50)
        c = Claim(id=1, location=loc)
        assert c.location is not None
        assert c.location.paragraph_index == 2

    def test_claim_location_json_roundtrip(self) -> None:
        loc = ClaimLocation(
            paragraph_index=3, char_start=10, char_end=60,
            citation_markers=["[7]"], section_heading="Results",
        )
        c = Claim(id=1, manuscript_text="test [7]", location=loc)
        data = c.model_dump_json()
        restored = Claim.model_validate_json(data)
        assert restored.location is not None
        assert restored.location.citation_markers == ["[7]"]


class TestVerificationResultWithEvidence:
    def test_evidence_sections_default(self) -> None:
        vr = VerificationResult(claim_id=1, reference_id=1)
        assert vr.evidence_sections == []

    def test_with_evidence_sections(self) -> None:
        es = EvidenceSection(
            section_heading="Results",
            full_text="28% reduction in mortality.",
            quote_highlights=[
                QuoteHighlight(
                    quote="28% reduction", char_start=0, char_end=13,
                    match_type="numeric_mismatch",
                ),
            ],
        )
        vr = VerificationResult(
            claim_id=1, reference_id=1, verdict="partially_supported",
            evidence_sections=[es],
        )
        assert len(vr.evidence_sections) == 1
        assert vr.evidence_sections[0].quote_highlights[0].match_type == "numeric_mismatch"

    def test_evidence_sections_json_roundtrip(self) -> None:
        vr = VerificationResult(
            claim_id=1, reference_id=1,
            evidence_sections=[
                EvidenceSection(section_heading="Methods", full_text="..."),
                EvidenceSection(section_heading="Results", full_text="..."),
            ],
        )
        data = vr.model_dump_json()
        restored = VerificationResult.model_validate_json(data)
        assert len(restored.evidence_sections) == 2
