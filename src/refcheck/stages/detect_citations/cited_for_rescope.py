"""Eval parity for cited_for (V5.7 #10 / #14): what the CURRENT detection rules give.

Eval rows carry the cited_for recorded when the manuscript was processed (gold rows)
or none at all (Citation-Integrity rows, whose text marks the cited reference with
<|cit|> / <|multi_cit|> and the others with <|other_cit|>), so a detection change
such as positional attribution (#10) never reached the eval. Both helpers run the
production detector and ``compute_cited_for`` on the row's sentence:

* ``gold_cited_for(sentence, scope, stored, author, year)``: the gold row's cited_for
  under the current rules; ``stored`` unchanged when the rules without #10/#14 do not
  reproduce it (a row recorded by older code is left alone);
* ``placeholder_scope(claim_raw)``: the Citation-Integrity citing sentence and the
  cited reference's cited_for without (``before``) and with (``after``) the V5.7
  rules; None when the cited marker is not found.
"""

import re
from itertools import count

from pydantic import BaseModel

from refcheck.models.citation import CitationInstance
from refcheck.stages.detect_citations.cited_for import cited_for_or_scope, compute_cited_for
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes

_PLACEHOLDER = re.compile(r"<\|(cit|multi_cit|other_cit)\|>")
_BRACKETED = re.compile(r"[\[(]([^\[\]()]*<\|\w+\|>[^\[\]()]*)[\])]")
_OWN = 1


class PlaceholderScope(BaseModel):
    sentence: str  # the citing sentence, markers as "[n]" (the cited reference is [1])
    scope: str  # that sentence without markers (production extracted_claim)
    before: str  # cited_for without the V5.7 rules (cited_for_or_scope form)
    after: str  # cited_for with them (switches as set)

    @property
    def changed(self) -> bool:
        return _norm(self.before) != _norm(self.after)


def gold_cited_for(sentence: str, scope: str, stored: str, author: str,
                   year: int | str | None) -> str:
    """The gold row's cited_for under the current rules (``stored`` if not reproducible)."""
    found = detect_in_paragraph(sentence, 0, "")
    ids = _author_ids(found, _norm(author.split(",")[0]), str(year or "")[:4])
    cits = [c.model_copy(update={"reference_id": rid}) for c, rid in zip(found, ids, strict=True)]
    target = _norm(stored or scope)
    for group in _sentences(cits):
        before = compute_cited_for(group, positional=False, subject=False)
        after = compute_cited_for(group)
        for cit, old, new in zip(group, before, after, strict=True):
            if cit.reference_id == _OWN and _norm(cited_for_or_scope(old, scope)) == target:
                return cited_for_or_scope(new, scope)
    return stored


def placeholder_scope(claim_raw: str) -> PlaceholderScope | None:
    """The cited reference's sentence and cited_for in a Citation-Integrity claim."""
    text = numbered_text(claim_raw)
    cits = [c.model_copy(update={"reference_id": c.number})
            for c in detect_in_paragraph(text, 0, "") if c.number is not None]
    for group in _sentences(cits):
        if not any(c.reference_id == _OWN for c in group):
            continue
        unit = next(u for u in resolve_scopes(group) if u.reference_id == _OWN)
        index = next(i for i, c in enumerate(group) if c.reference_id == _OWN)
        before = compute_cited_for(group, positional=False, subject=False)[index]
        after = compute_cited_for(group)[index]
        return PlaceholderScope(
            sentence=group[0].sentence_text, scope=unit.scope_text,
            before=cited_for_or_scope(before, unit.scope_text),
            after=cited_for_or_scope(after, unit.scope_text))
    return None


def numbered_text(claim_raw: str) -> str:
    """Placeholders as numbered brackets: the cited reference [1], the others [2], [3] ..."""
    others = count(_OWN + 1)

    def numbers(chunk: str) -> list[str]:
        out: list[str] = []
        for kind in _PLACEHOLDER.findall(chunk):
            if kind != "other_cit":  # cit, or multi_cit: shares its bracket with others
                out.append(str(_OWN))
            if kind != "cit":
                out.append(str(next(others)))
        return out

    def bare(match: re.Match[str]) -> str:  # "disease.<|cit|>" -> "disease. [1]"
        space = "" if match.string[match.start() - 1:match.start()].isspace() else " "
        return space + "[" + ", ".join(numbers(match.group(0))) + "]"

    text = _BRACKETED.sub(lambda m: "[" + ", ".join(numbers(m.group(1))) + "]", claim_raw)
    return _PLACEHOLDER.sub(bare, text)


def _author_ids(cits: list[CitationInstance], surname: str, year: str) -> list[int]:
    """Reference ids by (first author, year, number): the row's reference is 1."""
    keys: dict[tuple[str, str, int | None], int] = {}
    ids: list[int] = []
    for cit in cits:
        first = _norm(cit.authors[0]) if cit.authors else ""
        key = (first, (cit.year or "")[:4], cit.number)
        own = bool(surname and first and year) and key[1] == year and (
            first.startswith(surname) or surname.startswith(first))
        ids.append(_OWN if own else keys.setdefault(key, len(keys) + _OWN + 1))
    return ids


def _sentences(cits: list[CitationInstance]) -> list[list[CitationInstance]]:
    groups: dict[tuple[int, int], list[CitationInstance]] = {}
    for cit in cits:
        groups.setdefault((cit.sentence_start, cit.sentence_end), []).append(cit)
    return list(groups.values())


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())
