"""Main orchestrator for PDF matching."""

import logging
from pathlib import Path

import httpx
from rapidfuzz import fuzz

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.doi_matcher import extract_doi_from_pdf, match_by_doi
from refcheck.stages.match_pdfs.scorer import classify_match
from refcheck.stages.match_pdfs.title_matcher import extract_title_from_pdf, match_by_title

logger = logging.getLogger(__name__)

_CROSSREF_BASE = "https://api.crossref.org"


def match_pdfs(
    references: list[Reference],
    pdf_dir: Path,
) -> list[MatchResult]:
    """Match uploaded PDFs to manuscript references.

    Tries DOI matching first, then title fuzzy, then DOI-CrossRef lookup.
    """
    if not pdf_dir.exists():
        logger.warning("PDF directory does not exist: %s", pdf_dir)
        return []

    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logger.info("No PDF files found in %s", pdf_dir)
        return []

    results: list[MatchResult] = []
    matched_ref_ids: set[int] = set()
    matched_pdf_paths: set[str] = set()

    # Pass 1: Direct DOI matching (ref DOI == PDF DOI)
    for pdf_path in pdf_files:
        result = match_by_doi(references, pdf_path)
        if result and result.reference_id not in matched_ref_ids:
            classified = classify_match(result)
            results.append(classified)
            matched_ref_ids.add(result.reference_id)
            matched_pdf_paths.add(str(pdf_path))

    # Pass 2: Title fuzzy matching
    unmatched_refs = [r for r in references if r.id not in matched_ref_ids]
    for pdf_path in pdf_files:
        if str(pdf_path) in matched_pdf_paths:
            continue
        result = match_by_title(unmatched_refs, pdf_path)
        if result and result.reference_id not in matched_ref_ids:
            classified = classify_match(result)
            results.append(classified)
            matched_ref_ids.add(result.reference_id)
            matched_pdf_paths.add(str(pdf_path))

    # Pass 3: CrossRef DOI lookup — for PDFs with DOIs that didn't
    # match directly (reference has no DOI), look up the title via
    # CrossRef and fuzzy-match against remaining references
    still_unmatched_refs = [r for r in references if r.id not in matched_ref_ids]
    if still_unmatched_refs:
        for pdf_path in pdf_files:
            if str(pdf_path) in matched_pdf_paths:
                continue
            result = _match_via_crossref_doi(
                still_unmatched_refs, pdf_path, matched_ref_ids
            )
            if result and result.reference_id not in matched_ref_ids:
                classified = classify_match(result)
                results.append(classified)
                matched_ref_ids.add(result.reference_id)
                matched_pdf_paths.add(str(pdf_path))

    logger.info(
        "Matched %d/%d PDFs to references", len(results), len(pdf_files)
    )
    return results


def _match_via_crossref_doi(
    references: list[Reference],
    pdf_path: Path,
    already_matched: set[int],
) -> MatchResult | None:
    """Extract DOI from PDF, look up title via CrossRef, fuzzy match."""
    pdf_doi = extract_doi_from_pdf(pdf_path)
    if not pdf_doi:
        return None

    # Look up the DOI on CrossRef to get the canonical title
    cr_title = _lookup_doi_title(pdf_doi)
    if not cr_title:
        # Fallback: use the PDF-extracted title
        cr_title = extract_title_from_pdf(pdf_path)
    if not cr_title:
        return None

    best_score = 0.0
    best_ref: Reference | None = None

    for ref in references:
        if ref.id in already_matched or not ref.title:
            continue
        score = fuzz.token_sort_ratio(cr_title.lower(), ref.title.lower())
        normalized = score / 100.0
        if normalized > best_score:
            best_score = normalized
            best_ref = ref

    if best_ref is None or best_score < 0.55:
        return None

    confidence = min(best_score * 0.95, 0.98)
    return MatchResult(
        reference_id=best_ref.id,
        pdf_path=str(pdf_path),
        confidence=round(confidence, 3),
        match_method="doi_crossref_title",
        needs_user_confirmation=confidence < 0.90,
    )


def _lookup_doi_title(doi: str) -> str:
    """Look up a DOI on CrossRef and return the title."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{_CROSSREF_BASE}/works/{doi}")
            if resp.status_code != 200:
                return ""
            data = resp.json()
            msg = data.get("message", {})
            title_list = msg.get("title", [])
            if isinstance(title_list, list) and title_list:
                return str(title_list[0])
    except Exception as exc:
        logger.warning("CrossRef DOI lookup failed for %s: %s", doi, exc)
    return ""
