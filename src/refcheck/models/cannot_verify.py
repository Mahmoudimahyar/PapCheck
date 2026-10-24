"""Cannot-verify reason classification (V2, extended for the V5 cascade).

Provides detailed reason breakdown for claims that could not be verified.
"""

from enum import StrEnum


class CannotVerifyReason(StrEnum):
    """Specific reasons why a claim could not be verified."""

    NO_PDF_PAYWALLED = "no_pdf_paywalled"
    NO_PDF_NOT_FOUND = "no_pdf_not_found"
    NO_PDF_BOOK_CHAPTER = "no_pdf_book_chapter"
    NO_PDF_WEBSITE = "no_pdf_website"
    PDF_METADATA_ONLY = "pdf_metadata_only"
    PDF_SCANNED = "pdf_scanned"
    PDF_SUPPLEMENT = "pdf_supplement"
    SECTION_IRRELEVANT = "section_irrelevant"
    REFERENCE_MISMATCH = "reference_mismatch"
    LLM_ERROR = "llm_error"
    ABSTRACT_INSUFFICIENT = "abstract_insufficient"
    NOT_RELEVANT = "not_relevant"
    # V5: the judge saw the expanded full-text pack and still found too little
    # evidence either way (distinct from having no source at all).
    INSUFFICIENT_IN_SOURCE = "insufficient_in_source"


# Source-document quality reasons that mean "the attached PDF is not usable as
# the cited article" -> the cannot_verify reason reported for the pair.
PDF_PROBLEM_REASONS: dict[str, CannotVerifyReason] = {
    "pdf_unreadable": CannotVerifyReason.PDF_SCANNED,  # no text layer: scanned or broken
    "pdf_scanned": CannotVerifyReason.PDF_SCANNED,
    "likely_supplement": CannotVerifyReason.PDF_SUPPLEMENT,
    "metadata_only": CannotVerifyReason.PDF_METADATA_ONLY,
    "reference_mismatch": CannotVerifyReason.REFERENCE_MISMATCH,
}


def classify_cannot_verify(
    reference_source_status: str,
    reference_doi: str | None,
    reference_type: str | None,
    text_quality_score: float,
    section_relevance: str,
    source_coverage: str,
    had_llm_error: bool,
) -> CannotVerifyReason:
    """Determine the specific reason a claim could not be verified."""
    if source_coverage == "no_source":
        return _classify_no_source(reference_type, reference_doi)

    if had_llm_error:
        return CannotVerifyReason.LLM_ERROR
    if text_quality_score < 0.3:
        return _classify_low_quality(text_quality_score)
    if section_relevance == "low":
        return CannotVerifyReason.SECTION_IRRELEVANT
    if source_coverage == "abstract_only":
        return CannotVerifyReason.ABSTRACT_INSUFFICIENT

    return CannotVerifyReason.SECTION_IRRELEVANT


def classify_quality_reason(quality_reason: str, quality_score: float) -> CannotVerifyReason:
    """Reason for an unusable PDF from the source document's quality verdict."""
    reason = PDF_PROBLEM_REASONS.get(quality_reason)
    return reason if reason is not None else _classify_low_quality(quality_score)


def _classify_no_source(
    reference_type: str | None, reference_doi: str | None,
) -> CannotVerifyReason:
    """Classify no-source cannot-verify reasons."""
    if reference_type == "website":
        return CannotVerifyReason.NO_PDF_WEBSITE
    if reference_type == "book_chapter":
        return CannotVerifyReason.NO_PDF_BOOK_CHAPTER
    if reference_doi:
        return CannotVerifyReason.NO_PDF_PAYWALLED
    return CannotVerifyReason.NO_PDF_NOT_FOUND


def _classify_low_quality(text_quality_score: float) -> CannotVerifyReason:
    """Classify low-quality PDF reasons."""
    if text_quality_score < 0.15:
        return CannotVerifyReason.PDF_METADATA_ONLY
    return CannotVerifyReason.PDF_SUPPLEMENT
