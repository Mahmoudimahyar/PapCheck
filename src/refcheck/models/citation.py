"""Citation detection and verification unit data models (V4)."""

from typing import Literal

from pydantic import BaseModel, Field

CitationStyle = Literal[
    "author_year_parenthetical",
    "author_year_narrative",
    "numbered_bracket",
    "numbered_superscript",
    "numbered_paren",
]

ClaimType = Literal[
    "factual",
    "methodological",
    "background",
    "attribution",
    "contrast",
    "interpretive",
]

Priority = Literal["high", "medium", "low"]


class CitationInstance(BaseModel):
    """A single occurrence of a citation in the manuscript."""

    id: int = 0
    raw_marker: str
    style: CitationStyle

    # Location
    paragraph_index: int
    char_start: int
    char_end: int
    section_heading: str = ""

    # Parsed
    authors: list[str] = Field(default_factory=list)
    year: str | None = None
    number: int | None = None

    # Context
    sentence_text: str = ""
    sentence_start: int = 0
    sentence_end: int = 0
    is_narrative: bool = False

    # Reference mapping
    reference_id: int | None = None
    reference_title: str = ""
    mapping_confidence: float = 0.0
    mapping_method: str = ""


class VerificationUnit(BaseModel):
    """A citation instance with resolved scope, ready for verification."""

    id: int = 0

    # What to verify
    manuscript_text: str
    scope_text: str
    citation_marker: str

    # Location
    paragraph_index: int = 0
    char_start: int = 0
    char_end: int = 0
    section_heading: str = ""

    # Reference
    reference_id: int
    reference_title: str = ""
    reference_authors: list[str] = Field(default_factory=list)

    # Metadata
    citation_style: str = ""
    is_narrative: bool = False
    claim_type: ClaimType = "factual"
    priority: Priority = "medium"
    atomic_claims: list[str] = Field(default_factory=list)

    @property
    def extracted_claim(self) -> str:
        """Backward compat with Claim.extracted_claim."""
        return self.scope_text

    @property
    def reference_ids(self) -> list[int]:
        """Backward compat with Claim.reference_ids."""
        return [self.reference_id]


class MissingCitation(BaseModel):
    """A sentence that should have a citation but doesn't."""

    id: int = 0
    sentence_text: str
    paragraph_index: int
    char_start: int = 0
    char_end: int = 0
    section_heading: str = ""
    confidence: float = 0.0
    category: str = ""
    reason: str = ""
    suggestion: str = ""
