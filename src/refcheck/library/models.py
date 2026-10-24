"""SQLModel table for the reference library."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class LibraryPaper(SQLModel, table=True):
    """A paper stored in the local reference library."""

    __tablename__ = "library_papers"

    id: int | None = Field(default=None, primary_key=True)
    doi: str | None = Field(default=None, index=True)
    pmid: str | None = Field(default=None, index=True)
    title: str = ""
    authors_json: str = "[]"
    year: int | None = None
    journal: str | None = None
    pdf_path: str = ""
    pdf_hash: str = Field(default="", index=True)
    text_extracted: bool = False
    text_path: str | None = None
    source: str = ""
    added_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    source_session_id: str | None = None
