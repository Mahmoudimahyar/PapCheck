"""Flag citing sentences that are not complete claims (deterministic).

"Combining these features (Kray et al., 2023)." was verified as
if it asserted something and came back "not supported"; the real problem is
the manuscript sentence itself. Such claims are still verified, but carry
``claim_quality="fragment"`` so the verifier/report can say "Claim text
appears incomplete".
"""

import re
from typing import Literal

from refcheck.stages.detect_citations.verb_heuristics import has_verb, words

ClaimQualityLabel = Literal["ok", "fragment"]

_MIN_WORDS = 3
_MAX_HEADING_WORDS = 12
_SECTION_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+\S")
_MARKERS = re.compile(
    r"\([^()]*\d{4}[a-z]?[^()]*\)|\[\s*\d[\d,\s\-–—]*\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
)
_TERMINAL = re.compile(r"[.!?]['\")\]]*\s*$")


def assess_claim_quality(sentence: str) -> ClaimQualityLabel:
    """"fragment" when the citing sentence cannot be a complete assertion."""
    text = " ".join(_MARKERS.sub(" ", sentence).split())
    tokens = words(text)
    if len(tokens) < _MIN_WORDS or _looks_like_heading(sentence, text, tokens):
        return "fragment"
    # No tensed verb: a gerund/participle phrase ("Combining these
    # functionalities"), a bare noun phrase, or a sentence cut short.
    return "ok" if has_verb(text) else "fragment"


def _looks_like_heading(sentence: str, text: str, tokens: list[str]) -> bool:
    """Short, unpunctuated, numbered or Title Case line ("2.1 Hydrogel Barriers")."""
    if _TERMINAL.search(sentence.strip()) or len(tokens) > _MAX_HEADING_WORDS:
        return False
    if _SECTION_NUMBER.match(text):
        return True
    raw_words = [w for w in text.split() if w[:1].isalpha()]
    capitalised = sum(1 for w in raw_words if w[0].isupper())
    return bool(raw_words) and capitalised / len(raw_words) >= 0.7
