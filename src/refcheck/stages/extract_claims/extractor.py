"""Claim extraction: LLM-powered extraction of claim-citation pairs."""

import logging

from refcheck.llm.client import LLMResponseInvalidError, call_llm
from refcheck.models.claim import Claim
from refcheck.models.reference import ParsedManuscript
from refcheck.stages.extract_claims.claim_parser import (
    AtomicDecompositionResponse,
    ClaimExtractionResponse,
    apply_priority,
    assign_sequential_ids,
    deduplicate_claims,
    filter_invalid_refs,
)
from refcheck.stages.extract_claims.position_mapper import map_claims_to_positions
from refcheck.stages.extract_claims.section_filter import (
    is_body_section,
    section_has_citations,
)

logger = logging.getLogger(__name__)

_DECOMPOSE_TYPES = frozenset({"factual", "contrast"})


def _build_reference_list(manuscript: ParsedManuscript) -> str:
    """Build a reference list string for the LLM prompt context."""
    lines: list[str] = []
    for ref in manuscript.references:
        parts = [f"[{ref.id}]"]
        if ref.authors:
            parts.append(", ".join(ref.authors[:3]))
        if ref.title:
            parts.append(ref.title)
        if ref.journal:
            parts.append(ref.journal)
        if ref.year:
            parts.append(f"({ref.year})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


async def extract_claims(
    manuscript: ParsedManuscript,
) -> list[Claim]:
    """Extract claim-citation pairs from a parsed manuscript.

    Processes body sections, calling the LLM for each section that
    contains citations. If no sections have detected citations, falls
    back to sending all body sections (citation format may not be
    detected). Deduplicates, assigns IDs, and runs V2 atomic
    decomposition on high-priority factual/contrast claims.
    """
    valid_ref_ids = {ref.id for ref in manuscript.references}
    reference_list = _build_reference_list(manuscript)

    # Filter to body sections only (skip references, acknowledgments, etc.)
    body_sections = [
        s for s in manuscript.sections
        if s.text and is_body_section(s)
    ]

    # Try citation-based filtering first
    sections_with_cites = [
        s for s in body_sections if section_has_citations(s.text)
    ]

    # Fallback: if no sections have detected citations but body text exists,
    # send all body sections — the citation format may not be bracket-based
    if not sections_with_cites and body_sections:
        logger.info(
            "No bracket/paren citations detected; sending all %d body "
            "sections to LLM for claim extraction",
            len(body_sections),
        )
        sections_with_cites = body_sections

    all_claims: list[Claim] = []
    warnings: list[str] = []

    for section in sections_with_cites:
        heading = section.heading or "Untitled Section"
        section_claims = await _extract_section_claims(
            section_text=section.text,
            reference_list=reference_list,
            section_heading=heading,
        )

        if section_claims is None:
            warnings.append(f"LLM failed for section: {heading}")
            continue

        processed = []
        for claim in section_claims:
            updated = apply_priority(claim)
            updated = updated.model_copy(update={"section_heading": heading})
            processed.append(updated)

        processed = filter_invalid_refs(processed, valid_ref_ids)
        all_claims.extend(processed)

    all_claims = deduplicate_claims(all_claims)
    all_claims = assign_sequential_ids(all_claims)

    # V2: Atomic decomposition for high-priority factual/contrast claims
    all_claims = await _decompose_claims(all_claims)

    # V2: Map claims to manuscript positions for the viewer
    all_claims = map_claims_to_positions(all_claims, manuscript)

    if warnings:
        logger.warning("Claim extraction warnings: %s", warnings)

    logger.info("Extracted %d claims from manuscript", len(all_claims))
    return all_claims


async def _decompose_claims(claims: list[Claim]) -> list[Claim]:
    """Run atomic decomposition on eligible claims."""
    result: list[Claim] = []
    for claim in claims:
        if _should_decompose(claim):
            atoms = await _decompose_single(claim)
            claim = claim.model_copy(update={"atomic_claims": atoms})
        result.append(claim)
    return result


def _should_decompose(claim: Claim) -> bool:
    """Only high-priority factual/contrast claims get decomposed."""
    return claim.claim_type in _DECOMPOSE_TYPES and claim.priority == "high"


async def _decompose_single(claim: Claim) -> list[str]:
    """Decompose a single claim into atoms. Returns [] on failure."""
    try:
        response = await call_llm(
            template="atomic_decomposition",
            variables={
                "claim": claim.extracted_claim,
                "claim_type": claim.claim_type,
            },
            output_model=AtomicDecompositionResponse,
        )
        return response.atoms
    except (LLMResponseInvalidError, Exception):
        logger.warning(
            "Atomic decomposition failed for claim %d", claim.id,
        )
        return []


async def _extract_section_claims(
    section_text: str,
    reference_list: str,
    section_heading: str,
) -> list[Claim] | None:
    """Extract claims from a single section via LLM. Returns None on failure."""
    try:
        response = await call_llm(
            template="claim_extraction",
            variables={
                "section_text": section_text,
                "reference_list": reference_list,
                "section_heading": section_heading,
            },
            output_model=ClaimExtractionResponse,
        )
        return response.claims
    except LLMResponseInvalidError:
        logger.warning(
            "LLM returned invalid response for section: %s",
            section_heading,
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected error extracting claims from section: %s",
            section_heading,
        )
        return None
