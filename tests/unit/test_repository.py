"""Tests for database repository operations."""

from sqlmodel import Session

from refcheck.db.claim_repo import (
    delete_claim,
    get_claims,
    save_claims,
    update_claim,
)
from refcheck.db.models import (
    ClaimDB,
    PipelineEventDB,
    ReferenceDB,
    SessionDB,
    VerificationDB,
)
from refcheck.db.reference_repo import (
    get_all_references,
    get_reference,
    get_references,
    save_references,
    update_reference,
)
from refcheck.db.session_repo import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    update_session,
)
from refcheck.db.verification_repo import (
    get_all_verifications,
    save_verifications,
    update_verification,
)


def _make_session(db: Session, sid: str = "sess_test") -> SessionDB:
    """Create and return a session in the database."""
    sess = SessionDB(id=sid, manuscript_filename="test.docx")
    return create_session(db, sess)


class TestSessionRepo:
    def test_create_and_get(self, db_session: Session) -> None:
        """Create a session and retrieve it."""
        created = _make_session(db_session)
        loaded = get_session(db_session, created.id)
        assert loaded is not None
        assert loaded.id == created.id

    def test_update_session(self, db_session: Session) -> None:
        """Update session fields."""
        _make_session(db_session, "sess_upd")
        updated = update_session(db_session, "sess_upd", status="running")
        assert updated is not None
        assert updated.status == "running"

    def test_list_sessions(self, db_session: Session) -> None:
        """List sessions with pagination."""
        _make_session(db_session, "sess_a")
        _make_session(db_session, "sess_b")
        _make_session(db_session, "sess_c")
        sessions, total = list_sessions(db_session, limit=2, offset=0)
        assert total == 3
        assert len(sessions) == 2

    def test_delete_session(self, db_session: Session) -> None:
        """Delete removes session and associated data."""
        _make_session(db_session, "sess_del")
        db_session.add(ReferenceDB(
            session_id="sess_del", ref_number=1, title="Test",
        ))
        db_session.add(ClaimDB(
            session_id="sess_del", claim_number=1,
        ))
        db_session.commit()

        result = delete_session(db_session, "sess_del")
        assert result is True
        assert get_session(db_session, "sess_del") is None
        assert get_all_references(db_session, "sess_del") == []

    def test_delete_nonexistent_returns_false(
        self, db_session: Session,
    ) -> None:
        """Delete nonexistent session returns False."""
        assert delete_session(db_session, "nonexistent") is False


class TestReferenceRepo:
    def test_save_and_get(self, db_session: Session) -> None:
        """Save and retrieve references."""
        _make_session(db_session, "sess_ref")
        refs = [
            ReferenceDB(session_id="sess_ref", ref_number=1, title="Paper A"),
            ReferenceDB(session_id="sess_ref", ref_number=2, title="Paper B"),
        ]
        save_references(db_session, "sess_ref", refs)
        loaded, total = get_references(db_session, "sess_ref")
        assert total == 2
        assert loaded[0].title == "Paper A"

    def test_get_with_status_filter(self, db_session: Session) -> None:
        """Filter references by status."""
        _make_session(db_session, "sess_filt")
        refs = [
            ReferenceDB(session_id="sess_filt", ref_number=1,
                         source_status="found"),
            ReferenceDB(session_id="sess_filt", ref_number=2,
                         source_status="not_found"),
        ]
        save_references(db_session, "sess_filt", refs)
        found, total = get_references(
            db_session, "sess_filt", status="found",
        )
        assert total == 1
        assert found[0].source_status == "found"

    def test_get_single_reference(self, db_session: Session) -> None:
        """Get a single reference by number."""
        _make_session(db_session, "sess_single")
        save_references(db_session, "sess_single", [
            ReferenceDB(session_id="sess_single", ref_number=5,
                         title="Target"),
        ])
        ref = get_reference(db_session, "sess_single", 5)
        assert ref is not None
        assert ref.title == "Target"

    def test_update_reference(self, db_session: Session) -> None:
        """Update a reference's fields."""
        _make_session(db_session, "sess_upd_ref")
        save_references(db_session, "sess_upd_ref", [
            ReferenceDB(session_id="sess_upd_ref", ref_number=1,
                         title="Old"),
        ])
        updated = update_reference(
            db_session, "sess_upd_ref", 1, title="New Title",
        )
        assert updated is not None
        assert updated.title == "New Title"

    def test_pagination(self, db_session: Session) -> None:
        """Pagination returns correct subsets."""
        _make_session(db_session, "sess_page")
        refs = [
            ReferenceDB(session_id="sess_page", ref_number=i)
            for i in range(1, 6)
        ]
        save_references(db_session, "sess_page", refs)
        page1, total = get_references(
            db_session, "sess_page", page=1, per_page=2,
        )
        assert total == 5
        assert len(page1) == 2


class TestClaimRepo:
    def test_save_and_get(self, db_session: Session) -> None:
        """Save and retrieve claims."""
        _make_session(db_session, "sess_clm")
        claims = [
            ClaimDB(session_id="sess_clm", claim_number=1,
                     extracted_claim="Claim A"),
            ClaimDB(session_id="sess_clm", claim_number=2,
                     extracted_claim="Claim B"),
        ]
        save_claims(db_session, "sess_clm", claims)
        loaded = get_claims(db_session, "sess_clm")
        assert len(loaded) == 2

    def test_update_claim(self, db_session: Session) -> None:
        """Update a claim."""
        _make_session(db_session, "sess_clm_upd")
        save_claims(db_session, "sess_clm_upd", [
            ClaimDB(session_id="sess_clm_upd", claim_number=1),
        ])
        updated = update_claim(
            db_session, "sess_clm_upd", 1,
            extracted_claim="Updated",
        )
        assert updated is not None
        assert updated.extracted_claim == "Updated"

    def test_delete_claim(self, db_session: Session) -> None:
        """Delete a claim."""
        _make_session(db_session, "sess_clm_del")
        save_claims(db_session, "sess_clm_del", [
            ClaimDB(session_id="sess_clm_del", claim_number=1),
            ClaimDB(session_id="sess_clm_del", claim_number=2),
        ])
        result = delete_claim(db_session, "sess_clm_del", 1)
        assert result is True
        remaining = get_claims(db_session, "sess_clm_del")
        assert len(remaining) == 1


class TestVerificationRepo:
    def test_save_and_get(self, db_session: Session) -> None:
        """Save and retrieve verifications."""
        _make_session(db_session, "sess_ver")
        vs = [
            VerificationDB(
                session_id="sess_ver", claim_id=1, reference_id=1,
                verdict="supported", confidence=0.9,
            ),
            VerificationDB(
                session_id="sess_ver", claim_id=2, reference_id=2,
                verdict="contradicted", confidence=0.8,
            ),
        ]
        save_verifications(db_session, "sess_ver", vs)
        loaded = get_all_verifications(db_session, "sess_ver")
        assert len(loaded) == 2

    def test_update_verification(self, db_session: Session) -> None:
        """Update a verification."""
        _make_session(db_session, "sess_ver_upd")
        save_verifications(db_session, "sess_ver_upd", [
            VerificationDB(
                session_id="sess_ver_upd", claim_id=1, reference_id=1,
                verdict="cannot_verify",
            ),
        ])
        updated = update_verification(
            db_session, "sess_ver_upd", 1,
            verdict="supported", user_override=True,
        )
        assert updated is not None
        assert updated.verdict == "supported"
        assert updated.user_override is True
