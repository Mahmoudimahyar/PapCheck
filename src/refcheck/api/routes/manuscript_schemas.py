"""Pydantic schemas for the manuscript viewer API endpoints."""

from pydantic import BaseModel, Field

from refcheck.api.routes.results_schemas import PartialFields
from refcheck.models.evidence import ClaimLocation, EvidenceSection
from refcheck.stages.generate_report.claim_signals import ClaimSignals
from refcheck.stages.generate_report.result_signals import ResultSignals


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
    # V5.2: cited-for clause, fragment and ambiguous-mapping warnings
    signals: ClaimSignals = Field(default_factory=ClaimSignals)


class ModelReasoningResponse(BaseModel):
    """Single model's reasoning detail (V2)."""

    model_name: str = ""
    model_display: str = ""
    verdict: str = "cannot_verify"
    confidence: float = 0.0
    reasoning: str = ""
    evidence_quotes: list[str] = Field(default_factory=list)
    source_section_preview: str = ""
    response_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class VerificationEvidence(PartialFields):
    """Verification evidence for a single reference (V5.4 fields from PartialFields)."""

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
    # V2 fields
    model_reasoning: list[ModelReasoningResponse] = Field(
        default_factory=list,
    )
    cannot_verify_reason: str | None = None
    source_coverage: str = "no_source"
    section_relevance: str = "high"
    text_quality_score: float = 1.0
    signals: ResultSignals = Field(default_factory=ResultSignals)  # V5.2


class EvidenceResponse(BaseModel):
    """Full evidence for a specific claim."""

    claim: ClaimDetailResponse
    verifications: list[VerificationEvidence] = Field(default_factory=list)
