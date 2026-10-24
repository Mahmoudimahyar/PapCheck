"""Polarity trigger of the slot audit (V5.8 #31, F10; slot_apply.py asks about it).

Both models can read a source sentence of the opposite polarity as support: the
supporting quote says "graft Q is not widely used" while the cited span says "graft Q
is used". Here a validated SUPPORTS quote that negates a content word
("not", "never", "no longer", "rarely", "seldom", "hardly", optionally with an adverb in
between: "not widely used") which the cited span asserts without a negation becomes an
element "polarity: '<the span's words up to that word>'" for the slot audit's ONE
element-adjudicator call (exact-quote clearing rule): a survivor makes the verdict a
minor partial (unsupported_inference: the relation the claim asserts is not the one the
source states) with a review flag.

Offline scan of the 172 final "supported" gold verdicts (cached answers): it fires on
the TEST pair whose missed partial it targets and on few others; its gain needs live
adjudicator calls and it has no DEV evidence, so it is EXPERIMENTAL: off unless
REFCHECK_V57_ENABLE lists 31 (v57.OPT_IN).
"""

import re

from refcheck.stages.verify_claims import v57

MAX_POLARITY = 2
_SPAN_WORDS = 4  # the cited span's words shown up to the asserted word
_NEGATED = re.compile(
    r"\b(?:not|never|no longer|rarely|seldom|hardly)\s+(?:(?:\w+ly|be|been|being)\s+){0,2}"
    r"(?P<word>[a-z]{4,})\b", re.IGNORECASE)
_SKIP = frozenset({"only", "also", "just", "even", "more", "less", "much", "very", "always",
                   "necessarily", "significantly", "statistically", "different", "known",
                   "well", "clear", "fully", "entirely", "completely", "until", "because",
                   "have", "been", "with", "from", "that", "this", "than", "into", "able",
                   "were"})
_SPAN_NEGATION = re.compile(r"\b(?:not|never|no|nor|without|cannot|lack\w*|fail\w*)\b",
                            re.IGNORECASE)


def _asserted(word: str, cited: str) -> str | None:
    """The cited span's words up to ``word`` when it asserts ``word`` un-negated."""
    words = cited.split()
    for i, token in enumerate(words):
        if re.sub(r"\W", "", token).lower() != word:
            continue
        before = " ".join(words[max(0, i - 3):i])
        if _SPAN_NEGATION.search(before):
            continue
        return " ".join(words[max(0, i - _SPAN_WORDS + 1):i + 1]).strip(" ,;:")
    return None


def polarity_pairs(cited: str, supports: list[str]) -> list[tuple[str, str]]:
    """(cited-span phrase, negated quote phrase) pairs (module doc), <= MAX_POLARITY."""
    if not v57.enabled(31):
        return []
    found: list[tuple[str, str]] = []
    for quote in supports:
        for match in _NEGATED.finditer(quote):
            word = match.group("word").lower()
            if word in _SKIP:
                continue
            phrase = _asserted(word, cited or "")
            if phrase and all(phrase != p for p, _ in found):
                found.append((phrase, " ".join(match.group(0).split())))
    return found[:MAX_POLARITY]
