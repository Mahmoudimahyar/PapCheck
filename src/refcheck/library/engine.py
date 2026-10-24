"""Library database engine setup (separate from main app DB)."""

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

logger = logging.getLogger(__name__)

LIBRARY_DB_PATH = Path(
    os.getenv("REFCHECK_LIBRARY_DB", str(Path.home() / ".refcheck" / "library.db"))
)
LIBRARY_PDF_DIR = Path(
    os.getenv("REFCHECK_LIBRARY_DIR", str(Path.home() / ".refcheck" / "library" / "pdfs"))
)

_engine: object = None


def get_library_engine() -> object:
    """Get or create the library SQLite engine (singleton)."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        LIBRARY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIBRARY_PDF_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{LIBRARY_DB_PATH}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(_engine)
        logger.info("Library DB initialized: %s", LIBRARY_DB_PATH)
    return _engine


def set_library_engine(engine: object) -> None:
    """Override the engine (for testing with in-memory SQLite)."""
    global _engine  # noqa: PLW0603
    _engine = engine


def get_library_session() -> Generator[Session, None, None]:
    """Yield a library database session."""
    engine = get_library_engine()
    with Session(engine) as session:  # type: ignore[arg-type]
        yield session
