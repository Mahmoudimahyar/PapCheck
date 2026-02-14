"""Helper functions for manuscript viewer API endpoints."""

import re

from refcheck.api.routes.manuscript_schemas import (
    ManuscriptParagraph,
    ParagraphClaim,
    VerificationEvidence,
)
from refcheck.models.claim import Claim
from refcheck.models.reference import ManuscriptSection, Reference
from refcheck.models.verification import VerificationResult


def group_verifications(
    verifications: list[VerificationResult],
) -> dict[int, list[VerificationResult]]:
    """Group verifications by claim_id."""
    by_claim: dict[int, list[VerificationResult]] = {}
    for v in verifications:
        by_claim.setdefault(v.claim_id, []).append(v)
    return by_claim


def best_verdict(
    claim_id: int,
    v_by_claim: dict[int, list[VerificationResult]],
) -> str:
    """Get the most severe verdict for a claim."""
    vs = v_by_claim.get(claim_id, [])
    if not vs:
        return "pending"
    severity = {
        "contradicted": 0, "not_supported": 1,
        "partially_supported": 2, "cannot_verify": 3, "supported": 4,
    }
    return min(vs, key=lambda v: severity.get(v.verdict, 9)).verdict


def build_paragraphs_from_sections(
    sections: list[ManuscriptSection],
) -> list[ManuscriptParagraph]:
    """Flatten sections into indexed paragraphs."""
    paragraphs: list[ManuscriptParagraph] = []
    idx = 0
    for section in sections:
        heading = section.heading or ""
        for text in _split_text(section.text):
            paragraphs.append(ManuscriptParagraph(
                index=idx, text=text, section_heading=heading,
            ))
            idx += 1
    return paragraphs


def _split_text(text: str) -> list[str]:
    """Split section text into paragraphs."""
    if not text.strip():
        return []
    parts = re.split(r"\n\s*\n", text)
    result = [p.strip() for p in parts if p.strip()]
    return result if result else [text.strip()]


def attach_claims_to_paragraphs(
    paragraphs: list[ManuscriptParagraph],
    claims: list[Claim],
    v_by_claim: dict[int, list[VerificationResult]],
) -> None:
    """Attach claim markers to matching paragraphs (mutates in place)."""
    para_by_idx = {p.index: p for p in paragraphs}
    for claim in claims:
        if claim.location is None:
            continue
        para = para_by_idx.get(claim.location.paragraph_index)
        if not para:
            continue
        verdict = best_verdict(claim.id, v_by_claim)
        vs = v_by_claim.get(claim.id, [])
        confidence = max((v.confidence for v in vs), default=0.0)
        para.claims.append(ParagraphClaim(
            claim_id=claim.id,
            char_start=claim.location.char_start,
            char_end=claim.location.char_end,
            citation_markers=claim.location.citation_markers,
            verdict=verdict,
            confidence=confidence,
            reference_ids=claim.reference_ids,
        ))


def build_verification_evidences(
    claim_vs: list[VerificationResult],
    refs_by_id: dict[int, Reference],
) -> list[VerificationEvidence]:
    """Build VerificationEvidence list from verifications."""
    evidences: list[VerificationEvidence] = []
    for v in claim_vs:
        ref = refs_by_id.get(v.reference_id)
        atomic = None
        if v.atomic_results:
            atomic = [a.model_dump() for a in v.atomic_results]
        evidences.append(VerificationEvidence(
            reference_id=v.reference_id,
            reference_title=ref.title if ref else "",
            reference_authors=ref.authors if ref else [],
            verdict=v.verdict,
            confidence=v.confidence,
            tier=v.tier,
            reasoning=v.reasoning,
            evidence_sections=v.evidence_sections,
            atomic_results=atomic,
            user_override=v.user_override,
            user_override_reason=v.user_override_reason,
        ))
    return evidences
