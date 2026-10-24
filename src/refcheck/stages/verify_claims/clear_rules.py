"""Shared clearing rules for the verifier's dismissal audit, the element adjudicator and
the co-cited union check (V5.6). No imports from the layers, so dismissals.py (run by
layers.run_layer) can use them.

* ``disqualifier``: elements a "wording only" / "author framing" clearance may never
  dismiss. Found by the manual review of 191 "supported" verdicts: a wording/framing
  guard cleared an added time frame ("every year"), a mechanism ("immune rejection"),
  a recommendation attributed to the source and a broadened subject. Such an element
  needs a passage that states it; paraphrase is not enough;
* a clearing quote has >= MIN_QUOTE_WORDS words and is found EXACTLY (similarity
  EXACT after normalisation): a short "quote" is found almost anywhere, and a fuzzy
  match accepts one inverted key word ("did not prolong" -> "did prolong");
* a quote that says an element IS stated (co-cited share, secondary source, "stated
  here") must be ``about_element`` and keep its figures (``figures_kept``).

V5.7 (each part off with REFCHECK_V57_DISABLE, v57.py):

* #3 ``disqualifier(element, quote)`` is diff-based and hedge-aware: it fires only on
  a disqualifying phrase of the element that the clearing quote does not state
  (slot_lexicon.stated_strictly: the phrase's own words, a frequency only by the same
  unit's frequency, a population only by a form of the same one; a cause connective also needs
  its object: "due to poor integration" is not stated by "due to nonunion"; a number
  must be in the quote). A negated quantifier ("not universally", "not all") is a hedge, never an
  added universality; a recommendation / need or exclusivity word in a modal author
  reading ("solely local therapy may still require ...") is the author's hedged
  inference (a cause or mechanism never is: "may down-regulate ... thereby"). It
  also names specificity / exclusivity words ("specific", "only", "selective") and
  causal / relational verbs ("thereby", "down-regulate", "activate", "justify");
* #5 ``about_loose``: for a quote already validated EXACTLY, abbreviations expanded
  from the source's own definitions (abbrev.py), meta words dropped ("goal",
  "role", "strategy"), and >= LOOSE_OVERLAP of the element's content words, at least
  LOOSE_MIN_MATCH of them, in the quote (thresholds fitted on gold DEV only).
"""

import re

from rapidfuzz.utils import default_process

from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.abbrev import expand
from refcheck.stages.verify_claims.bm25 import tokenize
from refcheck.stages.verify_claims.slot_lexicon import phrase_in, stated_strictly

MIN_QUOTE_WORDS = 5  # as the adjudicator prompt asks; a short "quote" is found almost anywhere
EXACT = 1.0  # quote similarity required to clear an element

# Frequency / universality words that are never mere wording (taxonomy G3/G4 disqualifiers).
# Defined here (no layer imports) so the verifier's dismissal audit can import this
# module without importing the layers (adjudicate_prompt re-exports it).
QUANTIFIERS: tuple[str, ...] = ("often", "typically", "widely", "most", "all", "always",
                                "consistently", "universally")

_TIME_FRAME = re.compile(
    r"\b(?:every|each|per|a)\s+(?:year|month|week|day|decade)s?\b|\bannual(?:ly)?\b|\byearly\b"
    r"|\blong[- ]term\b|\b(?:months?|years?|weeks?)[- ]scale\b|\bdecades?\b|\bwithin\s+\d",
    re.IGNORECASE)
_MECHANISM = re.compile(
    r"\b(?:rejection|tolerance|caus(?:e|es|ed|ing)|lead(?:s|ing)?\s+to|result(?:s|ing)?\s+in"
    r"|due\s+to|because|mechanis\w*|mediat\w*|driven\s+by|attributable)\b",
    re.IGNORECASE)
_RECOMMENDATION = re.compile(
    r"\b(?:should|must|need(?:s|ed)?|requir\w*|future|forward[- ]looking|recommend\w*|ought"
    r"|essential|necessary|necessity)\b",
    re.IGNORECASE)
_POPULATION = re.compile(
    r"\b(?:humans?|patients?|clinical(?:ly)?|children|adults?|mice|murine|rats?|primates?|pigs?"
    r"|porcine|dogs?|canine|sheep|ovine|in\s+vivo|in\s+vitro)\b",
    re.IGNORECASE)
# Claim-slot classes (V5.7 #2 slot audit: slot_audit.py); quantifiers are not slots.
SLOT_PATTERNS: dict[str, re.Pattern[str]] = {
    "time frame": _TIME_FRAME, "mechanism": _MECHANISM, "recommendation": _RECOMMENDATION,
    "population": _POPULATION}
_NUMBER = re.compile(r"(?<![A-Za-z-])\d")
# A number starting a token ("40%", "60 days", "2.5-fold"), not one inside a name ("IL-6").
_FIGURE = re.compile(r"(?:^|(?<=[\s(~<>=/]))[-+]?(?P<value>\d+(?:[.,]\d+)?)")
_QUANTIFIER = re.compile(r"\b(?:" + "|".join(re.escape(q) for q in QUANTIFIERS) + r")\b",
                         re.IGNORECASE)


# V5.7 #3: specificity / exclusivity words and causal / relational verbs.
_SPECIFICITY = re.compile(
    r"\b(?:specific(?:ally)?|only|solely|exclusive(?:ly)?|selective(?:ly)?|cell[- ]types?)\b"
    r"|\w-specific\b", re.IGNORECASE)
_RELATIONAL = re.compile(
    r"\b(?:thereby|(?:up|down)[- ]?regulat\w*|activat\w*|inhibit\w*|induc\w*|promot\w*"
    r"|justif\w*|necessit\w*)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|never|no|nor|without)\s+(?:\w+\s+)?$", re.IGNORECASE)
# The author's hedged reading: a modal ("highlighting that X may still require Y").
_MODAL_READING = re.compile(r"\b(?:may|might|could)\b", re.IGNORECASE)
_MODAL_EXEMPT = frozenset({"a recommendation or need", "a specificity or exclusivity qualifier"})
# A cause connective is stated only with its object: "due to poor road access" is not
# stated by a quote "due to storms" (the pattern of a gold DEV case).
_CONNECTIVE = re.compile(r"caus\w*|lead\w*\s+to|result\w*\s+in|due\s+to|because|driven\s+by"
                         r"|attributable|mediat\w*", re.IGNORECASE)
_OBJECT_WORDS = 4
_CLASSES = (("a time frame", _TIME_FRAME), ("a mechanism or cause", _MECHANISM),
            ("a recommendation or need", _RECOMMENDATION),
            ("a population or model", _POPULATION),
            ("a frequency or universality word", _QUANTIFIER))
_EXTENDED = (("a specificity or exclusivity qualifier", _SPECIFICITY),
             ("a mechanism or cause", _RELATIONAL))


def _exempt(reason: str, match: re.Match[str], element: str) -> bool:
    """A negated quantifier, or a need / exclusivity word inside a modal author reading
    (module doc); a cause or mechanism is never exempt ("may down-regulate ... thereby")."""
    if reason == "a frequency or universality word":
        return _NEGATION.search(element[:match.start()]) is not None
    return reason in _MODAL_EXEMPT and _MODAL_READING.search(element) is not None


def _numbers_kept(element: str, quote: str) -> bool:
    numbers = {m.group("value") for m in _FIGURE.finditer(element)}
    return bool(numbers) and all(
        re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", quote) for n in numbers)


def _stated(match: re.Match[str], element: str, quote: str) -> bool:
    """The quote states the phrase; a cause connective ("due to X") also its object."""
    if not stated_strictly(match.group(0), quote):
        return False
    if not _CONNECTIVE.fullmatch(match.group(0)):
        return True
    obj = " ".join(element[match.end():].split()[:_OBJECT_WORDS])
    return not obj.strip() or phrase_in(obj, quote)


def _diff_disqualifier(element: str, quote: str | None) -> str | None:
    """V5.7 #3 (module doc): only a disqualifying phrase the quote does not state."""
    for reason, pattern in (*_CLASSES, *_EXTENDED):
        for match in pattern.finditer(element):
            if _exempt(reason, match, element):
                continue
            if quote is None or not _stated(match, element, quote):
                return reason
    if _NUMBER.search(element) and (quote is None or not _numbers_kept(element, quote)):
        return "a number"
    return None


def disqualifier(element: str, quote: str | None = None) -> str | None:
    """Why ``element`` cannot be cleared as wording/framing (None = it may be);
    ``quote``: the clearing quote (V5.7 #3, module doc)."""
    text = element or ""
    if v57.enabled(3):
        return _diff_disqualifier(text, quote)
    for reason, pattern in (*_CLASSES, ("a number", _NUMBER)):
        if pattern.search(text):
            return reason
    return None


def long_enough(quote: str | None) -> bool:
    """A clearing quote of at least MIN_QUOTE_WORDS words."""
    return quote is not None and len(quote.split()) >= MIN_QUOTE_WORDS


def figures_kept(element: str, quote: str) -> bool:
    """Every number and quantifier word of ``element`` is also in ``quote``."""
    words = set(default_process(element).split()) & set(QUANTIFIERS)
    if not words <= set(default_process(quote).split()):
        return False
    numbers = {m.group("value") for m in _FIGURE.finditer(element)}
    return all(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", quote) for n in numbers)


def about_element(element: str, quote: str) -> bool:
    """More than half of ``element``'s content words (bm25.tokenize: stopwords dropped,
    light stemming) are in ``quote``: a generic sentence clears nothing."""
    wanted = set(tokenize(element))
    return bool(wanted) and 2 * len(wanted & set(tokenize(quote))) > len(wanted)


def states_element(element: str, quote: str) -> bool:
    """``quote`` is about ``element`` and keeps its figures (module doc)."""
    return about_element(element, quote) and figures_kept(element, quote)


LOOSE_OVERLAP = 0.4  # V5.7 #5, fitted on gold DEV union answers
LOOSE_MIN_MATCH = 2  # one shared word ("the primates were") is never "about" an element
META_WORDS = frozenset({"goal", "element", "role", "strategy", "approach", "aim"})


def about_loose(element: str, quote: str, definitions: str = "") -> bool:
    """V5.7 #5 (module doc): ``quote`` (already validated EXACTLY) is about ``element``.
    ``definitions``: source text whose "long form (SF)" definitions expand abbreviations."""
    if about_element(element, quote):
        return True
    if not v57.enabled(5):
        return False
    context = f"{definitions} {element} {quote}"
    wanted = {w for w in tokenize(expand(element, context)) if w not in META_WORDS}
    matched = len(wanted & set(tokenize(expand(quote, context))))
    return matched >= LOOSE_MIN_MATCH and matched >= LOOSE_OVERLAP * len(wanted)
