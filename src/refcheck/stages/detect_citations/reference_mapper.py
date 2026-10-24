"""Map detected citations to references in the reference list."""

import logging

from rapidfuzz import fuzz

from refcheck.models.citation import CitationInstance
from refcheck.models.reference import Reference
from refcheck.stages.detect_citations.author_year_matcher import (
    Pick,
    ambiguous_pick,
    last_name,
    normalize_name,
    pick_reference,
    reference_year,
    split_year,
)

logger = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 85
_YEAR_MISMATCH_CONFIDENCE = 0.5


def map_citations_to_references(
    citations: list[CitationInstance],
    references: list[Reference],
) -> list[CitationInstance]:
    """Map each citation to its matching reference.

    Returns new list with reference fields populated via model_copy.
    """
    return [_map_single(cit, references) for cit in citations]


def _map_single(
    citation: CitationInstance, references: list[Reference],
) -> CitationInstance:
    """Map a single citation using cascading strategies.

    Returns a new CitationInstance with mapping fields set.
    """
    # Strategy 0: numbered direct lookup
    if citation.number is not None:
        match = _find_by_number(citation.number, references)
        if match:
            return _apply(citation, Pick(reference=match, method="number", confidence=1.0))

    pick = _pick_author_year(citation, references) if citation.authors else None
    if pick is None and citation.authors:
        pick = _pick_author_only(citation, references)
    if pick is not None:
        return _apply(citation, pick)

    return citation.model_copy(update={
        "mapping_method": "unresolved",
        "mapping_confidence": 0.0,
    })


def _pick_author_year(
    cit: CitationInstance, refs: list[Reference],
) -> Pick | None:
    """Strategies 1-3: first author + year (letter-aware), then co-authors."""
    if not cit.year:
        return None
    year, suffix = split_year(cit.year)
    dated = [r for r in refs if r.authors and str(reference_year(r)[0]) == year]
    author = normalize_name(cit.authors[0])

    exact = [r for r in dated if _first_surname(r) == author]
    if exact:
        return pick_reference(exact, suffix, cit.authors, "exact_author_year", 0.95)

    scored = [(fuzz.ratio(author, _first_surname(r)), r) for r in dated]
    best = max((s for s, _ in scored), default=0.0)
    if best >= _FUZZY_THRESHOLD:
        fuzzy = [r for s, r in scored if s == best]
        return pick_reference(fuzzy, suffix, cit.authors, "fuzzy_author_year", 0.85)

    if len(cit.authors) > 1:
        wanted = {normalize_name(a) for a in cit.authors}
        multi = [
            r for r in dated
            if wanted <= {normalize_name(last_name(a)) for a in r.authors}
        ]
        if multi:
            return pick_reference(multi, suffix, cit.authors, "multi_author_year", 0.90)
    return None


def _pick_author_only(
    cit: CitationInstance, refs: list[Reference],
) -> Pick | None:
    """Strategy 4: author only — "n.d." citations, or a year that matches nothing."""
    author = normalize_name(cit.authors[0])
    if cit.year:
        # The year disagrees with every same-author reference: never a silent
        # guess (a fuzzy "Sous" once landed on "de Sousa, 2023").
        same = [r for r in refs if r.authors and _first_surname(r) == author]
        if not same:
            return None
        pick = ambiguous_pick(same, "author_only_year_mismatch")
        return pick.model_copy(update={"confidence": _YEAR_MISMATCH_CONFIDENCE})
    same = [
        r for r in refs
        if r.authors and (
            _first_surname(r) == author
            or fuzz.ratio(author, _first_surname(r)) >= _FUZZY_THRESHOLD
        )
    ]
    if not same:
        return None
    undated = [r for r in same if reference_year(r)[0] is None]
    return pick_reference(undated or same, None, cit.authors, "author_only", 0.70)


def _apply(cit: CitationInstance, pick: Pick) -> CitationInstance:
    """Apply a reference match to a citation via model_copy."""
    return cit.model_copy(update={
        "reference_id": pick.reference.id,
        "reference_title": pick.reference.title,
        "mapping_confidence": pick.confidence,
        "mapping_method": pick.method,
        "mapping_ambiguous": pick.ambiguous,
        "candidate_reference_ids": pick.candidates,
    })


def _find_by_number(
    number: int, refs: list[Reference],
) -> Reference | None:
    """Find reference by number (1-indexed)."""
    for ref in refs:
        if ref.id == number:
            return ref
    return None


def _first_surname(ref: Reference) -> str:
    return normalize_name(last_name(ref.authors[0])) if ref.authors else ""
