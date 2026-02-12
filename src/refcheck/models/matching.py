"""PDF-to-reference match result data models."""

from typing import Literal

from pydantic import BaseModel, Field


class MatchResult(BaseModel):
    """Result of matching a PDF to a manuscript reference."""

    reference_id: int
    pdf_path: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, description="Match confidence 0-1")
    match_method: Literal[
        "doi",
        "title_fuzzy",
        "doi_crossref_title",
        "grobid_structured",
        "llm_firstpage",
        "user_confirmed",
        "unmatched",
    ] = "unmatched"
    needs_user_confirmation: bool = False
    candidate_alternatives: list[str] = Field(default_factory=list)
