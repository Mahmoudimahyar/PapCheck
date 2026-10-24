"""Database engine setup and initialization."""

import logging
import os
import sqlite3
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

logger = logging.getLogger(__name__)

_DB_PATH_STR = os.getenv(
    "REFCHECK_DB_PATH",
    str(Path.home() / ".refcheck" / "refcheck.db"),
)
DB_PATH = Path(_DB_PATH_STR)

_engine_instance: object = None

# V5 cascade columns. Each carries a DEFAULT so rows written before the
# migration read back as valid values instead of NULL.
V5_MIGRATIONS: list[tuple[str, str, str]] = [
    ("references", "identity_status", "VARCHAR DEFAULT 'unverified'"),
    ("claims", "co_cited_count", "INTEGER DEFAULT 1"),
    ("verifications", "votes_json", "VARCHAR"),
    ("verifications", "consensus_type", "VARCHAR DEFAULT ''"),
    ("verifications", "final_tier", "INTEGER DEFAULT 0"),
    ("verifications", "escalation_path_json", "VARCHAR DEFAULT '[]'"),
    ("verifications", "total_models_consulted", "INTEGER DEFAULT 0"),
    ("verifications", "agreement_ratio", "REAL DEFAULT 0.0"),
    ("verifications", "decided_by", "VARCHAR DEFAULT 'none'"),
    ("verifications", "screen_p_support", "REAL"),
    ("verifications", "screen_p_contradict", "REAL"),
    ("verifications", "screen_p_topic", "REAL"),
    ("verifications", "layer_path_json", "VARCHAR DEFAULT '[]'"),
    ("verifications", "cost_usd", "REAL DEFAULT 0.0"),
    ("verifications", "latency_ms", "INTEGER DEFAULT 0"),
    ("verifications", "quotes_validated", "BOOLEAN"),
]

# V5.2 citation signals. Without these columns the clause each reference is
# cited for, fragment / ambiguous-mapping flags and year letters were dropped
# on save, so the UI, the report and re-verification (which reload claims from
# the DB) judged and showed the whole sentence again.
V52_MIGRATIONS: list[tuple[str, str, str]] = [
    ("references", "year_suffix", "VARCHAR"),
    ("claims", "cited_for", "VARCHAR DEFAULT ''"),
    ("claims", "claim_quality", "VARCHAR DEFAULT 'ok'"),
    ("claims", "mapping_ambiguous", "BOOLEAN DEFAULT 0"),
    ("claims", "candidate_reference_ids_json", "VARCHAR DEFAULT '[]'"),
]

# V5.4 partial sub-types: why a verdict is only partial, what the author should
# do, and which benign guards cleared a concern on a supported result.
V54_MIGRATIONS: list[tuple[str, str, str]] = [
    ("verifications", "partial_type", "VARCHAR"),
    ("verifications", "partial_severity", "VARCHAR"),
    ("verifications", "author_action", "VARCHAR DEFAULT ''"),
    ("verifications", "unsupported_elements_json", "VARCHAR DEFAULT '[]'"),
    ("verifications", "guards_applied_json", "VARCHAR DEFAULT '[]'"),
]

# Free-full-text hint of a reference (OpenAlex open_access, models/open_access.py).
# NULL = not looked up (the reference had a usable full text, or the lookup failed).
OA_HINT_MIGRATIONS: list[tuple[str, str, str]] = [
    ("references", "oa_status", "VARCHAR"),
    ("references", "oa_url", "VARCHAR"),
    ("references", "oa_pdf_url", "VARCHAR"),
    ("references", "oa_license", "VARCHAR"),
    ("references", "oa_version", "VARCHAR"),
]


def get_engine() -> object:
    """Get or create the SQLite engine (singleton)."""
    global _engine_instance  # noqa: PLW0603
    if _engine_instance is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine_instance = create_engine(
            f"sqlite:///{DB_PATH}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        logger.info("Database engine created: %s", DB_PATH)
    return _engine_instance


def set_engine(engine: object) -> None:
    """Override the engine (for testing with in-memory SQLite)."""
    global _engine_instance  # noqa: PLW0603
    _engine_instance = engine


def _migrate_add_columns(db_path: Path) -> None:
    """Add columns introduced after initial schema (safe for fresh DBs)."""
    if not db_path.exists():
        return
    migrations: list[tuple[str, str, str]] = [
        ("claims", "location_json", "VARCHAR"),
        ("verifications", "evidence_sections_json", "VARCHAR"),
        ("sessions", "manuscript_sections_json", "VARCHAR"),
        # V2 reference fields
        ("references", "raw_text_original", "VARCHAR"),
        ("references", "repair_applied", "VARCHAR"),
        ("references", "reference_type", "VARCHAR"),
        ("references", "abstract_text", "VARCHAR"),
        ("references", "abstract_source", "VARCHAR"),
        ("references", "pmc_id", "VARCHAR"),
        # V2 claim fields
        ("claims", "paragraph_text", "VARCHAR"),
        # V2 verification fields
        ("verifications", "model_reasoning_json", "VARCHAR"),
        ("verifications", "cannot_verify_reason", "VARCHAR"),
        ("verifications", "section_relevance", "VARCHAR"),
        ("verifications", "text_quality_score", "REAL"),
        # V2 retry workflow fields
        ("verifications", "retry_strategy_used", "VARCHAR"),
        ("verifications", "retry_attempts", "INTEGER"),
        *V5_MIGRATIONS,
        *V52_MIGRATIONS,
        *V54_MIGRATIONS,
        # V5.8 G3: why an uploaded PDF was replaced from the library / open access
        ("references", "replaced_upload_reason", "VARCHAR"),
        *OA_HINT_MIGRATIONS,
    ]
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        for table, column, col_type in migrations:
            cursor.execute(f'PRAGMA table_info("{table}")')
            existing = {row[1] for row in cursor.fetchall()}
            if column not in existing:
                cursor.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN {column} {col_type}'
                )
                logger.info("Migrated: added %s.%s", table, column)
        conn.commit()
    finally:
        conn.close()


def init_db() -> object:
    """Create all database tables and return the engine."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)  # type: ignore[arg-type]
    _migrate_add_columns(DB_PATH)
    logger.info("Database tables initialized")
    return engine


def get_db_session() -> Session:
    """Create a new database session (non-generator, for background tasks)."""
    engine = get_engine()
    return Session(engine)  # type: ignore[arg-type]
