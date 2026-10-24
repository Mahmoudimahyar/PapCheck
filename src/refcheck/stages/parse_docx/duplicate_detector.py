"""Detect duplicate references in extracted reference lists.

Runs inside parse_manuscript() (it used to exist but was never called, so
"Wang 2024a" and "Wang 2024b" — the same DOI and title — were both kept as
distinct references). A duplicate keeps its own id and gets ``duplicate_of``
pointing at the first occurrence; the reason goes into the parse warnings.
"""

import logging
import re
import unicodedata

from rapidfuzz import fuzz

from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

_TITLE_HIGH_THRESHOLD = 95
_TITLE_MEDIUM_THRESHOLD = 85
# Two long titles this different are distinct works even with one DOI
# (chapters of one book can share the book's DOI).
_SAME_DOI_TITLE_FLOOR = 50
_MIN_TITLE_CHARS_FOR_DOI_GUARD = 25

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_NUMBER = re.compile(r"\d+")


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
                logger.info("Duplicate reference [%d] of [%d]: %s", ref_b.id, ref_a.id, dup_type)

    return updated, warnings


def normalize_doi(doi: str | None) -> str:
    """Case-insensitive DOI without resolver prefix or trailing punctuation."""
    if not doi:
        return ""
    return _DOI_PREFIX.sub("", doi.strip()).rstrip(".,;)").lower()


def _check_duplicate(a: Reference, b: Reference) -> str | None:
    """Check if two references are duplicates. Returns reason or None."""
    doi_a, doi_b = normalize_doi(a.doi), normalize_doi(b.doi)
    ratio = _title_ratio(a, b)
    if doi_a and doi_a == doi_b:
        if ratio is not None and ratio < _SAME_DOI_TITLE_FLOOR and _both_long(a, b):
            return None
        return "same DOI"
    # Different DOIs are different works; conflicting metadata too
    if (doi_a and doi_b) or ratio is None or _conflicting(a, b):
        return None
    if ratio >= _TITLE_HIGH_THRESHOLD:
        return f"similar title ({ratio}%)"
    if _same_first_author_and_year(a, b) and ratio >= _TITLE_MEDIUM_THRESHOLD:
        return f"same first author + year + similar title ({ratio}%)"
    return None


def _title_ratio(a: Reference, b: Reference) -> int | None:
    if not a.title or not b.title:
        return None
    return int(fuzz.token_sort_ratio(_norm_text(a.title), _norm_text(b.title)))


def _both_long(a: Reference, b: Reference) -> bool:
    return min(len(a.title), len(b.title)) >= _MIN_TITLE_CHARS_FOR_DOI_GUARD


def _conflicting(a: Reference, b: Reference) -> bool:
    """Known metadata that rules a duplicate out (years, first authors, numbers)."""
    if a.year and b.year and a.year != b.year:
        return True
    sur_a, sur_b = _first_surname(a), _first_surname(b)
    if sur_a and sur_b and sur_a != sur_b:
        return True
    # "Registry 2017 Annual Data Report" vs "... 2020 ..." are different reports
    return _NUMBER.findall(a.title) != _NUMBER.findall(b.title)


def _same_first_author_and_year(a: Reference, b: Reference) -> bool:
    sur_a, sur_b = _first_surname(a), _first_surname(b)
    return bool(sur_a and sur_a == sur_b and a.year and a.year == b.year)


def _first_surname(ref: Reference) -> str:
    """Normalised family name of the first author ("Wang, Q." -> "wang")."""
    if not ref.authors:
        return ""
    first = ref.authors[0].strip()
    if "," in first:
        return _norm_text(first.split(",")[0])
    # "A. Smith" / "Smith JA": the surname is the token that is not initials
    names = [t for t in first.split() if len(t.strip(".")) > 1 and not t.isupper()]
    return _norm_text(names[-1]) if names else _norm_text(first)


def _norm_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", ascii_text.lower()).split())
