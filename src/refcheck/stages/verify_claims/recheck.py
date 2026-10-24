"""Evidence re-check (taxonomy guard 1, evidence_gap): search the whole paper once more.

On the V4.9 gold set a quarter of the "partial" flags on supported citations
were retrieval misses: the element the verifier called absent was in the
Results, a table or a legend that the standard pack did not include. When the
verifier answers partially_supported / not_supported / contradicted and lists
``unsupported_elements`` on a full text, each element is used as a retrieval
query over the WHOLE document (BM25 + embeddings, rank_units); its best new
windows are added to the standard pack (cap 8,000 tokens) and the verifier is
re-run ONCE on that pack. A decisive second verdict replaces the first for
routing (the cross-check / dispute flow continues from it); guard
"evidence_recheck" is recorded only when the re-run itself is positive and it
cleared an element or upgraded the verdict (a still-negative re-run clears
nothing, whatever the dispute later shows). A re-run that moves a negative
verdict (or one backed by a validated contradicting quote) to the positive
side is never final on its own: it is
cross-checked by another model family and reviewed, and the first run's
contradicting quote is kept in the notes (``overturned`` / ``overturn_note``).
At most one verifier re-run per pair: the insufficient-evidence expanded
re-run (cascade.py) and this re-check never both run.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from refcheck.llm import CostTracker
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.retrieval_pack import assemble_pack
from refcheck.stages.verify_claims.retriever import EvidencePack, rank_units
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import PairContext

logger = logging.getLogger(__name__)

RECHECK_PACK_TOKENS = 8000
PASSAGES_PER_ELEMENT = 2
RECHECK_TOP_N = 30
MIN_RECHECK_SECONDS = 20.0  # leave time for the re-run and a cross-check
RECHECK_VERDICTS = frozenset({"partially_supported", "not_supported", "contradicted"})
_VERDICT_RANK = {"supported": 0, "partially_supported": 1, "not_supported": 2,
                 "contradicted": 2, "not_relevant": 3}
_SAME_ELEMENT = 80  # token_set_ratio: a reworded element is still the same element
_NOTE_QUOTE_CHARS = 240

RerunFn = Callable[[EvidencePack], Awaitable[LayerResult]]


class RecheckOutcome(BaseModel):
    """What the re-check did; ``layer`` is the verifier result to route on."""

    layer: LayerResult
    ran: bool = False
    cleared: list[str] = Field(default_factory=list)  # first-run elements no longer reported
    guard: bool = False  # evidence_recheck applies (an element cleared or verdict upgraded)


def within_budget(tracker: CostTracker | None, deadline: float) -> bool:
    """Enough per-pair time left and the run's cost cap not reached."""
    if deadline - time.monotonic() < MIN_RECHECK_SECONDS:
        return False
    return tracker is None or tracker.total_cost < tracker.max_cost


def wants_recheck(ctx: PairContext, l2: LayerResult, tracker: CostTracker | None,
                  deadline: float) -> bool:
    out = l2.output
    return (out is not None and l2.verdict in RECHECK_VERDICTS
            and bool(out.unsupported_elements) and ctx.coverage == "full_text"
            and l2.pack_kind == "standard" and within_budget(tracker, deadline))


async def targeted_units(ctx: PairContext, elements: list[str],
                         tracker: CostTracker | None) -> list[tuple[int, float]]:
    """Best windows per element over the whole document, skipping those already shown."""
    seen = {idx for p in ctx.pack.passages for idx in (p.unit_idxs or [p.unit_idx])}
    return await element_units(ctx.doc, elements, seen, ctx.use_embeddings, tracker)


async def element_units(doc: SourceDocument, elements: list[str], seen: set[int],
                        use_embeddings: bool, tracker: CostTracker | None,
                        ) -> list[tuple[int, float]]:
    """The best PASSAGES_PER_ELEMENT windows of ``doc`` per element, not in ``seen``
    (updated); also used over co-cited references' documents (cocited_union_pack)."""
    picked: list[tuple[int, float]] = []
    for element in elements:
        try:
            ranking = await rank_units(element, doc, RECHECK_TOP_N, use_embeddings, tracker)
        except Exception:  # a retrieval bug must not fail the pair: skip this element
            logger.exception("Per-element retrieval failed for ref %d", doc.ref_id)
            continue
        added = 0
        for idx, score in ranking.ranked[:ranking.n_candidates]:
            if added >= PASSAGES_PER_ELEMENT:
                break
            if idx not in seen:
                seen.add(idx)
                picked.append((idx, score))
                added += 1
    return picked


def recheck_pack(ctx: PairContext, targeted: list[tuple[int, float]],
                 elements: list[str]) -> EvidencePack:
    """Standard pack windows first (same order), then the targeted ones (<= 8,000 tokens)."""
    standard = [(idx, p.score) for p in ctx.pack.passages if p.kind != "abstract"
                for idx in (p.unit_idxs or [p.unit_idx])]
    return assemble_pack(ctx.doc, standard + targeted, RECHECK_PACK_TOKENS,
                         f"{ctx.pack.retrieval_version}+recheck",
                         used_embeddings=ctx.pack.used_embeddings, query=" | ".join(elements))


def is_listed(element: str, listed: list[str]) -> bool:
    """``element`` (or a rewording of it) is among ``listed``."""
    return any(fuzz.token_set_ratio(element.lower(), r.lower()) >= _SAME_ELEMENT
               for r in listed)


def cleared_elements(before: list[str], after: LayerResult) -> list[str]:
    """First-run elements the re-run no longer reports as unsupported."""
    if after.output is None:
        return []
    if after.verdict == "supported":
        return list(before)
    remaining = after.output.unsupported_elements
    return [e for e in before if not is_listed(e, remaining)]


def upgraded(before: LayerResult, after: LayerResult) -> bool:
    """The re-run's verdict is milder than the first one."""
    first = _VERDICT_RANK.get(before.verdict or "", 9)
    return _VERDICT_RANK.get(after.verdict or "", 9) < first


def overturned(first: LayerResult, second: LayerResult) -> bool:
    """The re-run moved a negative verdict, or one backed by a validated contradicting
    quote, to a milder positive one (needs a cross-check; never final on its own)."""
    if second is first or second.axis != "positive" or not upgraded(first, second):
        return False
    return first.axis == "negative" or bool(first.quotes("contradicts"))


def overturn_note(first: LayerResult) -> str:
    """The first run's verdict and contradicting quote, kept for the reviewer."""
    note = (f"Evidence re-check: the first check said {first.verdict}; the re-run on the "
            "targeted passages found support.")
    quote = next(iter(first.quotes("contradicts")), None)
    if quote is None:
        return note
    text = " ".join(quote.text.split())
    if len(text) > _NOTE_QUOTE_CHARS:
        text = text[:_NOTE_QUOTE_CHARS].rsplit(" ", 1)[0] + " …"
    return f'{note} First-run contradicting quote [{quote.passage_id}]: "{text}"'


async def evidence_recheck(ctx: PairContext, l2: LayerResult, rerun: RerunFn,
                           tracker: CostTracker | None, deadline: float) -> RecheckOutcome:
    """Re-run the verifier once with per-element passages when it applies (module doc)."""
    if not wants_recheck(ctx, l2, tracker, deadline) or l2.output is None:
        return RecheckOutcome(layer=l2)
    elements = list(l2.output.unsupported_elements)
    targeted = await targeted_units(ctx, elements, tracker)
    if not targeted:  # nothing the verifier has not seen: a re-run cannot change much
        return RecheckOutcome(layer=l2)
    ctx.recheck = recheck_pack(ctx, targeted, elements)
    second = await rerun(ctx.recheck)
    if second.output is None or second.axis is None:  # failed / undecided: keep the first
        return RecheckOutcome(layer=l2, ran=True)
    if second.axis != "positive":
        # Still negative: the re-check cleared nothing, even when the re-run reworded or
        # dropped an element (a later dispute may soften the shown verdict to partial).
        return RecheckOutcome(layer=second, ran=True)
    cleared = cleared_elements(elements, second)
    milder, harsher = upgraded(l2, second), upgraded(second, l2)
    return RecheckOutcome(layer=second, ran=True, cleared=cleared,
                          guard=milder or (bool(cleared) and not harsher))
