"""Citation-only text: nothing is asserted once the citation markers are removed.

"Lee et al. (2002)." split off as its own sentence carries no claim: the
sentence splitter must join it to the sentence it belongs to, and a citing
sentence that is still citation-only cannot be verified, so it is dropped
before verification (claim_filter). Deterministic, no LLM.
"""

import re

# Parenthetical "(Lee et al., 2020; Kim, 2021)" or numbered "[3, 5-7]"
PARENTHETICAL = re.compile(r"\([^()]*\d{4}[a-z]?[^()]*\)|\[\s*\d[\d,\s\-–—]*\]")
_NAME = r"[A-ZÀ-ÖØ-Þ][\w'’\-]+"
# Narrative "Lee et al. (2020)", "Lee and Kim (2020)", "Lee & Kim (2020a, 2021)".
# The dot of "et al." may already be the sentence splitter's placeholder (†).
NARRATIVE = re.compile(
    rf"\b{_NAME}(?:\s+et\s+al[.†]?|\s+(?:and|&)\s+{_NAME})?,?\s*"
    r"\(\s*\d{4}[a-z]?(?:\s*[,;]\s*\d{4}[a-z]?)*\s*\)",
)
# Words that may surround a bare citation without asserting anything
_FILLERS = frozenset({
    "see", "cf", "e", "g", "eg", "also", "and", "reviewed", "review", "in", "by",
})
_TOKEN = re.compile(r"[^\W_]+")


def strip_all_markers(text: str) -> str:
    """Text with narrative, parenthetical and numbered citation markers removed."""
    return PARENTHETICAL.sub(" ", NARRATIVE.sub(" ", text))


def is_citation_only(text: str) -> bool:
    """True when ``text`` holds citation markers and nothing else to verify."""
    if not (NARRATIVE.search(text) or PARENTHETICAL.search(text)):
        return False
    rest = strip_all_markers(text)
    return all(tok.lower() in _FILLERS for tok in _TOKEN.findall(rest))


def is_narrative_only(text: str) -> bool:
    """Citation-only text holding a narrative marker ("Lee et al. (2002).")."""
    return bool(NARRATIVE.search(text)) and is_citation_only(text)
