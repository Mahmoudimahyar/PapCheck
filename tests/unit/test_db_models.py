"""Tests for database models and converters."""

import json

from sqlmodel import Session

from refcheck.db.converters import (
    claim_to_db,
    db_to_claim,
    db_to_reference,
    db_to_session,
    db_to_verification,
    reference_to_db,
    session_to_db,
    verification_to_db,
)
from refcheck.db.models import ClaimDB, ReferenceDB, SessionDB, VerificationDB
from refcheck.models.claim import Claim
from refcheck.models.pipeline import Session as PydanticSession
from refcheck.models.reference import Reference
from refcheck.models.verification import AtomicVerification, VerificationResult


class TestReferenceRoundTrip:
    def test_reference_converts_to_db_and_back(self) -> None:
        """Reference → ReferenceDB → Reference produces identical data."""
        ref = Reference(
            id=7, raw_text="Smith et al. 2020",
            title="Drug X study", authors=["Smith J", "Doe A"],
            year=2020, doi="10.1234/test", journal="Lancet",
            pmid="12345", source_status="found",
            retraction_status="ok",
        )
        db_ref = reference_to_db(ref, "sess_abc")
        assert db_ref.ref_number == 7
        assert db_ref.session_id == "sess_abc"
        assert json.loads(db_ref.authors_json) == ["Smith J", "Doe A"]

        restored = db_to_reference(db_ref)
        assert restored.id == 7
        assert restored.title == "Drug X study"
        assert restored.authors == ["Smith J", "Doe A"]
        assert restored.doi == "10.1234/test"
        assert restored.source_status == "found"

    def test_reference_with_none_fields(self) -> None:
        """Reference with None fields converts correctly."""
        ref = Reference(id=1, title="Minimal ref")
        db_ref = reference_to_db(ref, "sess_1")
        restored = db_to_reference(db_ref)
        assert restored.doi is None
        assert restored.pdf_path is None
        assert restored.authors == []


class TestClaimRoundTrip:
    def test_claim_converts_to_db_and_back(self) -> None:
        """Claim → ClaimDB → Claim produces identical data."""
        claim = Claim(
            id=5, manuscript_text="Drug X reduces pain [1]",
            extracted_claim="Drug X reduces pain",
            claim_type="factual", reference_ids=[1, 2],
            priority="high", section_heading="Results",
            atomic_claims=["Drug X exists", "Drug X reduces pain"],
        )
        db_claim = claim_to_db(claim, "sess_abc")
        assert db_claim.claim_number == 5
        assert json.loads(db_claim.reference_ids_json) == [1, 2]
        assert json.loads(db_claim.atomic_claims_json) == [
            "Drug X exists", "Drug X reduces pain",
        ]

        restored = db_to_claim(db_claim)
        assert restored.id == 5
        assert restored.reference_ids == [1, 2]
        assert restored.atomic_claims == ["Drug X exists", "Drug X reduces pain"]
        assert restored.priority == "high"


class TestVerificationRoundTrip:
    def test_verification_converts_to_db_and_back(self) -> None:
        """VerificationResult → VerificationDB → VerificationResult."""
        v = VerificationResult(
            claim_id=1, reference_id=7,
            verdict="contradicted", confidence=0.91,
            evidence_quotes=["non-significant 12%"],
            reasoning="30% vs 12%", tier=2,
            source_coverage="full_text",
            user_override=True,
            user_override_reason="Manual check",
            original_verdict="not_supported",
            original_confidence=0.85,
        )
        db_v = verification_to_db(v, "sess_abc")
        restored = db_to_verification(db_v)
        assert restored.verdict == "contradicted"
        assert restored.confidence == 0.91
        assert restored.evidence_quotes == ["non-significant 12%"]
        assert restored.tier == 2
        assert restored.user_override is True
        assert restored.original_verdict == "not_supported"

    def test_verification_with_atomic_results(self) -> None:
        """Atomic results serialize and deserialize correctly."""
        v = VerificationResult(
            claim_id=1, reference_id=1,
            verdict="supported", confidence=0.9,
            atomic_results=[
                AtomicVerification(atom="Drug X exists", verified=True, evidence="p.3"),
                AtomicVerification(atom="Reduces pain", verified=False, evidence=None),
            ],
        )
        db_v = verification_to_db(v, "sess_abc")
        assert db_v.atomic_results_json is not None

        restored = db_to_verification(db_v)
        assert restored.atomic_results is not None
        assert len(restored.atomic_results) == 2
        assert restored.atomic_results[0].atom == "Drug X exists"
        assert restored.atomic_results[0].verified is True
        assert restored.atomic_results[1].verified is False


class TestSessionRoundTrip:
    def test_session_converts_to_db_and_back(self) -> None:
        """Session → SessionDB → Session."""
        session = PydanticSession(
            id="sess_abc", status="running",
            manuscript_filename="paper.docx", pdf_count=10,
        )
        db_sess = session_to_db(session)
        assert db_sess.id == "sess_abc"

        restored = db_to_session(db_sess)
        assert restored.id == "sess_abc"
        assert restored.status == "running"
        assert restored.manuscript_filename == "paper.docx"
        assert restored.pdf_count == 10


class TestDBModelPersistence:
    def test_session_persists(self, db_session: Session) -> None:
        """SessionDB can be saved and retrieved."""
        sess = SessionDB(id="sess_test", manuscript_filename="test.docx")
        db_session.add(sess)
        db_session.commit()

        loaded = db_session.get(SessionDB, "sess_test")
        assert loaded is not None
        assert loaded.manuscript_filename == "test.docx"

    def test_reference_persists(self, db_session: Session) -> None:
        """ReferenceDB can be saved and retrieved."""
        db_session.add(SessionDB(id="sess_ref"))
        db_session.add(ReferenceDB(
            session_id="sess_ref", ref_number=1, title="Test",
            authors_json='["Smith"]',
        ))
        db_session.commit()

        from sqlmodel import select
        stmt = select(ReferenceDB).where(ReferenceDB.session_id == "sess_ref")
        refs = db_session.exec(stmt).all()
        assert len(refs) == 1
        assert refs[0].title == "Test"

    def test_claim_persists(self, db_session: Session) -> None:
        """ClaimDB can be saved and retrieved."""
        db_session.add(SessionDB(id="sess_clm"))
        db_session.add(ClaimDB(
            session_id="sess_clm", claim_number=1,
            extracted_claim="Test claim",
        ))
        db_session.commit()

        from sqlmodel import select
        stmt = select(ClaimDB).where(ClaimDB.session_id == "sess_clm")
        claims = db_session.exec(stmt).all()
        assert len(claims) == 1

    def test_verification_persists(self, db_session: Session) -> None:
        """VerificationDB can be saved and retrieved."""
        db_session.add(SessionDB(id="sess_ver"))
        db_session.add(VerificationDB(
            session_id="sess_ver", claim_id=1, reference_id=1,
            verdict="supported", confidence=0.95,
        ))
        db_session.commit()

        from sqlmodel import select
        stmt = select(VerificationDB).where(
            VerificationDB.session_id == "sess_ver",
        )
        vs = db_session.exec(stmt).all()
        assert len(vs) == 1
        assert vs[0].confidence == 0.95
