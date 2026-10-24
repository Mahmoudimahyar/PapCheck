"""Deterministic code gates for the screen auto-clear + numeric checks.

A pair may only be auto-cleared by the screen when every gate holds; the
gates exclude claim shapes where a fast predicate model is known to be
unreliable (numbers, negations, long or contrastive claims, abstract-only or
poor-quality sources).
"""

import re
from functools import lru_cache

from pydantic import BaseModel

from refcheck.stages.verify_claims.numeric_text import quantity_text
from refcheck.stages.verify_claims.retriever import clean_query

MAX_CLEAR_WORDS = 60
_YEAR_RE = re.compile(r"\b(?:1[89]\d{2}|20\d{2})(?:s|'s)?\b")
_NEGATION_RE = re.compile(
    r"\b(?:not|no|without|fail\w*|unlike|neither|nor|cannot|lack\w*)\b|\w+n['’]t\b",
    re.IGNORECASE,
)
# A quantity: not glued to a word (IL-6, CD4, p53, COVID-19, H1N1 are names).
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?<![A-Za-z]-)(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?!\w)(\s?%|\s?percent\b)?",
    re.IGNORECASE,
)


class Quantity(BaseModel):
    """A number mentioned in text (years excluded)."""

    text: str
    value: float
    decimals: int
    percent: bool


def strip_markers_and_years(text: str) -> str:
    """Text with citation markers and years blanked (they are never quantities)."""
    return _YEAR_RE.sub(" ", clean_query(text))


def has_non_year_digits(text: str) -> bool:
    """Digits other than years and citation markers ("[12]", "(3, 4)", "Smith 2010")."""
    return any(ch.isdigit() for ch in strip_markers_and_years(text))


def has_negation_cue(text: str) -> bool:
    """not / no / without / fail* / unlike / neither / nor / cannot / lack* / n't."""
    return _NEGATION_RE.search(text) is not None


def word_count(text: str) -> int:
    return len(text.split())


def is_contrast(claim_type: str) -> bool:
    return claim_type == "contrast"


def is_abstract_only(coverage: str) -> bool:
    return coverage != "full_text"


def quality_ok(quality_reason: str, quality_score: float) -> bool:
    """Only clean, complete full texts are eligible for auto-clear."""
    return quality_reason == "ok" and quality_score >= 0.6


def extract_quantities(text: str, source: bool = False) -> list[Quantity]:
    """Numbers in text, years, citation markers and name digits (IL-6, α-1,3) removed.

    ``source``: the text comes from a PDF (also unglue mangled comparison glyphs).
    """
    out: list[Quantity] = []
    for match in _NUMBER_RE.finditer(strip_markers_and_years(quantity_text(text, source))):
        raw = match.group(1)
        digits = raw.replace(",", "")
        decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
        out.append(Quantity(text=raw + (match.group(2) or "").strip(), value=float(digits),
                            decimals=decimals, percent=bool(match.group(2))))
    return out


def _matches(claim_q: Quantity, quote_q: Quantity) -> bool:
    # "30%" in a claim matches 30.2% in the source (claim precision decides).
    tolerance = 0.5 / float(10 ** claim_q.decimals) + 1e-9
    return abs(quote_q.value - claim_q.value) <= tolerance


@lru_cache(maxsize=64)
def _source_quantities(source_text: str) -> tuple[Quantity, ...]:
    return tuple(extract_quantities(source_text, source=True))


def numeric_mismatch(claim: str, quotes: list[str], near_text: str | None = None,
                     ) -> tuple[list[str], list[str]] | None:
    """(unmatched claim numbers, quoted numbers) when they disagree, else None.

    Only flags a claim number when the quotes contain a number of the same
    kind (percentage vs plain) and none of them matches it, and (when
    ``near_text`` is given: the source text right around the quotes, see
    post_checks.quote_surroundings) the figure is not stated there either, e.g.
    for another arm of the quoted result. A figure stated only elsewhere in the
    paper is still a mismatch: common figures appear somewhere in most papers.
    """
    claim_qs = extract_quantities(claim)
    quote_qs = [q for text in quotes for q in extract_quantities(text, source=True)]
    if not claim_qs or not quote_qs:
        return None
    pool = _source_quantities(near_text) if near_text else ()
    unmatched = [
        c for c in claim_qs
        if not any(_matches(c, q) for q in quote_qs)
        and any(q.percent == c.percent for q in quote_qs)
        and not any(_matches(c, s) and s.percent == c.percent for s in pool)
    ]
    if not unmatched:
        return None
    return [c.text for c in unmatched], list(dict.fromkeys(q.text for q in quote_qs))
