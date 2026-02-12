"""Tests for all Pydantic data models."""

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from refcheck.models.claim import AtomicClaim, Claim
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


# --- Claim models ---


class TestClaim:
    def test_minimal_claim(self) -> None:
        c = Claim(id=1, reference_id=1)
        assert c.claim_type == "unknown"
        assert c.priority == "medium"

    def test_full_claim(self) -> None:
        c = Claim(
            id=1,
            reference_id=5,
            manuscript_text="Drug X reduces mortality [5]",
            extracted_claim="Drug X reduces mortality",
            claim_type="factual",
            priority="high",
            section="Results",
        )
        assert c.claim_type == "factual"


class TestAtomicClaim:
    def test_atomic_claim(self) -> None:
        ac = AtomicClaim(id=1, parent_claim_id=1, text="Drug X reduces mortality")
        assert ac.verifiable is True
        assert ac.tags == []


# --- Verification models ---


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


class TestAtomicVerification:
    def test_atomic_verification(self) -> None:
        av = AtomicVerification(atomic_claim_id=1)
        assert av.verdict == "cannot_verify"


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
        assert ps.manuscript is None

    def test_state_with_data(self) -> None:
        ref = Reference(id=1, title="Test")
        ps = PipelineState(
            session_id="sess_123",
            references=[ref],
            current_stage=1,
            status="running",
        )
        assert len(ps.references) == 1


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
