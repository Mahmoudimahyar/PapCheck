"""V5.4 persistence: partial sub-type, severity, author action, unsupported elements, guards.

Without these columns every result read back from the DB (results API, report
regeneration, re-verification) lost why a verdict was partial and which benign
guard cleared a supported one. The exhaustive round trip fails for ANY
VerificationResult field that is not persisted. Synthetic data only.
"""

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from refcheck.db.converters import db_to_verification, verification_to_db
from refcheck.db.engine import V54_MIGRATIONS, _migrate_add_columns
from refcheck.db.models import VerificationDB
from refcheck.models.evidence import EvidenceSection
from refcheck.models.verification import (
    AtomicVerification,
    ModelReasoning,
    VerificationResult,
    VoteRecord,
)

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo


def _full_result() -> VerificationResult:
    """A result with EVERY field set to a non-default value."""
    return VerificationResult(
        claim_id=3, reference_id=7, verdict="partially_supported", confidence=0.7,
        evidence_quotes=["Gel A lowered marker X in mice."], reasoning="Mouse data only.",
        tier=2, source_coverage="full_text", needs_user_review=True,
        atomic_results=[AtomicVerification(atom="Gel A lowers X", verified=True)],
        user_override=True, user_override_reason="checked", original_verdict="not_supported",
        original_confidence=0.4,
        evidence_sections=[EvidenceSection(section_heading="[P1] Results", full_text="t")],
        votes=[VoteRecord(model_name="m", abbreviation="V", tier=2, verdict="partially_supported",
                          confidence=0.7)],
        consensus_type="confirmed", final_tier=2, escalation_path=[1, 2],
        total_models_consulted=2, agreement_ratio=1.0,
        model_reasoning=[ModelReasoning(model_name="m", verdict="partially_supported")],
        cannot_verify_reason="llm_error", section_relevance="low", text_quality_score=0.5,
        retry_strategy_used="expand", retry_attempts=1,
        decided_by="verifier", screen_p_support=0.4, screen_p_contradict=0.1, screen_p_topic=0.9,
        layer_path=["screen", "verifier"], cost_usd=0.01, latency_ms=900, quotes_validated=True,
        partial_type="scope_overgeneralized", partial_severity="major",
        author_action="Narrow the wording to the source's population ('in humans').",
        unsupported_elements=["in humans", "all gels"],
        guards_applied=["cocited_share", "overliteral_wording"],
    )


def _sqlite_round_trip(result: VerificationResult) -> VerificationResult:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(verification_to_db(result, "s"))
        db.commit()
    with Session(engine) as db:
        return db_to_verification(db.exec(select(VerificationDB)).one())


class TestEveryFieldIsPersisted:
    def test_fixture_sets_every_field(self) -> None:
        result = _full_result()
        fields: dict[str, FieldInfo] = VerificationResult.model_fields
        for name, info in fields.items():
            assert getattr(result, name) != info.get_default(call_default_factory=True), (
                f"VerificationResult.{name} has its default in the fixture: set it and persist "
                "it (db/models.py, db/engine.py migration, db/verification_converters.py)")

    def test_round_trip_keeps_every_field(self) -> None:
        assert db_to_verification(verification_to_db(_full_result(), "s")) == _full_result()

    def test_round_trip_through_sqlite(self) -> None:
        assert _sqlite_round_trip(_full_result()) == _full_result()

    def test_defaults_round_trip(self) -> None:
        minimal = VerificationResult(claim_id=1, reference_id=1)
        assert _sqlite_round_trip(minimal) == minimal


class TestLegacyRows:
    def test_null_v54_columns_read_as_defaults(self) -> None:
        row = VerificationDB(session_id="s", claim_id=1, reference_id=2,
                             verdict="partially_supported")
        for column in ("partial_type", "partial_severity", "author_action",
                       "unsupported_elements_json", "guards_applied_json"):
            setattr(row, column, None)
        result = db_to_verification(row)
        assert result.partial_type is None and result.partial_severity is None
        assert result.author_action == "" and result.unsupported_elements == []
        assert result.guards_applied == []

    def test_bad_values_are_dropped(self) -> None:
        row = verification_to_db(VerificationResult(claim_id=1, reference_id=1), "s")
        row.partial_type = "none"
        row.partial_severity = "catastrophic"
        row.unsupported_elements_json = "{not json"
        row.guards_applied_json = '["cocited_share", 3]'
        result = db_to_verification(row)
        assert result.partial_type is None and result.partial_severity is None
        assert result.unsupported_elements == [] and result.guards_applied == ["cocited_share"]


class TestMigrations:
    def test_adds_v54_columns_with_defaults(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE "references" (id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL,
                ref_number INTEGER NOT NULL);
            CREATE TABLE claims (id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL,
                claim_number INTEGER NOT NULL);
            CREATE TABLE verifications (id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL,
                claim_id INTEGER NOT NULL, reference_id INTEGER NOT NULL);
            CREATE TABLE sessions (id VARCHAR PRIMARY KEY);
            INSERT INTO verifications (session_id, claim_id, reference_id) VALUES ('s', 1, 1);
        """)
        conn.commit()
        conn.close()
        _migrate_add_columns(db_path)
        _migrate_add_columns(db_path)  # idempotent
        conn = sqlite3.connect(str(db_path))
        try:
            cols = {r[1] for r in conn.execute('PRAGMA table_info("verifications")')}
            assert {column for _, column, _ in V54_MIGRATIONS} <= cols
            row = conn.execute("SELECT partial_type, partial_severity, author_action, "
                               "unsupported_elements_json, guards_applied_json "
                               "FROM verifications").fetchone()
            assert row == (None, None, "", "[]", "[]")
        finally:
            conn.close()

    def test_migrations_match_model_columns(self) -> None:
        for table, column, _ in V54_MIGRATIONS:
            assert table == "verifications" and column in VerificationDB.model_fields, column
