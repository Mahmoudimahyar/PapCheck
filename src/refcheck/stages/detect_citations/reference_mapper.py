"""Map detected citations to references in the reference list."""

import logging
import re
import unicodedata

from rapidfuzz import fuzz

from refcheck.models.citation import CitationInstance
from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 85


def map_citations_to_references(
    citations: list[CitationInstance],
    references: list[Reference],
) -> list[CitationInstance]:
    """Map each citation to its matching reference.

    Populates reference_id, reference_title, mapping_confidence,
    and mapping_method. Returns the same list with fields filled.
    """
    for citation in citations:
        _map_single(citation, references)
    return citations


def _map_single(
    citation: CitationInstance, references: list[Reference],
) -> None:
    """Map a single citation using cascading strategies."""
    # Strategy 0: numbered direct lookup
    if citation.number is not None:
        match = _find_by_number(citation.number, references)
        if match:
            _apply_match(citation, match, 1.0, "number")
            return

    # Strategy 1: exact first author + exact year
    if citation.authors and citation.year:
        year_str = citation.year.rstrip("abcdefghij")
        match = _find_exact_author_year(
            citation.authors[0], year_str, references,
        )
        if match:
            _apply_match(citation, match, 0.95, "exact_author_year")
            return

    # Strategy 2: fuzzy first author + exact year
    if citation.authors and citation.year:
        year_str = citation.year.rstrip("abcdefghij")
        match = _find_fuzzy_author_year(
            citation.authors[0], year_str, references,
        )
        if match:
            _apply_match(citation, match, 0.85, "fuzzy_author_year")
            return

    # Strategy 3: multi-author + year
    if len(citation.authors) > 1 and citation.year:
        year_str = citation.year.rstrip("abcdefghij")
        match = _find_multi_author_year(
            citation.authors, year_str, references,
        )
        if match:
            _apply_match(citation, match, 0.90, "multi_author_year")
            return

    # Strategy 4: author only (no year — e.g., "n.d.")
    if citation.authors:
        match = _find_by_author_only(citation.authors[0], references)
        if match:
            _apply_match(citation, match, 0.70, "author_only")
            return

    citation.mapping_method = "unresolved"
    citation.mapping_confidence = 0.0


def _apply_match(
    cit: CitationInstance, ref: Reference,
    confidence: float, method: str,
) -> None:
    """Apply a reference match to a citation."""
    cit.reference_id = ref.id
    cit.reference_title = ref.title
    cit.mapping_confidence = confidence
    cit.mapping_method = method


def _find_by_number(
    number: int, refs: list[Reference],
) -> Reference | None:
    """Find reference by number (1-indexed)."""
    for ref in refs:
        if ref.id == number:
            return ref
    return None


def _find_exact_author_year(
    author: str, year: str, refs: list[Reference],
) -> Reference | None:
    """Find by exact first author last name + year."""
    norm_author = _normalize_name(author)
    for ref in refs:
        if not ref.authors or not ref.year:
            continue
        ref_first = _extract_last_name(ref.authors[0])
        if _normalize_name(ref_first) == norm_author and str(ref.year) == year:
            return ref
    return None


def _find_fuzzy_author_year(
    author: str, year: str, refs: list[Reference],
) -> Reference | None:
    """Find by fuzzy first author + exact year."""
    norm_author = _normalize_name(author)
    best_ref: Reference | None = None
    best_score = 0.0
    for ref in refs:
        if not ref.authors or not ref.year:
            continue
        if str(ref.year) != year:
            continue
        ref_first = _normalize_name(_extract_last_name(ref.authors[0]))
        score = fuzz.ratio(norm_author, ref_first)
        if score >= _FUZZY_THRESHOLD and score > best_score:
            best_score = score
            best_ref = ref
    return best_ref


def _find_multi_author_year(
    authors: list[str], year: str, refs: list[Reference],
) -> Reference | None:
    """Match using multiple author last names + year."""
    norm_authors = {_normalize_name(a) for a in authors}
    for ref in refs:
        if not ref.authors or not ref.year:
            continue
        if str(ref.year) != year:
            continue
        ref_names = {_normalize_name(_extract_last_name(a)) for a in ref.authors}
        if norm_authors.issubset(ref_names):
            return ref
    return None


def _find_by_author_only(
    author: str, refs: list[Reference],
) -> Reference | None:
    """Find by author name only (for n.d. citations)."""
    norm = _normalize_name(author)
    for ref in refs:
        if not ref.authors:
            continue
        ref_first = _normalize_name(_extract_last_name(ref.authors[0]))
        if ref_first == norm or fuzz.ratio(norm, ref_first) >= _FUZZY_THRESHOLD:
            return ref
    return None


def _normalize_name(name: str) -> str:
    """Normalize author name for comparison."""
    # Strip accents via unicode NFKD decomposition
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase and strip particles
    lower = ascii_name.lower().strip()
    lower = re.sub(
        r"^(de|van|von|del|der|den|di|da|la|le|el|al|bin|ibn|dos|das)\s+",
        "", lower,
    )
    return lower


def _extract_last_name(full_name: str) -> str:
    """Extract last name from 'First Last' or 'Last, First' format."""
    if "," in full_name:
        return full_name.split(",")[0].strip()
    parts = full_name.strip().split()
    return parts[-1] if parts else full_name
