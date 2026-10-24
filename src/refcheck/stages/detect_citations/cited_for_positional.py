"""V5.7 #10: positional attribution of phrases in multi-marker sentences.

``compute_cited_for`` leaves a marker on the whole sentence (None) when it tags a
noun phrase that shares the sentence's predicate. In "As 3D networks (R1) with
tunable stiffness (R2) and high biocompatibility (R3), hydrogels support tissue
integration." every reference was therefore judged on the other references'
phrases too, and R1 came back partial for not stating R3's biocompatibility.
Citation-scope work (Abu-Jbara & Radev 2012; Fetahu et al. 2017) gives each
phrase to the marker that closes it. For such a marker only:

* a *run* is a chain of marker groups joined by verbless text (no tensed verb, no
  ";", no narrative citation): an enumeration ("including A [1], B [2], and C [3]")
  or noun-phrase markers ("networks (R1) with tunable stiffness (R2)");
* inside the run, the text before each group is that group's phrase (for the first
  group: from the last ","/";"/":" or list cue such as "including" / "such as");
* a verbless phrase under ANOTHER reference's group leaves this reference's
  cited_for. Its own phrases, the frame before the run and the shared main clause
  after it stay: R1 above is cited for "As 3D networks, hydrogels support tissue
  integration", R3 for "high biocompatibility, hydrogels support ...".

Never changed: sentences with one marker group or only this reference's markers,
narrative citations, figure credit lines, and markers ``compute_cited_for``
already narrows. Off with REFCHECK_V57_DISABLE=10.
"""

import re
from collections.abc import Sequence

from refcheck.stages.detect_citations.verb_heuristics import has_verb, words

Span = tuple[int, int]
PROPOSAL = 10

_CUE = re.compile(
    r"(?:(?P<punct>[,;:])|(?<!\w)(?:e\.g\.|i\.e\.)|\b(?:including|includes?|such\s+as|"
    r"namely|for\s+(?:example|instance)|like|especially|particularly|notably)\b)\s*",
    re.IGNORECASE,
)
# The word governing a coordinated list that has no list cue ("data from Germany [1],
# the UK [2] and the US [3]"; "vaccines, developed using mRNA [1] and vectors [2]")
_GOVERNOR = re.compile(
    r"\b(?:from|of|in|on|at|with|for|to|by|between|among|across|using|via|as|against|"
    r"into|onto|within|towards?|than|through|after|before|during|under|without)\s+",
    re.IGNORECASE,
)
_COORDINATED = re.compile(r"^\s*(?:[,;]|(?:and|or|as\s+well\s+as)\b)", re.IGNORECASE)
_RESPECTIVELY = re.compile(r"\brespectively\b", re.IGNORECASE)
_SEPARATOR = re.compile(r"^[\s,;]*(?:(?:and|or|as\s+well\s+as)\s+)?", re.IGNORECASE)
_CREDIT = re.compile(
    r"\b(?:adapted|reproduced|reprinted|modified|redrawn|taken)\s+"
    r"(?:with\s+permission\s+)?from\b",
    re.IGNORECASE,
)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,;:.)\]])")
_REPEATED_PUNCT = re.compile(r"([,;:])(?:\s*[,;:])+")
_NARRATIVE_START = re.compile(r"[A-Za-z]")
_MIN_WORDS = 2


def positional_on() -> bool:
    """#10 is on unless REFCHECK_V57_DISABLE lists it (read on every call)."""
    from refcheck.stages.verify_claims.v57 import enabled  # lazy: no stage import cycle

    return enabled(PROPOSAL)


def positional_clauses(
    sentence: str, groups: Sequence[Span], refs: Sequence[int | None],
    located: Sequence[int | None], clauses: Sequence[str | None],
) -> dict[int, str]:
    """Citation index -> its positional clause, for citations still on the whole sentence.

    ``refs[i]``: citation i's reference id; ``located[i]``: the index of its marker
    group (None: not located, or narrative); ``clauses``: compute_cited_for's result.
    """
    out: dict[int, str] = {}
    for i, (ref, own) in enumerate(zip(refs, located, strict=True)):
        if clauses[i] is not None or own is None:
            continue
        mine = [k == own or (ref is not None and any(
            r == ref and g == k for r, g in zip(refs, located, strict=True)))
            for k in range(len(groups))]
        clause = positional_clause(sentence, groups, mine, own)
        if clause is not None:
            out[i] = clause
    return out


def positional_clause(
    sentence: str, groups: Sequence[Span], mine: Sequence[bool], own: int,
) -> str | None:
    """The sentence without the run phrases of other references' groups.

    ``groups``: the sentence's merged marker groups in order; ``mine[i]``: group i
    cites this reference; ``own``: the group of this citation. None = no change.
    """
    if len(groups) < 2 or _narrative(sentence, groups[own]) or _CREDIT.search(sentence) \
            or _RESPECTIVELY.search(sentence):  # "A [1] and B [2] gave 2 and 3%, respectively"
        return None
    first, last = _run(sentence, groups, own)
    phrases = _phrases(sentence, groups, first, last)
    dropped = {k for k, (start, end) in zip(range(first, last + 1), phrases, strict=True)
               if not mine[k] and _removable(sentence[start:end])}
    if not dropped:
        return None
    text = _assemble(sentence, phrases, first, dropped, groups[last][1])
    return text if len(words(text)) >= _MIN_WORDS else None


def _narrative(sentence: str, group: Span) -> bool:
    """A narrative marker ("Lee et al. (2019)") is a subject, not a closing tag."""
    return bool(_NARRATIVE_START.match(sentence[group[0]:group[0] + 1]))


def _joined(sentence: str, groups: Sequence[Span], i: int) -> bool:
    """Groups i and i+1 belong to one enumeration / noun-phrase chain."""
    if _narrative(sentence, groups[i]) or _narrative(sentence, groups[i + 1]):
        return False
    gap = sentence[groups[i][1]:groups[i + 1][0]]
    return ";" not in gap and not has_verb(gap)


def _run(sentence: str, groups: Sequence[Span], own: int) -> Span:
    """First and last group index of the chain around ``own``."""
    first = own
    while first > 0 and _joined(sentence, groups, first - 1):
        first -= 1
    last = own
    while last + 1 < len(groups) and _joined(sentence, groups, last):
        last += 1
    return first, last


def _phrases(sentence: str, groups: Sequence[Span], first: int, last: int) -> list[Span]:
    """Per group of the run, the span of the phrase it closes."""
    spans = [(_head_start(sentence, groups, first, last), groups[first][0])]
    spans += [(groups[k - 1][1], groups[k][0]) for k in range(first + 1, last + 1)]
    return spans


def _head_start(sentence: str, groups: Sequence[Span], first: int, last: int) -> int:
    """Where the run's first phrase starts: after the last list cue; in a coordinated
    list ("A [1], B [2]") with no cue word, after the word governing the list."""
    head_from = groups[first - 1][1] if first > 0 else 0
    end = groups[first][0]
    cues = list(_CUE.finditer(sentence, head_from, end))
    start = cues[-1].end() if cues else head_from
    gap = sentence[groups[first][1]:groups[first + 1][0]] if last > first else ""
    items_governed = _GOVERNOR.match(_SEPARATOR.sub("", gap, count=1))  # "by X [1] or via Y"
    if _COORDINATED.match(gap) and not items_governed and (not cues or cues[-1].group("punct")):
        governor = _GOVERNOR.search(sentence, start, end)
        start = governor.end() if governor else start
    return start


def _removable(phrase: str) -> bool:
    """A noun phrase / list item (a phrase with a tensed verb is a shared clause)."""
    return bool(words(phrase)) and not has_verb(phrase)


def _assemble(
    sentence: str, phrases: list[Span], first: int, dropped: set[int], run_end: int,
) -> str:
    """Frame + kept run phrases + the text after the run, tidied."""
    parts = [sentence[:phrases[0][0]]]
    kept_any = False
    for k, (start, end) in zip(range(first, first + len(phrases)), phrases, strict=True):
        if k in dropped:
            continue
        phrase = sentence[start:end]
        if not kept_any and k != first:  # the separator joined it to a dropped phrase
            phrase = " " + _SEPARATOR.sub("", phrase, count=1)
        parts.append(phrase)
        kept_any = True
    parts.append(sentence[run_end:])
    return tidy(" ".join(parts))


def tidy(text: str) -> str:
    """Whitespace and punctuation left behind by removed phrases and markers."""
    text = " ".join(text.split())
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _REPEATED_PUNCT.sub(r"\1", text).strip()
