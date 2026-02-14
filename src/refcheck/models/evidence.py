"""Evidence mapping data models for manuscript viewer (V2)."""

from typing import Literal

from pydantic import BaseModel, Field


class ClaimLocation(BaseModel):
    """Where a claim lives in the manuscript text."""

    paragraph_index: int = Field(ge=0, description="0-based paragraph index")
    char_start: int = Field(ge=0, description="Character offset start")
    char_end: int = Field(ge=0, description="Character offset end")
    citation_markers: list[str] = Field(default_factory=list)
    section_heading: str = ""
    in_figure_or_table: bool = False


class QuoteHighlight(BaseModel):
    """A specific evidence quote positioned within a source section."""

    quote: str = ""
    char_start: int = Field(ge=0, default=0)
    char_end: int = Field(ge=0, default=0)
    match_type: Literal[
        "direct", "paraphrased", "numeric_mismatch", "absent"
    ] = "direct"
    manuscript_element: str = ""


class EvidenceSection(BaseModel):
    """A section from the cited article containing evidence."""

    section_heading: str = ""
    full_text: str = ""
    page_number: int | None = None
    quote_highlights: list[QuoteHighlight] = Field(default_factory=list)
