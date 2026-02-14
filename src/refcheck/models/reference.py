"""Reference and parsed manuscript data models."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class InTextCitation(BaseModel):
    """A citation marker found in the manuscript body text."""

    raw_text: str = Field(description="Original citation text, e.g. '[1-3, 5]'")
    position: int = Field(description="Character offset in section text")
    reference_ids: list[int] = Field(
        default_factory=list,
        description="Mapped reference IDs (empty if unmapped)",
    )


class ManuscriptSection(BaseModel):
    """A section of the manuscript text."""

    heading: str | None = None
    text: str = ""
    citations: list[InTextCitation] = Field(default_factory=list)


class Reference(BaseModel):
    """A single bibliographic reference from the manuscript."""

    id: int
    raw_text: str = ""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    pmid: str | None = None
    volume: str | None = None
    pages: str | None = None
    url: str | None = None

    # Status fields populated as pipeline progresses
    source_status: Literal[
        "pending", "found", "not_found", "api_error"
    ] = "pending"
    pdf_path: Path | None = None
    pdf_source: Literal[
        "user_upload", "open_access", "library", "not_available"
    ] | None = None
    journal_url: str | None = None

    # Duplicate detection (populated by parse_docx stage)
    duplicate_of: int | None = None
    is_supplementary: bool = False

    # Retraction status (populated by retraction checking stage)
    retraction_status: Literal[
        "ok", "retracted", "corrected", "expression_of_concern", "unknown"
    ] = "unknown"
    retraction_detail: str = ""


class ParsedManuscript(BaseModel):
    """Result of DOCX parsing."""

    filename: str
    sections: list[ManuscriptSection] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    citation_style: Literal[
        "numbered", "author_year", "footnote", "unknown"
    ] = "unknown"
    has_field_codes: bool = False
    warnings: list[str] = Field(default_factory=list)
