"""References cited in the same sentence as a pair's reference (taxonomy guard 2).

The verifier sees the other references of the citing sentence (number, title,
abstract when known) so it can judge only THIS reference's share: an element
another reference states is not this reference's problem (cocited_share).
Claims are one per (sentence, reference), so the sentence's references are
gathered across claims with the same paragraph and sentence text. Each pair also
keeps the co-cited references' loaded sources (``co_cited_documents``) for the
co-cited full-text union check after the element adjudicator.
"""

from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.retrieval_pack import truncate_to_tokens
from refcheck.stages.verify_claims.source_models import SourceDocument

MAX_COCITED = 3
COCITED_ABSTRACT_TOKENS = 250

SentenceKey = tuple[int, str]
PairKey = tuple[int, int]


class CoCitedRef(BaseModel):
    """Another reference cited in the same sentence."""

    number: int
    title: str = ""
    abstract: str | None = None  # truncated to ~250 tokens (COCITED_ABSTRACT_TOKENS)


def co_cited_ref(number: int, title: str | None, abstract: str | None) -> CoCitedRef:
    """A CoCitedRef with a whitespace-normalised, truncated abstract."""
    text = " ".join((abstract or "").split())
    return CoCitedRef(number=number, title=" ".join((title or "").split()),
                      abstract=truncate_to_tokens(text, COCITED_ABSTRACT_TOKENS) or None)


def sentence_key(claim: Claim) -> SentenceKey:
    """Identity of the citing sentence (paragraph index + normalised text)."""
    paragraph = claim.location.paragraph_index if claim.location is not None else -1
    return paragraph, " ".join(claim.manuscript_text.lower().split())


def sentence_references(claims: Iterable[Claim]) -> dict[SentenceKey, list[int]]:
    """Reference ids per citing sentence, in order of first appearance."""
    groups: dict[SentenceKey, list[int]] = {}
    for claim in claims:
        ids = groups.setdefault(sentence_key(claim), [])
        ids.extend(rid for rid in claim.reference_ids if rid not in ids)
    return groups


def _same_paper(ref_id: int, other: Reference, refs: Mapping[int, Reference]) -> bool:
    """A duplicate entry in either direction is the same paper, not a co-cited one."""
    this = refs.get(ref_id)
    return other.id == ref_id or other.duplicate_of == ref_id or (
        this is not None and this.duplicate_of == other.id)


def _others(ref_id: int, ids: list[int], refs: Mapping[int, Reference]) -> list[CoCitedRef]:
    out: list[CoCitedRef] = []
    for other_id in ids:
        other = refs.get(other_id)
        if other is None or _same_paper(ref_id, other, refs):
            continue
        out.append(co_cited_ref(other.id, other.title, other.abstract_text))
        if len(out) >= MAX_COCITED:
            break
    return out


def co_cited_map(claims: Iterable[Claim], refs: Mapping[int, Reference],
                 ) -> dict[PairKey, list[CoCitedRef]]:
    """(claim id, reference id) -> the other references of that claim's sentence."""
    claims = list(claims)
    groups = sentence_references(claims)
    out: dict[PairKey, list[CoCitedRef]] = {}
    for claim in claims:
        ids = groups[sentence_key(claim)]
        for ref_id in claim.reference_ids:
            others = _others(ref_id, ids, refs)
            if others:
                out[(claim.id, ref_id)] = others
    return out


def co_cited_documents(co_cited: Iterable[CoCitedRef], docs: Mapping[int, SourceDocument],
                       ) -> dict[int, SourceDocument]:
    """The loaded source (full text, else abstract) of each co-cited reference that has one.

    The same SourceDocument objects the run already holds (no copy, no re-parse): the
    co-cited union check (cocited_union.py) searches them for elements absent here.
    """
    return {ref.number: docs[ref.number] for ref in co_cited if ref.number in docs}
