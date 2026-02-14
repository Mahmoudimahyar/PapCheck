"""FastAPI dependency for database session injection."""

from collections.abc import Generator

from sqlmodel import Session

from refcheck.db.engine import get_engine


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for a single request lifecycle."""
    engine = get_engine()
    with Session(engine) as session:  # type: ignore[arg-type]
        yield session
