"""Lineage connectives: "Building on these results, X (2016) ..." (V5.6, finding L4).

A citing sentence that opens with a lineage connective ("Building on these results",
"Based on these findings", "Following this", "Extending this work", "Subsequently",
"In a follow-up study", "Later,") asserts that the cited work came AFTER the work
cited in the previous sentence. The manual review found a 2016 paper presented as
building on 2018 work; no model listed the connective as an element.

Deterministic check: the author-year citations of the previous sentence ("(Smith et
al., 2018)", "Smith and Lee (2019)", "(Lee 2020; Wong, 2021)") give the years of the
prior work; when this reference's year is earlier than the latest of them, the
lineage is impossible (outcome_rules.py makes the pair partially_supported,
specific_detail_mismatch, minor). Numbered citations ("[12]") carry no year in the
sentence and are not checked (the pair context has no bibliography).

Only real citation markers count (as markers.py, with a stricter name: "DSPE-PEG
(2000)" is no author): a parenthesised author-year citation or a narrative one
("Smith et al. (2018)"); a capitalised word before a bare number ("Over 2020 grafts",
"December 2019") is not a citation. A connective counts only when it opens a lineage:
"Following / Based on / Building on" + a result noun ("these results", "their earlier
work") or a bare determiner closing the clause ("Following this,"); "Later" only as
"Later," or "Later work / studies"; never a compound ("Later-stage", "Afterward-treated").
"""

import re

from pydantic import BaseModel

_RESULT_NOUNS = (r"(?:results?|findings?|work|stud(?:y|ies)|observations?|data|reports?"
                 r"|approach(?:es)?)")
_DETERMINER = r"(?:th(?:is|ese|ose|at|e|eir)|such|his|her|its|our)"
# "these results", "their earlier work", or a bare "this," closing the clause.
_OBJECT = rf"{_DETERMINER}(?:(?:\s+[\w-]+){{0,2}}?\s+{_RESULT_NOUNS}\b|\s*,)"
_LEADS = (r"building\s+(?:up)?on|built\s+(?:up)?on|expanding\s+(?:up)?on|based\s+on"
          r"|following(?:\s+up\s+on)?|extending|further\s+to|inspired\s+by")
_CONNECTIVE_RE = re.compile(
    rf"^\W*(?:(?:{_LEADS})\s+{_OBJECT}"
    r"|(?:subsequently|thereafter|afterwards?)(?![-\w])"
    r"|later(?:\s*,|\s+(?:work|stud(?:y|ies)|reports?|experiments?)\b)"
    r"|in\s+a\s+(?:subsequent|follow[- ]?up)\b"
    r"|in\s+(?:a\s+)?later\s+(?:work|study|studies)\b)",
    re.IGNORECASE)
_CLAUSE_CHARS = 60  # the connective shown: up to the first comma when it is this close
# An author name: "Smith", "McDonald", "O'Brien", "Lee-Wong"; not an acronym ("DSPE-PEG").
_NAME = r"[A-Z](?:[a-z]|['’][A-Z])[A-Za-z'’\-]*"
_AUTHORS = rf"(?P<name>{_NAME})(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_NAME})?"
_YEAR = r"(?:19|20)\d{2}[a-z]?"
# "(Smith et al., 2018)", "(e.g., Lee 2020; Wong, 2021)"
_PAREN_CITATION_RE = re.compile(
    rf"\((?:(?:e\.g\.|see|cf\.|i\.e\.)\s*,?\s*)?{_AUTHORS},?\s+{_YEAR}"
    r"(?:\s*[;,][^()]{0,120})?\)")
# "Smith et al. (2018)", "Park (2017)"
_NARRATIVE_CITATION_RE = re.compile(rf"\b{_AUTHORS}\s*\(\s*{_YEAR}\s*\)")
_YEARS_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
# Capitalised words before a year that are not author names ("In 2018, ...").
_NOT_NAMES = frozenset({
    "In", "By", "From", "Since", "Until", "Before", "After", "During", "Of", "The", "This",
    "These", "Through", "Between", "To", "Around", "Circa", "As", "At", "For", "On",
    "Year", "Years", "Fig", "Figure", "Table", "Vol", "Volume", "Page", "Pages",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
})


class LineageConflict(BaseModel):
    """A lineage connective whose cited work predates the work it is said to follow."""

    connective: str
    ref_year: int
    prior_year: int

    @property
    def element(self) -> str:
        return (f"lineage: {self.connective} (the cited work, {self.ref_year}, predates the "
                f"work it is said to build on, {self.prior_year})")

    @property
    def note(self) -> str:
        return (f"Lineage check: '{self.connective}' presents this work as following the work "
                f"cited in the previous sentence, but the cited work ({self.ref_year}) "
                f"predates the work it is said to build on ({self.prior_year}).")


_ELEMENT_RE = re.compile(
    r"^lineage: (?P<connective>.+) \(the cited work, (?P<ref>\d{4}), predates the work it is "
    r"said to build on, (?P<prior>\d{4})\)$")


def lineage_action(element: str | None) -> str | None:
    """The author action for a ``LineageConflict.element``, else None."""
    match = _ELEMENT_RE.match((element or "").strip())
    if match is None:
        return None
    return (f"Rephrase or reorder '{match['connective']}': the cited work ({match['ref']}) "
            f"predates the work it is said to build on ({match['prior']}).")


def lineage_connective(sentence: str) -> str | None:
    """The opening lineage connective of ``sentence`` (to its first comma), else None."""
    match = _CONNECTIVE_RE.match(sentence or "")
    if match is None:
        return None
    text = sentence.strip()
    comma = text.find(",")
    clause = text[:comma] if 0 < comma <= _CLAUSE_CHARS else match.group(0).strip()
    return " ".join(clause.split())


def citation_years(text: str) -> list[int]:
    """Years of the author-year citations in ``text``, in text order ("(Smith et al.,
    2018)" -> 2018; module doc: citation markers only)."""
    found: list[tuple[int, int]] = []
    for pattern in (_PAREN_CITATION_RE, _NARRATIVE_CITATION_RE):
        found += [(m.start(), int(y)) for m in pattern.finditer(text or "")
                  if m.group("name") not in _NOT_NAMES for y in _YEARS_RE.findall(m.group())]
    return [year for _, year in sorted(found)]


def lineage_conflict(sentence: str, prev_sentence: str,
                     ref_year: int | None) -> LineageConflict | None:
    """The conflict when ``sentence`` claims to follow later work (module doc), else None."""
    connective = lineage_connective(sentence)
    if connective is None or ref_year is None:
        return None
    years = citation_years(prev_sentence)
    if not years or ref_year >= max(years):
        return None
    return LineageConflict(connective=connective, ref_year=ref_year, prior_year=max(years))
