"""Passages of the co-cited references for the co-cited union check (cocited_union.py).

The element adjudicator only sees each co-cited reference's abstract (<= 250
tokens), which rarely states the specific detail a reviewer found in that
reference's full text. Here each element still absent for THIS reference is
used as a retrieval query over every co-cited reference's loaded source (the
run's own SourceDocument: full text, else its abstract-only document) with the
evidence re-check's per-element retrieval (recheck.element_units: BM25 +
embeddings when available). The reference's abstract unit, then the best windows
of every element taken in turn (each element's best, then each one's second, ...:
the budget cut never drops a later element entirely), are packed per reference
within an equal share of UNION_PACK_TOKENS and labelled by reference number
("R12-A", "R12-P3") so a quote can be checked against exactly the reference it
names.

V5.8 #30 (F9): an element stating a property shortfall ("mechanical properties require
reinforcement", "poor mechanical ...") is searched with deficit terms added
(DEFICIT_TERMS), so a co-cited paper's caveat ("poor mechanical properties compared to
the native tissue") is retrieved. Kept narrow on purpose: a broad limitation trigger
("need", "limited") changed the union request of 7 gold pairs, most of them gold partials.

Skipped: a co-cited reference without a loaded source, a repeated number, this
reference's own number, and a duplicate entry of this reference (same document
fingerprint, e.g. a duplicate inheriting this reference's PDF).
"""

import re

from pydantic import BaseModel

from refcheck.llm import CostTracker
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.cocited import MAX_COCITED
from refcheck.stages.verify_claims.quote_context import header_text
from refcheck.stages.verify_claims.recheck import element_units
from refcheck.stages.verify_claims.retrieval_models import EvidencePack, Passage, passage_label
from refcheck.stages.verify_claims.retrieval_pack import assemble_pack
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import PairContext

UNION_PACK_TOKENS = 3000  # all co-cited references together
DEFICIT_TERMS = "poor weak insufficient limited inadequate"  # V5.8 #30
# A property shortfall: "require(s) reinforcement", "need improved ...", "poor mechanical".
_LIMITATION = re.compile(
    r"\b(?:requir\w*|need\w*)\s+(?:\w+\s+){0,2}?(?:reinforc\w*|improv\w*|enhanc\w*|strengthen\w*)"
    r"|\b(?:poor|weak|insufficient|inadequate)\s+mechanical", re.IGNORECASE)
UNION_VERSION = "cocited-union"


class UnionSource(BaseModel):
    """One co-cited reference's passages, ids prefixed with its number ("R12-P3")."""

    number: int
    title: str = ""
    pack: EvidencePack
    header: str = ""  # its page-1 matter before the abstract (never evidence, V5.6)

    def find(self, passage_id: str | None) -> Passage | None:
        return self.pack.get(passage_id) if passage_id else None


def passage_prefix(number: int) -> str:
    return f"R{number}-"


def _same_document(doc: SourceDocument, own: SourceDocument) -> bool:
    return doc is own or bool(doc.fingerprint and doc.fingerprint == own.fingerprint)


def union_documents(ctx: PairContext) -> list[tuple[int, str, SourceDocument]]:
    """(number, title, document) of each usable co-cited reference, <= MAX_COCITED (module doc)."""
    found: list[tuple[int, str, SourceDocument]] = []
    seen = {ctx.ref.id}
    for ref in ctx.co_cited:
        doc = ctx.co_cited_docs.get(ref.number)
        if doc is None or ref.number in seen or _same_document(doc, ctx.doc):
            continue
        seen.add(ref.number)
        found.append((ref.number, ref.title, doc))
        if len(found) >= MAX_COCITED:
            break
    return found


def _relabel(pack: EvidencePack, number: int) -> EvidencePack:
    passages = [p.model_copy(update={"id": passage_prefix(number) + p.id})
                for p in pack.passages]
    return pack.model_copy(update={"passages": passages})


def search_query(element: str) -> str:
    """The element's retrieval query (V5.8 #30: deficit terms for a limitation)."""
    if v57.enabled(30) and _LIMITATION.search(element):
        return f"{element} {DEFICIT_TERMS}"
    return element


async def _ranked(doc: SourceDocument, elements: list[str], use_embeddings: bool,
                  tracker: CostTracker | None) -> list[tuple[int, float]]:
    """Per-element windows interleaved (every element's best first), so the budget
    cut never drops a later element entirely."""
    if doc.coverage != "full_text":
        return []
    seen: set[int] = set()
    per_element = [await element_units(doc, [search_query(e)], seen, use_embeddings, tracker)
                   for e in elements]
    depth = max((len(units) for units in per_element), default=0)
    return [units[i] for i in range(depth) for units in per_element if i < len(units)]


async def union_sources(ctx: PairContext, elements: list[str],
                        tracker: CostTracker | None) -> list[UnionSource]:
    """Targeted passages of every usable co-cited reference (module doc)."""
    docs = union_documents(ctx)
    if not docs or not elements:
        return []
    budget = UNION_PACK_TOKENS // len(docs)
    out: list[UnionSource] = []
    for number, title, doc in docs:
        ranked = await _ranked(doc, elements, ctx.use_embeddings, tracker)
        pack = assemble_pack(doc, ranked, budget, UNION_VERSION,
                             used_embeddings=ctx.use_embeddings, query=" | ".join(elements))
        if not pack.is_empty:
            out.append(UnionSource(number=number, title=title, pack=_relabel(pack, number),
                                   header=header_text(doc)))
    return out


def _line(passage: Passage) -> str:
    label = "Abstract" if passage.kind == "abstract" else passage_label(passage)
    return f"[{passage.id}] ({label}) {' '.join(passage.text.split())}"


def render_sources(sources: list[UnionSource]) -> list[dict[str, object]]:
    """Template rows: number, title, coverage and the labelled passage lines."""
    return [{"number": s.number, "title": s.title, "coverage": s.pack.coverage,
             "passages": [_line(p) for p in s.pack.passages]} for s in sources]


def union_tokens(sources: list[UnionSource]) -> int:
    return sum(s.pack.total_tokens for s in sources)
