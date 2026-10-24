"""Which clause of a sentence each citation marker is cited for.

Every reference used to be judged against the WHOLE sentence, so in "A does
X (Ref1) and Y (Ref2)." Ref1 was "not supported" for failing to show Y.
Rule: a marker group that closes a clause (followed by punctuation or a
conjunction, or at the end) covers the text from the previous such group —
or the sentence start — up to itself. A marker embedded in a noun phrase
("Hydrogels (Ref1) are used ...") narrows nothing, and narrative citations
keep their own scope. ``None`` means "the whole sentence".
V5.7: positional attribution in marker chains (#10, cited_for_positional.py) and an
opt-in sentence subject for verb-initial clauses (#14, cited_subject.py).
"""

import re

from pydantic import BaseModel

from refcheck.models.citation import CitationInstance
from refcheck.stages.detect_citations.author_year_detector import (
    detect_author_year_narrative,
    detect_author_year_parenthetical,
)
from refcheck.stages.detect_citations.cited_for_positional import (
    positional_clauses,
    positional_on,
)
from refcheck.stages.detect_citations.cited_subject import subject_prepend_on, with_subject
from refcheck.stages.detect_citations.numbered_detector import (
    detect_numbered_bracket,
    detect_numbered_superscript,
)
from refcheck.stages.detect_citations.verb_heuristics import has_verb, words

_GAP_INSIDE_GROUP = re.compile(r"^[\s,;]*$")
_CLOSING_PUNCT = ".;:,!?)]–—"
_CLAUSE_WORD = re.compile(
    r"(?:and|or|but|while|whilst|whereas|which|although|though|yet|nor|thus|"
    r"thereby|respectively|as\s+well\s+as)\b",
    re.IGNORECASE,
)
_LEADING_CONNECTOR = re.compile(r"^(?:and|or|but|as\s+well\s+as)\s+", re.IGNORECASE)
_LEFTOVER_MARKER = re.compile(r"\s*\([^()]*\d{4}[a-z]?[^()]*\)|\s*\[\d+[^\]]*\]")
_MIN_WORDS_WITHOUT_VERB = 2


class _Group(BaseModel):
    start: int
    end: int
    closes_clause: bool = False


def compute_cited_for(
    group: list[CitationInstance], positional: bool | None = None, subject: bool | None = None,
) -> list[str | None]:
    """Per citation of one sentence: the narrowed clause, or None (whole sentence).

    ``positional`` (#10) / ``subject`` (#14) force those rules on or off; None reads
    their switches (REFCHECK_V57_DISABLE / REFCHECK_SUBJECT_PREPEND).
    """
    sentence = group[0].sentence_text if group else ""
    if not sentence:
        return [None] * len(group)
    spans = _scan_markers(sentence, {c.style for c in group})
    own = [_locate(c, sentence, spans) for c in group]
    groups = _group_spans(sorted(spans | {s for s in own if s}), sentence)
    tail = clean_clause(sentence[groups[-1].end:]) if groups else ""
    tail_has_predicate = has_verb(tail)
    clauses = [
        None if c.is_narrative or span is None
        else _clause_for(span, groups, sentence, tail_has_predicate)
        for c, span in zip(group, own, strict=True)
    ]
    if positional_on() if positional is None else positional:
        clauses = _with_positions(group, own, groups, sentence, clauses)
    if subject_prepend_on() if subject is None else subject:
        bare = clean_clause(sentence)
        clauses = [with_subject(c, bare) if c else c for c in clauses]
    return clauses


def _with_positions(
    group: list[CitationInstance], own: list[tuple[int, int] | None], groups: list[_Group],
    sentence: str, clauses: list[str | None],
) -> list[str | None]:
    """#10: citations left on the whole sentence lose other references' list phrases."""
    located = [None if c.is_narrative or s is None else _group_index(s, groups)
               for c, s in zip(group, own, strict=True)]
    found = positional_clauses(sentence, [(g.start, g.end) for g in groups],
                               [c.reference_id for c in group], located, clauses)
    return [(clean_clause(found[i]) or None) if i in found else clause
            for i, clause in enumerate(clauses)]


def _group_index(span: tuple[int, int], groups: list[_Group]) -> int | None:
    return next((i for i, g in enumerate(groups) if g.start <= span[0] < g.end), None)


def cited_for_or_scope(clause: str | None, scope: str) -> str:
    """The narrowed clause, or the scope when it is (textually) the whole scope."""
    if not clause or _alnum(clause) == _alnum(scope):
        return scope
    return clause


def _alnum(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def clean_clause(text: str) -> str:
    """Clause text without markers, edge punctuation or a leading "and"/"or"."""
    cleaned = " ".join(_LEFTOVER_MARKER.sub("", text).split())
    cleaned = cleaned.lstrip(" ,;:.)]–—")
    cleaned = _LEADING_CONNECTOR.sub("", cleaned)
    return cleaned.rstrip(" ,;:.([–—").strip()


def _clause_for(
    span: tuple[int, int], groups: list[_Group], sentence: str, tail_has_predicate: bool,
) -> str | None:
    index = next((i for i, g in enumerate(groups) if g.start <= span[0] < g.end), None)
    if index is None or not groups[index].closes_clause:
        return None
    previous = [g for g in groups[:index] if g.closes_clause]
    start = previous[-1].end if previous else 0
    clause = clean_clause(sentence[start:groups[index].start])
    if not clause:
        return None
    if has_verb(clause):
        return clause
    # A verbless clause tagging a subject or context is not narrowed: "Drug X (Ref1)
    # and Drug Y (Ref2) both reduce rejection" (shared predicate after the last
    # marker), "Hydrogels, e.g. alginate (Ref1), reduce rejection (Ref2)" or "In
    # islets (Ref1), gels reduce hypoxia (Ref2)" (predicate right after the marker).
    # Narrowing Ref1 to the noun phrase would let a paper that merely mentions it
    # count as support. List items ("include A (R1), B (R2), and C (R3)") still are.
    if len(words(clause)) < _MIN_WORDS_WITHOUT_VERB or tail_has_predicate \
            or _predicate_follows(groups, index, sentence):
        return None
    return clause


def _predicate_follows(groups: list[_Group], index: int, sentence: str) -> bool:
    """A verb right after the marker group (before the next marker or a ";"), not
    introduced by "and"/"or"/"but" (which would start the next list item)."""
    end = groups[index + 1].start if index + 1 < len(groups) else len(sentence)
    segment = sentence[groups[index].end:end].split(";")[0].lstrip(" ,:)]–—")
    if _LEADING_CONNECTOR.match(segment):
        return False
    return has_verb(clean_clause(segment))


def _scan_markers(sentence: str, styles: set[str]) -> set[tuple[int, int]]:
    """Spans of every citation marker in the sentence (mapped or not)."""
    found: list[CitationInstance] = []
    if styles & {"author_year_parenthetical", "author_year_narrative"}:
        found += detect_author_year_parenthetical(sentence, 0, "")
        found += detect_author_year_narrative(sentence, 0, "")
    if "numbered_bracket" in styles:
        found += detect_numbered_bracket(sentence, 0, "")
    if "numbered_superscript" in styles:  # never otherwise: "cm²" is not a citation
        found += detect_numbered_superscript(sentence, 0, "")
    return {(c.char_start, c.char_end) for c in found}


def _locate(
    cit: CitationInstance, sentence: str, spans: set[tuple[int, int]],
) -> tuple[int, int] | None:
    """The marker span of this citation inside the sentence."""
    start, end = cit.char_start - cit.sentence_start, cit.char_end - cit.sentence_start
    if 0 <= start < end <= len(sentence):
        hit = next((s for s in spans if s[0] < end and start < s[1]), None)
        if hit or sentence[start:start + 1] in "([⁰¹²³⁴⁵⁶⁷⁸⁹":
            return hit or (start, end)
    pos = sentence.find(cit.raw_marker) if cit.raw_marker else -1
    if pos >= 0:
        return next((s for s in spans if s[0] <= pos < s[1]), (pos, pos + len(cit.raw_marker)))
    key = [k for k in (cit.authors[:1] + [cit.year or ""]) if k]
    return next((s for s in spans if key and all(k in sentence[s[0]:s[1]] for k in key)), None)


def _group_spans(spans: list[tuple[int, int]], sentence: str) -> list[_Group]:
    """Merge overlapping/adjacent marker spans; mark groups that close a clause."""
    groups: list[_Group] = []
    for start, end in spans:
        if groups and (start <= groups[-1].end
                       or _GAP_INSIDE_GROUP.match(sentence[groups[-1].end:start])):
            groups[-1] = groups[-1].model_copy(update={"end": max(end, groups[-1].end)})
        else:
            groups.append(_Group(start=start, end=end))
    return [g.model_copy(update={"closes_clause": _closes_clause(sentence[g.end:])})
            for g in groups]


def _closes_clause(following: str) -> bool:
    rest = following.lstrip()
    if not rest or rest[0] in _CLOSING_PUNCT:
        return True
    return bool(_CLAUSE_WORD.match(rest))
