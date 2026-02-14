"""Pydantic schemas for the manuscript viewer API endpoints."""

from pydantic import BaseModel, Field

from refcheck.models.evidence import ClaimLocation, EvidenceSection


class ParagraphClaim(BaseModel):
    """A claim positioned within a paragraph for the viewer."""

    claim_id: int
    char_start: int
    char_end: int
    citation_markers: list[str] = Field(default_factory=list)
    verdict: str = "pending"
    confidence: float = 0.0
    reference_ids: list[int] = Field(default_factory=list)


class ManuscriptParagraph(BaseModel):
    """A single paragraph with its positioned claims."""

    index: int
    text: str
    section_heading: str = ""
    claims: list[ParagraphClaim] = Field(default_factory=list)


class ManuscriptResponse(BaseModel):
    """Full manuscript structured for the viewer."""

    title: str = ""
    paragraphs: list[ManuscriptParagraph] = Field(default_factory=list)
    legend: dict[str, int] = Field(default_factory=dict)
    total_claims: int = 0
    total_paragraphs: int = 0
    unmapped_claims: list[int] = Field(default_factory=list)


class ClaimDetailResponse(BaseModel):
    """Full claim details for the evidence panel."""

    id: int
    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: str = ""
    priority: str = ""
    atomic_claims: list[str] = Field(default_factory=list)
    location: ClaimLocation | None = None


class VerificationEvidence(BaseModel):
    """Verification evidence for a single reference."""

    reference_id: int
    reference_title: str = ""
    reference_authors: list[str] = Field(default_factory=list)
    verdict: str = "cannot_verify"
    confidence: float = 0.0
    tier: int = 1
    reasoning: str = ""
    evidence_sections: list[EvidenceSection] = Field(default_factory=list)
    atomic_results: list[dict[str, object]] | None = None
    user_override: bool = False
    user_override_reason: str = ""


class EvidenceResponse(BaseModel):
    """Full evidence for a specific claim."""

    claim: ClaimDetailResponse
    verifications: list[VerificationEvidence] = Field(default_factory=list)
