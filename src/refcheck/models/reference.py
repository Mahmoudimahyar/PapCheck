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
    # Author-year disambiguation letter: "(2018b)" -> year=2018, year_suffix="b".
    # Citations "(Smith, 2018b)" must map to the reference with the same letter.
    year_suffix: str | None = None
    doi: str | None = None
    journal: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
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

    # V2: Reference repair tracking
    raw_text_original: str = ""
    repair_applied: str = "none"
    reference_type: str = "journal_article"

    # V2: Abstract fallback
    abstract_text: str | None = None
    # "pubmed" | "semantic_scholar" | "europepmc" | "crossref" (API records of the
    # reference's own DOI/PMID, see API_ABSTRACT_SOURCES in verify_claims.source_fallback)
    abstract_source: str | None = None

    # V5: Does the attached PDF really belong to this reference? (resolve stage)
    # "mismatch" lets verification return cannot_verify(reference_mismatch).
    identity_status: Literal["verified", "unverified", "mismatch"] = "unverified"
    # V5.8 G3: why the uploaded PDF was replaced by a library / open-access copy
    # (match_pdfs RejectReason: "identity_mismatch", "supplement", "scanned", "no_text");
    # None when nothing uploaded was replaced. Reported as a source issue.
    replaced_upload_reason: str | None = None

    # Duplicate detection (populated by parse_docx stage): id of the earlier
    # reference this one repeats (same DOI, or same title + first author + year).
    # The reason is in ParsedManuscript.warnings; report it as a bibliography issue.
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
