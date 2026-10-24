"""Choose among references that share a first author and year.

APA lists disambiguate same-surname/same-year works with letters: "Wang et
al., 2024a/b/c" (often different first authors — Wang Q. and Wang Y.). The
old mapper dropped the letter and took the first reference with that
surname and year, so every "2024c" landed on "2024a". Here the letter must
match exactly; without one, co-authors or known duplicates can settle it,
and otherwise the mapping is flagged ambiguous instead of guessed silently.
"""

import logging
import re
import unicodedata

from pydantic import BaseModel, Field

from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

AMBIGUOUS_CONFIDENCE = 0.5
_SUFFIX_ORDER_PENALTY = 0.1
_RAW_YEAR = re.compile(r"\(((?:19|20)\d{2})([a-z])?(?:,[^)]{0,30})?\)")


class Pick(BaseModel):
    """The chosen reference plus how sure the choice is."""

    reference: Reference
    method: str
    confidence: float
    ambiguous: bool = False
    candidates: list[int] = Field(default_factory=list)


def split_year(year: str) -> tuple[str, str | None]:
    """"2018b" -> ("2018", "b"); "2018" -> ("2018", None)."""
    match = re.fullmatch(r"(\d{4})([a-z])?", year.strip())
    if not match:
        return year.strip(), None
    return match.group(1), match.group(2)


def reference_year(ref: Reference) -> tuple[int | None, str | None]:
    """Year and suffix letter of a reference (raw text as fallback)."""
    raw = _RAW_YEAR.search(ref.raw_text or "")
    if ref.year is not None:
        suffix = ref.year_suffix
        if suffix is None and raw and int(raw.group(1)) == ref.year:
            suffix = raw.group(2)
        return ref.year, suffix
    if raw:
        return int(raw.group(1)), raw.group(2)
    return None, None


def pick_reference(
    cands: list[Reference], suffix: str | None, cit_authors: list[str],
    method: str, confidence: float,
) -> Pick:
    """Pick one of ``cands`` (same first author + year, in list order)."""
    if suffix:
        return _pick_with_suffix(cands, suffix, cit_authors, method, confidence)
    distinct = _collapse_duplicates(cands)
    if len(distinct) == 1:
        return Pick(reference=distinct[0], method=method, confidence=confidence)
    narrowed = _narrow_by_coauthors(distinct, cit_authors)
    if len(narrowed) == 1:
        return Pick(reference=narrowed[0], method=f"{method}+coauthor", confidence=confidence)
    return ambiguous_pick(narrowed, method)


def ambiguous_pick(cands: list[Reference], method: str) -> Pick:
    """Best guess (first in list order) with the ambiguity made visible."""
    ids = [c.id for c in cands]
    logger.warning("Ambiguous citation mapping (%s): candidates %s", method, ids)
    return Pick(
        reference=cands[0], method=method, confidence=AMBIGUOUS_CONFIDENCE,
        ambiguous=True, candidates=ids,
    )


def _pick_with_suffix(
    cands: list[Reference], suffix: str, cit_authors: list[str],
    method: str, confidence: float,
) -> Pick:
    suffixes = [reference_year(c)[1] for c in cands]
    exact = [c for c, s in zip(cands, suffixes, strict=True) if s == suffix]
    if exact:
        narrowed = _narrow_by_coauthors(exact, cit_authors)
        if len(narrowed) == 1:
            return Pick(reference=narrowed[0], method=method, confidence=confidence)
        return ambiguous_pick(narrowed, method)
    if all(s is None for s in suffixes):
        # The list prints no letters: "a" is the first such reference, "b" the second
        index = ord(suffix) - ord("a")
        if len(cands) == 1:
            return Pick(reference=cands[0], method=method, confidence=confidence)
        if 0 <= index < len(cands):
            return Pick(
                reference=cands[index], method=f"{method}+suffix_order",
                confidence=confidence - _SUFFIX_ORDER_PENALTY,
            )
    # e.g. "(Smith, 2018c)" but the list only has 2018a and 2018b
    return ambiguous_pick(cands, f"{method}+suffix_mismatch")


def _collapse_duplicates(cands: list[Reference]) -> list[Reference]:
    """Drop references flagged as duplicates of another candidate (same work)."""
    ids = {c.id for c in cands}
    return [c for c in cands if c.duplicate_of is None or c.duplicate_of not in ids]


def _narrow_by_coauthors(cands: list[Reference], cit_authors: list[str]) -> list[Reference]:
    """Keep candidates listing every co-author the citation names ("A and B, 2020")."""
    others = {normalize_name(a) for a in cit_authors[1:]}
    if not others or len(cands) < 2:
        return cands
    kept = [
        c for c in cands
        if others <= {normalize_name(last_name(a)) for a in c.authors}
    ]
    return kept or cands


def normalize_name(name: str) -> str:
    """Accent-free lowercase surname without leading particles."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = ascii_name.lower().strip()
    return re.sub(
        r"^(de|van|von|del|der|den|di|da|la|le|el|al|bin|ibn|dos|das)\s+", "", lower,
    )


def last_name(full_name: str) -> str:
    """Last name from 'First Last' or 'Last, First' format."""
    if "," in full_name:
        return full_name.split(",")[0].strip()
    parts = full_name.strip().split()
    # "Smith JA" / "J. A. Smith": skip the initials
    names = [p for p in parts if not re.fullmatch(r"(?:[A-Z]\.?-?){1,3}", p)]
    if names:
        return names[-1]
    return parts[-1] if parts else full_name
