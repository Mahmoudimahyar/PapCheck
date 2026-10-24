"""V5.2 persistence: cited_for, claim_quality, ambiguous mappings and year letters.

Regression for the V4.9 review: the parser and citation detector learned to
narrow each reference to the clause it is cited for (M2), flag incomplete
sentences (M11), flag ambiguous author-year mappings and keep "2018b" year
letters (M4), but the DB had no columns for them. Everything read back from
the DB (results API, report regeneration, re-verification after a PDF upload)
silently reverted to whole-sentence checking with no warnings. The exhaustive
round trips below fail for ANY model field that is not persisted.
"""

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.db.claim_repo import get_claims
from refcheck.db.converters import claim_to_db, db_to_claim, db_to_reference, reference_to_db
from refcheck.db.engine import V52_MIGRATIONS, _migrate_add_columns
from refcheck.db.models import ClaimDB, ReferenceDB
from refcheck.db.reference_repo import get_all_references
from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation
from refcheck.models.reference import Reference
from refcheck.services import persist

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo


def _full_claim() -> Claim:
    """A claim with EVERY field set to a non-default value."""
    return Claim(
        id=7, manuscript_text="Gels reduce IL-6 (Doe, 2018b) and resorb fast (Wang et al., 2024).",
        extracted_claim="Gels reduce IL-6 and resorb fast.", paragraph_text="Intro. Gels ...",
        claim_type="methodological", reference_ids=[105], priority="high",
        section_heading="Background", atomic_claims=["Gels reduce IL-6"],
        location=ClaimLocation(paragraph_index=3, char_start=10, char_end=60,
                               citation_markers=["(Wang et al., 2024)"],
                               section_heading="Background"),
        co_cited_count=2, cited_for="resorb fast", claim_quality="fragment",
        mapping_ambiguous=True, candidate_reference_ids=[105, 106, 107],
    )


def _full_reference() -> Reference:
    """A reference with EVERY field set to a non-default value."""
    return Reference(
        id=30, raw_text="Doe, J. (2018b). Title. J 1, 2.", title="Hydrogel title",
        authors=["Doe, J."], year=2018, year_suffix="b", doi="10.1/x", journal="J",
        pmid="123", pmc_id="PMC1", volume="1", pages="2", url="https://x.org",
        source_status="found", pdf_path=Path("pdfs/doe2018b.pdf"), pdf_source="user_upload",
        journal_url="https://j.org", raw_text_original="orig", repair_applied="title_from_api",
        reference_type="book_chapter", abstract_text="Abstract.", abstract_source="crossref",
        identity_status="mismatch", duplicate_of=29, is_supplementary=True,
        replaced_upload_reason="scanned",
        retraction_status="retracted", retraction_detail="Retracted 2025",
    )


def _assert_all_fields_set(model: Claim | Reference) -> None:
    fields: dict[str, FieldInfo] = type(model).model_fields
    for name, info in fields.items():
        default = info.get_default(call_default_factory=True)
        assert getattr(model, name) != default, (
            f"{type(model).__name__}.{name} has its default in the fixture: set it and "
            "persist it (db/models.py, db/engine.py migration, db/converters.py)")


def _engine() -> object:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


class TestEveryFieldIsPersisted:
    def test_claim_round_trip_keeps_every_field(self) -> None:
        claim = _full_claim()
        _assert_all_fields_set(claim)
        assert db_to_claim(claim_to_db(claim, "s")) == claim

    def test_reference_round_trip_keeps_every_field(self) -> None:
        ref = _full_reference()
        _assert_all_fields_set(ref)
        assert db_to_reference(reference_to_db(ref, "s")) == ref

    def test_persist_services_write_the_new_fields_to_sqlite(self) -> None:
        engine = _engine()
        with patch.object(persist, "get_db_session", lambda: Session(engine)):  # type: ignore[arg-type]
            persist.persist_claims("s", [_full_claim()])
            persist.persist_references("s", [_full_reference()])
        with Session(engine) as db:  # type: ignore[arg-type]
            assert [db_to_claim(c) for c in get_claims(db, "s")] == [_full_claim()]
            assert [db_to_reference(r) for r in get_all_references(db, "s")] == [
                _full_reference()]


class TestLegacyRows:
    def test_null_v52_claim_columns_read_as_defaults(self) -> None:
        row = ClaimDB(session_id="s", claim_number=1, extracted_claim="c")
        for column in ("cited_for", "claim_quality", "mapping_ambiguous",
                       "candidate_reference_ids_json"):
            setattr(row, column, None)
        claim = db_to_claim(row)
        assert claim.cited_for == "" and claim.claim_quality == "ok"
        assert claim.mapping_ambiguous is False and claim.candidate_reference_ids == []

    def test_unknown_quality_and_corrupt_candidates(self) -> None:
        row = claim_to_db(Claim(id=1), "s")
        row.claim_quality = "bogus"
        row.candidate_reference_ids_json = "{not json"
        claim = db_to_claim(row)
        assert claim.claim_quality == "ok" and claim.candidate_reference_ids == []

    def test_empty_year_suffix_reads_as_none(self) -> None:
        row = ReferenceDB(session_id="s", ref_number=1, year_suffix="")
        assert db_to_reference(row).year_suffix is None


class TestMigrations:
    def test_adds_v52_columns_with_defaults(self, tmp_path: Path) -> None:
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
            INSERT INTO claims (session_id, claim_number) VALUES ('s', 1);
            INSERT INTO "references" (session_id, ref_number) VALUES ('s', 1);
        """)
        conn.commit()
        conn.close()
        _migrate_add_columns(db_path)
        _migrate_add_columns(db_path)  # idempotent
        conn = sqlite3.connect(str(db_path))
        try:
            for table, column, _ in V52_MIGRATIONS:
                cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
                assert column in cols, f"{table}.{column}"
            row = conn.execute("SELECT cited_for, claim_quality, mapping_ambiguous, "
                               "candidate_reference_ids_json FROM claims").fetchone()
            assert row == ("", "ok", 0, "[]")
            assert conn.execute('SELECT year_suffix FROM "references"').fetchone() == (None,)
        finally:
            conn.close()

    def test_migrations_match_model_columns(self) -> None:
        tables = {"claims": ClaimDB, "references": ReferenceDB}
        for table, column, _ in V52_MIGRATIONS:
            assert column in tables[table].model_fields, f"{table}.{column}"
