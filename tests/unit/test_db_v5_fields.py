"""V5 persistence: new columns, round trips, migrations and NULL-safe reads."""

import sqlite3
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from refcheck.db.converters import (
    claim_to_db,
    db_to_claim,
    db_to_reference,
    db_to_verification,
    reference_to_db,
    verification_to_db,
)
from refcheck.db.engine import V5_MIGRATIONS, _migrate_add_columns
from refcheck.db.models import ClaimDB, ReferenceDB, VerificationDB
from refcheck.db.verification_converters import load_json_list
from refcheck.models.claim import Claim
from refcheck.models.evidence import EvidenceSection
from refcheck.models.reference import Reference
from refcheck.models.verification import (
    AtomicVerification,
    ModelReasoning,
    VerificationResult,
    VoteRecord,
)


def _v5_result() -> VerificationResult:
    return VerificationResult(
        claim_id=3, reference_id=7, verdict="contradicted", confidence=0.7,
        evidence_quotes=["X did not reduce Y."], reasoning="Judge: opposite finding.",
        tier=3, source_coverage="full_text", needs_user_review=True,
        atomic_results=[AtomicVerification(atom="X reduces Y", verified=False)],
        evidence_sections=[EvidenceSection(section_heading="[P1] Results, p.4",
                                           full_text="X did not reduce Y.", page_number=4)],
        votes=[VoteRecord(model_name="Decisions API · gpt-6-luna", abbreviation="S", tier=1,
                          verdict="escalate", confidence=0.2),
               VoteRecord(model_name="gpt-6-luna", abbreviation="V", tier=2,
                          verdict="not_supported", confidence=0.8)],
        consensus_type="judge", final_tier=3, escalation_path=[1, 2, 3],
        total_models_consulted=3, agreement_ratio=1.0,
        model_reasoning=[ModelReasoning(model_name="gpt-6-luna-decisions",
                                        model_display="Decisions API · gpt-6-luna",
                                        verdict="possible_problem", confidence=0.2,
                                        reasoning="P(support)=0.200")],
        cannot_verify_reason=None, section_relevance="high", text_quality_score=0.9,
        decided_by="judge", screen_p_support=0.2, screen_p_contradict=0.75,
        screen_p_topic=0.95, layer_path=["screen", "verifier", "judge"],
        cost_usd=0.0136, latency_ms=6700, quotes_validated=True,
    )


class TestVerificationRoundTrip:
    def test_all_v5_fields_survive(self) -> None:
        original = _v5_result()
        row = verification_to_db(original, "sess")
        assert row.decided_by == "judge" and row.layer_path_json is not None
        assert db_to_verification(row) == original

    def test_round_trip_through_sqlite(self) -> None:
        engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(verification_to_db(_v5_result(), "sess"))
            db.commit()
        with Session(engine) as db:
            row = db.exec(select(VerificationDB)).one()
            restored = db_to_verification(row)
        assert restored == _v5_result()

    def test_defaults_round_trip(self) -> None:
        minimal = VerificationResult(claim_id=1, reference_id=1)
        restored = db_to_verification(verification_to_db(minimal, "s"))
        assert restored == minimal
        assert restored.decided_by == "none" and restored.quotes_validated is None


class TestReferenceAndClaimFields:
    def test_identity_status_round_trip(self) -> None:
        ref = Reference(id=2, title="T", identity_status="mismatch")
        assert db_to_reference(reference_to_db(ref, "s")).identity_status == "mismatch"

    def test_unknown_identity_status_reads_as_unverified(self) -> None:
        row = reference_to_db(Reference(id=2), "s")
        row.identity_status = "bogus"
        assert db_to_reference(row).identity_status == "unverified"

    def test_co_cited_count_round_trip(self) -> None:
        claim = Claim(id=4, extracted_claim="c", co_cited_count=3)
        assert db_to_claim(claim_to_db(claim, "s")).co_cited_count == 3


class TestLegacyRows:
    """Rows written before a migration have NULL in the added columns."""

    def test_null_v2_and_v5_verification_columns(self) -> None:
        row = VerificationDB(session_id="s", claim_id=1, reference_id=2, verdict="supported",
                             confidence=0.9)
        for column in ("section_relevance", "text_quality_score", "retry_attempts",
                       "decided_by", "consensus_type", "final_tier", "escalation_path_json",
                       "total_models_consulted", "agreement_ratio", "layer_path_json",
                       "cost_usd", "latency_ms"):
            setattr(row, column, None)
        result = db_to_verification(row)
        assert result.section_relevance == "high" and result.text_quality_score == 1.0
        assert result.decided_by == "none" and result.layer_path == []
        assert result.escalation_path == [] and result.cost_usd == 0.0

    def test_null_reference_and_claim_columns(self) -> None:
        ref_row = ReferenceDB(session_id="s", ref_number=1)
        for column in ("raw_text_original", "repair_applied", "reference_type",
                       "identity_status"):
            setattr(ref_row, column, None)
        ref = db_to_reference(ref_row)
        assert ref.repair_applied == "none" and ref.identity_status == "unverified"
        claim_row = ClaimDB(session_id="s", claim_number=1)
        claim_row.paragraph_text = None  # type: ignore[assignment]
        claim_row.co_cited_count = None  # type: ignore[assignment]
        claim = db_to_claim(claim_row)
        assert claim.paragraph_text == "" and claim.co_cited_count == 1

    def test_unknown_decided_by_and_corrupt_json(self) -> None:
        row = verification_to_db(VerificationResult(claim_id=1, reference_id=1), "s")
        row.decided_by = "oracle"
        row.layer_path_json = "{not json"
        result = db_to_verification(row)
        assert result.decided_by == "none" and result.layer_path == []
        assert load_json_list('{"a": 1}') == []


def _old_schema_db(path: Path) -> None:
    """A database as written by the pre-V5 schema (no V5 columns)."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE "references" (id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL,
            ref_number INTEGER NOT NULL);
        CREATE TABLE claims (id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL,
            claim_number INTEGER NOT NULL);
        CREATE TABLE verifications (id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL,
            claim_id INTEGER NOT NULL, reference_id INTEGER NOT NULL);
        CREATE TABLE sessions (id VARCHAR PRIMARY KEY);
        INSERT INTO verifications (session_id, claim_id, reference_id) VALUES ('s', 1, 1);
        INSERT INTO claims (session_id, claim_number) VALUES ('s', 1);
        INSERT INTO "references" (session_id, ref_number) VALUES ('s', 1);
    """)
    conn.commit()
    conn.close()


class TestMigrations:
    def test_adds_v5_columns_with_defaults(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old.db"
        _old_schema_db(db_path)
        _migrate_add_columns(db_path)
        _migrate_add_columns(db_path)  # idempotent
        conn = sqlite3.connect(str(db_path))
        try:
            for table, column, _ in V5_MIGRATIONS:
                cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
                assert column in cols, f"{table}.{column}"
            row = conn.execute("SELECT decided_by, layer_path_json, cost_usd, final_tier, "
                               "escalation_path_json FROM verifications").fetchone()
            assert row == ("none", "[]", 0.0, 0, "[]")
            assert conn.execute("SELECT co_cited_count FROM claims").fetchone() == (1,)
            assert conn.execute('SELECT identity_status FROM "references"').fetchone() \
                == ("unverified",)
        finally:
            conn.close()

    def test_migrations_match_model_columns(self) -> None:
        tables = {"verifications": VerificationDB, "claims": ClaimDB,
                  "references": ReferenceDB}
        for table, column, _ in V5_MIGRATIONS:
            assert column in tables[table].model_fields, f"{table}.{column}"
