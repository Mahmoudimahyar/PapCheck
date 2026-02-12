"""DOI normalization utilities."""

import re

_DOI_PREFIX_PATTERN = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
    re.IGNORECASE,
)


def normalize_doi(doi: str) -> str:
    """Normalize a DOI string for comparison.

    Strips URL prefixes, lowercases, and removes trailing punctuation.
    """
    cleaned = _DOI_PREFIX_PATTERN.sub("", doi.strip())
    cleaned = cleaned.rstrip(".,;: ")
    return cleaned.lower()


def dois_match(doi_a: str | None, doi_b: str | None) -> bool:
    """Check if two DOIs refer to the same resource."""
    if doi_a is None or doi_b is None:
        return False
    return normalize_doi(doi_a) == normalize_doi(doi_b)
