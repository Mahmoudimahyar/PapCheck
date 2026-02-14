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
    ]
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        for table, column, col_type in migrations:
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cursor.fetchall()}
            if column not in existing:
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
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
