"""Claim numbers that occur nowhere in the cited source (deterministic check, M13).

A figure such as "<50% of patients" or "150 kPa" that appears nowhere in the
source document is strong evidence that the source is not where the number
comes from, whatever a model concluded from the retrieved passages. Years and
citation markers are ignored. Percentages and measurement units must match
with their unit ("150" in a page number is not "150 kPa"); plain counts match
any occurrence of the value. Time units are treated as plain numbers because
sources write them in too many forms ("day 40", "40 d", "40-day").
"""

import re
from functools import lru_cache

from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.figure_kind import (
    bound_before,
    label_before,
    nouns_around,
    object_after,
)
from refcheck.stages.verify_claims.gates import strip_markers_and_years
from refcheck.stages.verify_claims.numeric_text import quantity_text

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# Measurement units that must match (case-insensitive; longest alternatives first).
# Squares/cubes are dropped: PDFs often lose superscripts ("4 cm2").
_UNITS = (
    "mg/kg", "mg/ml", "µg/ml", "ng/ml", "pg/ml", "iu/ml", "u/ml",
    "mmhg", "kpa", "mpa", "gpa", "pa", "kda", "gy", "°c",
    "nm", "µm", "mm", "cm", "pg", "ng", "µg", "mg", "kg", "µl", "ml", "dl", "g", "l", "m",
)
_QUANTITY_RE = re.compile(
    rf"(?<![\w.])(?<![A-Za-z]-)(?P<num>{_NUM})(?!\w|\.\d)"
    rf"(?P<unit>\s?(?:%|percent\b|per cent\b|(?:{'|'.join(map(re.escape, _UNITS))})(?![a-z])))?",
    re.IGNORECASE,
)
_RANGE_GAP_RE = re.compile(r"\s?(?:–|—|-|to)\s?")


class SourceQuantity(BaseModel):
    """A number with its unit ("%" for percentages, "" for plain numbers)."""

    text: str
    value: float
    decimals: int
    unit: str
    label: str = ""  # statistic named right before it ("hr" in "HR 0.72"), figure_kind
    nouns: list[str] = Field(default_factory=list)  # words after it ("adult", "patient")
    object_words: list[str] = Field(default_factory=list)  # after "in / of" ("graft", "rejection")
    bound: str = ""  # "lower" ("more than X") / "upper" ("less than X"), figure_kind


def _unit(raw: str | None) -> str:
    # str.lower() turns the micro sign into Greek mu; keep one form for comparisons.
    unit = " ".join((raw or "").split()).lower().replace("μ", "µ")
    return "%" if unit in ("%", "percent", "per cent") else unit


def quantities(text: str, source: bool = False) -> list[SourceQuantity]:
    """Numbers in ``text`` with units; a range "1.8–120 kPa" gives both ends the unit.

    Comparison symbols are normalised and digits of names (α-1,3, 5-HT) masked
    first (numeric_text); ``source`` also unglues mangled glyphs ("Z65" = ">=65").
    """
    clean = strip_markers_and_years(quantity_text(text.replace("μ", "µ"), source))
    matches = list(_QUANTITY_RE.finditer(clean))
    out: list[SourceQuantity] = []
    for i, match in enumerate(matches):
        written = (match.group("unit") or "").strip()
        nxt = matches[i + 1] if i + 1 < len(matches) else None
        if not written and nxt is not None \
                and _RANGE_GAP_RE.fullmatch(clean[match.end():nxt.start()]):
            written = (nxt.group("unit") or "").strip()
        unit = _unit(written)
        digits = match.group("num").replace(",", "")
        decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
        shown = match.group("num") + ("%" if unit == "%" else f" {written}" if unit else "")
        out.append(SourceQuantity(text=shown, value=float(digits), decimals=decimals,
                                  unit=unit, label=label_before(clean, match.start()),
                                  nouns=nouns_around(clean, match.start(), match.end()),
                                  object_words=object_after(clean, match.end()),
                                  bound=bound_before(clean, match.start())))
    return out


@lru_cache(maxsize=64)
def source_index(source_text: str) -> tuple[SourceQuantity, ...]:
    """Every quantity of a source text (cached: the same text is checked per claim)."""
    return tuple(quantities(source_text, source=True))


def found_in(q: SourceQuantity, pool: tuple[SourceQuantity, ...]) -> bool:
    """The claim quantity ``q`` occurs in ``pool`` (claim precision; its unit if any)."""
    tolerance = 0.5 / float(10 ** q.decimals) + 1e-9  # claim precision decides
    return any(abs(s.value - q.value) <= tolerance and (not q.unit or s.unit == q.unit)
               for s in pool)


def numbers_missing_from_source(claim: str, source_text: str) -> list[str]:
    """Claim quantities (years and citation markers excluded) absent from the source."""
    if not source_text.strip():
        return []
    pool = source_index(source_text)
    return list(dict.fromkeys(q.text for q in quantities(claim) if not found_in(q, pool)))


def figures_only_absent(claim: str, source_text: str) -> bool:
    """Claim figures are missing from the source, which states none of them differently.

    "Differently" = a source figure of the same kind (``_same_kind``): the same unit
    ("%", "kPa"); for plain numbers the same statistic label ("HR 0.85" vs "HR 0.72",
    "p = 0.03" vs "p < 0.001"), a shared following word after normalisation ("180 adult
    patients" vs "240 patients", "58 yr" vs "65 years"), or, for a bare claim figure
    (no word after it), any bare source figure.
    """
    if not source_text.strip():
        return False
    pool = source_index(source_text)
    missing = [q for q in quantities(claim) if not found_in(q, pool)]
    return bool(missing) and not any(_same_kind(q, s) for q in missing for s in pool)


def _same_kind(claim_q: SourceQuantity, source_q: SourceQuantity) -> bool:
    if claim_q.unit != source_q.unit:
        return False
    if claim_q.unit or (claim_q.label and claim_q.label == source_q.label):
        return True
    if not claim_q.nouns:  # a bare figure ("HR 0.72", "(0.72)"): any bare source figure
        return not source_q.nouns
    return bool(set(claim_q.nouns) & set(source_q.nouns))
