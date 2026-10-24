"""V5.8 round-2 clearing-rule refinements of the element adjudicator and the co-cited
union check (G6). Each is off with REFCHECK_V57_DISABLE=<n> (v57.py); none changes a
model request. Measured with a free offline cache replay of the 281 gold pairs.

* #21 (F2) ``edge_trimmed``: a clearing quote not found exactly is retried once without
  leading / trailing function words ("a", "the", "and" ...). The model had quoted
  "a bipedal, ..." where the source reads "...s bipedal, ...": the content must still
  match exactly and keep MIN_QUOTE_WORDS words.
* #22 (F3) ``hedged_stated``: a "stated" answer whose own note concedes the source does
  not state it ("not explicitly", "weak match", "paraphrase-level", "only by inference")
  is treated as "overstated": the element survives.
* #24 (F5) ``twin_of`` (opt-in, v57.OPT_IN): an "absent" / "cocited" survivor that
  restates an element already cleared with a quote for the same pair: every content word
  (5-character stems) of each side is matched on the other side (>= TWIN_COVERAGE of the
  cleared one), and neither side has an unmatched negation, quantifier, exclusivity,
  number or population word ("not", "always", "alone", "human" ...). The twin's
  clearance carries no quote, so it never releases a dispute (adjudicate_result.released).
* #25 (F6) ``about_parts`` (opt-in): the union's about-check (clear_rules.about_loose)
  also accepts one disjunct of "X or Y" / "X/Y" (>= half its content words) and an
  all-caps short form spelled by the initials of consecutive CONTENT words of the quote,
  no word skipped ("FBR" = "foreign body reaction"; never "For Both Rats"). Prefix
  stemming was rejected: it cleared 3 gold-partial elements for every gold-supported one.
* #27 (F8) ``overstated_as_wording``: an "overstated" element with no quantifier,
  absolute / exclusive word or number, whose note itself calls the difference wording
  ("slightly stronger wording", "paraphrase") and gives no counter-data, is re-checked
  as "wording" (the disqualifier and the exact quote still apply). A note that names a
  stronger claim ("the source only says anti-inflammatory") keeps it overstated.
"""

import os
import re

from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.abbrev import expand
from refcheck.stages.verify_claims.bm25 import STOPWORDS, tokenize
from refcheck.stages.verify_claims.clear_rules import META_WORDS, about_loose

_EDGE_WORDS = frozenset({"a", "an", "the", "and", "of", "to", "in", "that", "which", "with",
                         "for", "by", "as", "is", "are"})
_HEDGE = re.compile(r"not explicitly|does not explicitly|weak match|paraphrase-level"
                    r"|only by inference", re.IGNORECASE)
_TRIGGER = re.compile(
    r"\b(often|frequently|commonly|usually|typically|generally|widely|most|all|always|never|"
    r"universally|consistently|many|every|alone|solely|sole|only|exclusively|entirely|exactly|"
    r"guarantee\w*|eliminat\w*|prove[nd]?|cure\w*|complete(ly)?|fully|any|no|none)\b|\d",
    re.IGNORECASE)
_COUNTER = re.compile(r"not associated|counter|contrary|opposite|in vitro|preliminary|speculat"
                      r"|future|limit(ed|s)? (to|its)|explicitly (says|states|notes)",
                      re.IGNORECASE)
_WORDING_NOTE = re.compile(r"\b(wording|word choice|phrasing|paraphras\w*|rephras\w*|synonym\w*"
                           r"|slightly stronger|stylistic)\b", re.IGNORECASE)
# Words a near-duplicate may not add or drop (#24): negation, quantifier, exclusivity,
# population / model.
_TWIN_GUARD = re.compile(
    r"^(not|no|never|without|none|neither|nor|cannot|fail\w*|lack\w*|often|frequently|"
    r"commonly|usually|typically|generally|widely|most|all|always|universally|consistently|"
    r"many|every|each|any|some|few|alone|solely|sole|only|exclusively|entirely|completely|"
    r"fully|totally|human|humans|patients?|clinical|children|adults?|mice|mouse|murine|"
    r"rats?|rodents?|porcine|pigs?|primates?|dogs?|canine|rabbits?|vitro|vivo)$|\d")
_DISJUNCTION = re.compile(r"\s+or\s+|/")
_SHORT_FORM = re.compile(r"\b[A-Z][A-Z0-9]{1,5}s?\b")
_STEM = 5
TWIN_COVERAGE = 0.75


def edge_trimmed(quote: str) -> str:
    """``quote`` without leading / trailing function words (#21)."""
    words = quote.split()
    while words and words[0].lower() in _EDGE_WORDS:
        words = words[1:]
    while words and words[-1].lower().strip(".,;") in _EDGE_WORDS:
        words = words[:-1]
    return " ".join(words)


def hedged_stated(category: str, note: str) -> bool:
    """#22: a "stated" answer its own note hedges."""
    return v57.enabled(22) and category == "stated" and _HEDGE.search(note or "") is not None


def overstated_as_wording(category: str, element: str, note: str) -> bool:
    """#27: an "overstated" answer without a trigger word whose note calls the difference
    wording and gives no counter-data (module doc)."""
    text = note or ""
    return v57.enabled(27) and category == "overstated" and not _TRIGGER.search(element) \
        and _WORDING_NOTE.search(text) is not None and not _COUNTER.search(text)


def _same(a: str, b: str) -> bool:
    return a == b or (len(a) >= _STEM and len(b) >= _STEM
                      and len(os.path.commonprefix([a, b])) >= _STEM)


def _covered(words: list[str], other: list[str]) -> float:
    return sum(any(_same(a, b) for b in other) for a in words) / len(words) if words else 0.0


def _raw(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def is_twin(survivor: str, cleared: str) -> bool:
    """#24: ``survivor`` restates ``cleared`` (module doc): a symmetric content match and
    no guard word on either side the other lacks."""
    words, other = tokenize(survivor), tokenize(cleared)
    if len(words) < 2 or survivor == cleared:
        return False
    if _covered(words, other) < 1.0 or _covered(other, words) < TWIN_COVERAGE:
        return False
    mine, theirs = _raw(survivor), _raw(cleared)
    return not any(_TWIN_GUARD.search(w) for w in mine ^ theirs)


TWIN_CATEGORIES = frozenset({"absent", "cocited"})  # never overstated / broadened / contradicted


def twin_of(survivor: str, cleared: list[tuple[str, str | None]],
            category: str = "absent") -> str | None:
    """#24: the first cleared element (with a quote) ``survivor`` repeats, else None;
    only for an "absent" / "cocited" survivor (``category``)."""
    if not v57.enabled(24) or category not in TWIN_CATEGORIES:
        return None
    return next((el for el, quote in cleared if quote and is_twin(survivor, el)), None)


def _initialism_in(short: str, quote: str) -> bool:
    """``short`` is spelled by the initials of consecutive content words of ``quote``
    (no stop word, no word skipped)."""
    letters = short.rstrip("s").lower()
    words = re.findall(r"[A-Za-z]+", quote)
    n = len(letters)
    return any(all(w.lower() not in STOPWORDS for w in words[i:i + n])
               and "".join(w[0].lower() for w in words[i:i + n]) == letters
               for i in range(len(words) - n + 1))


def _part_matches(part: str, quote: str, definitions: str) -> tuple[int, int]:
    """(content words of ``part`` in ``quote`` + initialisms spelled there, content words)."""
    context = f"{definitions} {part} {quote}"
    wanted = [w for w in dict.fromkeys(tokenize(expand(part, context))) if w not in META_WORDS]
    quoted = tokenize(expand(quote, context))
    matched = sum(1 for w in wanted if w in quoted)
    for short in _SHORT_FORM.findall(part):
        if short.lower() in tokenize(short) and _initialism_in(short, quote) \
                and not any(_same(t, short.lower()) for t in quoted):
            matched += 1
    return matched, len(wanted)


def about_parts(element: str, quote: str, definitions: str = "") -> bool:
    """clear_rules.about_loose, plus #25's disjuncts and initialisms (module doc)."""
    if about_loose(element, quote, definitions):
        return True
    if not v57.enabled(25) or not v57.enabled(5):  # extends #5's loose check
        return False
    parts = [element]
    if _DISJUNCTION.search(element):
        parts += [p for p in _DISJUNCTION.split(element) if p.strip()]
    for n, part in enumerate(parts):
        matched, wanted = _part_matches(part, quote, definitions)
        if not wanted:
            continue
        if matched >= 2 and matched >= 0.4 * wanted:
            return True
        if n > 0 and matched >= 1 and matched >= 0.5 * wanted:
            return True
    return False
