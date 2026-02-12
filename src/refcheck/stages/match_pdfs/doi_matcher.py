"""DOI-based PDF matching: extract DOI from PDF and match to references."""

import logging
import re
from pathlib import Path

import fitz

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference
from refcheck.utils.doi import dois_match

logger = logging.getLogger(__name__)

_DOI_PATTERN = re.compile(r"(10\.\d{4,}/[^\s,;\"'>\]]+)")


def extract_doi_from_pdf(pdf_path: Path) -> str | None:
    """Extract DOI from a PDF via metadata or first-page text."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        logger.warning("Cannot open PDF: %s", pdf_path.name)
        return None

    try:
        # Check PDF metadata fields
        metadata = doc.metadata or {}
        for key in ("doi", "subject", "keywords", "title"):
            value = metadata.get(key, "")
            if value:
                match = _DOI_PATTERN.search(value)
                if match:
                    return _clean_doi(match.group(1))

        # Check first page text
        if len(doc) > 0:
            first_page_text = doc[0].get_text()
            match = _DOI_PATTERN.search(first_page_text)
            if match:
                return _clean_doi(match.group(1))

        # Check second page if first page had no DOI
        if len(doc) > 1:
            second_page_text = doc[1].get_text()
            match = _DOI_PATTERN.search(second_page_text)
            if match:
                return _clean_doi(match.group(1))
    finally:
        doc.close()

    return None


def _clean_doi(doi: str) -> str:
    """Strip trailing punctuation from a DOI."""
    return doi.rstrip(".,;:)")


def match_by_doi(
    references: list[Reference],
    pdf_path: Path,
) -> MatchResult | None:
    """Try to match a PDF to a reference using DOI."""
    pdf_doi = extract_doi_from_pdf(pdf_path)
    if not pdf_doi:
        return None

    for ref in references:
        if dois_match(ref.doi, pdf_doi):
            return MatchResult(
                reference_id=ref.id,
                pdf_path=str(pdf_path),
                confidence=0.99,
                match_method="doi",
                needs_user_confirmation=False,
            )
    return None
