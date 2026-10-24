"""Publication year (+ author-year disambiguation letter) of a reference.

APA/Harvard lists disambiguate same-author/same-year works with a letter:
"(2018a)", "(2018b)". A plain ``\\b2018\\b`` never matches "2018a" (no word
boundary before the letter), so those references used to get ``year=None``
and every "(Doe et al., 2018b)" citation fell through to the first
reference with that author. The letter is returned separately so the
citation mapper can match it exactly.
"""

import re

from pydantic import BaseModel

_MIN_YEAR = 1900
_MAX_YEAR = 2035

# "(2018a)", "(2018)", "(2020, March 3)" — the author-year position
_PAREN_YEAR = re.compile(r"\(((?:19|20)\d{2})([a-z])?(?:,[^)]{0,30})?\)")
# bare "2018" or "2018a" (letters a-k only: "1990s" is a decade, not a suffix)
_BARE_YEAR = re.compile(r"\b((?:19|20)\d{2})([a-k])?\b")
# Years inside DOIs/URLs ("fimmu.2024.1391504") are not publication years
_DOI_OR_URL = re.compile(r"(?:https?://|doi:\s*|\b10\.\d{4,}/)\S+", re.IGNORECASE)


class YearInfo(BaseModel):
    """Publication year and optional disambiguation letter."""

    year: int | None = None
    suffix: str | None = None


def extract_year_info(text: str) -> YearInfo:
    """Year and suffix letter, preferring the parenthesised author-year slot."""
    for match in _PAREN_YEAR.finditer(text):
        year = int(match.group(1))
        if _MIN_YEAR <= year <= _MAX_YEAR:
            return YearInfo(year=year, suffix=match.group(2))
    without_ids = _DOI_OR_URL.sub(" ", text)
    for match in _BARE_YEAR.finditer(without_ids):
        year = int(match.group(1))
        if _MIN_YEAR <= year <= _MAX_YEAR:
            return YearInfo(year=year, suffix=match.group(2))
    return YearInfo()
