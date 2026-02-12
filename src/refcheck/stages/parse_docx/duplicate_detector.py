"""Detect duplicate references in extracted reference lists."""

import logging

from rapidfuzz import fuzz

from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

_DOI_EXACT_THRESHOLD = 1.0
_TITLE_HIGH_THRESHOLD = 95
_TITLE_MEDIUM_THRESHOLD = 85


def detect_duplicates(
    references: list[Reference],
) -> tuple[list[Reference], list[str]]:
    """Scan references for duplicates and mark them.

    Returns updated references and a list of warning strings.
    """
    warnings: list[str] = []
    updated = list(references)

    for i, ref_a in enumerate(updated):
        if ref_a.duplicate_of is not None:
            continue
        for j in range(i + 1, len(updated)):
            ref_b = updated[j]
            if ref_b.duplicate_of is not None:
                continue

            dup_type = _check_duplicate(ref_a, ref_b)
            if dup_type:
                updated[j] = ref_b.model_copy(
                    update={"duplicate_of": ref_a.id},
                )
                warnings.append(
                    f"Reference [{ref_b.id}] appears to be a "
                    f"duplicate of [{ref_a.id}] ({dup_type})"
                )

    return updated, warnings


def _check_duplicate(a: Reference, b: Reference) -> str | None:
    """Check if two references are duplicates. Returns reason or None."""
    # Same DOI (exact match after normalization)
    if a.doi and b.doi:
        doi_a = a.doi.lower().strip()
        doi_b = b.doi.lower().strip()
        if doi_a == doi_b:
            return "same DOI"

    # Same title (high similarity)
    if a.title and b.title:
        ratio = fuzz.token_sort_ratio(a.title.lower(), b.title.lower())
        if ratio >= _TITLE_HIGH_THRESHOLD:
            return f"similar title ({ratio}%)"

    # Same first author + year + similar title
    if (
        a.authors and b.authors and a.year and b.year
        and a.year == b.year
        and a.authors[0].lower() == b.authors[0].lower()
        and a.title and b.title
    ):
        ratio = fuzz.token_sort_ratio(
            a.title.lower(), b.title.lower(),
        )
        if ratio >= _TITLE_MEDIUM_THRESHOLD:
            return (
                f"same first author + year + similar title"
                f" ({ratio}%)"
            )

    return None
