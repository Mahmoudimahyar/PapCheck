"""The blind slot probe's call (V5.7 #15; slot_probe.py decides when and what follows).

One call, role "adjudicator" (task "verify_slot_probe", prompts/slot_probe.md): the pack
the shown verdict was based on and the cited span with its slot words masked
(slot_probe_rules.masked). A slot becomes a ``Finding`` only when the answer differs
(slot_probe_rules.differs) AND its quote (>= 5 words, sharing a word with the answer) is
found EXACTLY in that pack and is not front matter. Never raises for LLM / budget / time
failures (``ProbeRun.meta.error``).
"""

import logging
import time

from pydantic import BaseModel, Field

from refcheck.llm import CostLimitExceededError, CostTracker, LLMError, call_llm_raw
from refcheck.models.slot_probe import SlotAnswer, SlotProbeOutput
from refcheck.stages.verify_claims.adjudicate import MIN_SECONDS
from refcheck.stages.verify_claims.bm25 import tokenize
from refcheck.stages.verify_claims.clear_rules import EXACT, MIN_QUOTE_WORDS
from refcheck.stages.verify_claims.layer_quotes import ValidatedQuote, validate_quote
from refcheck.stages.verify_claims.layers import LayerResult, PackKind, pack_summary
from refcheck.stages.verify_claims.quote_context import front_matter
from refcheck.stages.verify_claims.retriever import EvidencePack, render_pack
from refcheck.stages.verify_claims.slot_probe_rules import Slot, differs, masked
from refcheck.stages.verify_claims.verifier_helpers import PairContext

logger = logging.getLogger(__name__)

PROBE_LAYER = "slot_probe"
TEMPLATE = "slot_probe"


class Finding(BaseModel):
    """A slot the source fills differently, with the validated quote saying so."""

    slot: Slot
    answer: str
    quote: ValidatedQuote


class ProbeRun(BaseModel):
    """Call metadata (``meta``) + the differing, quoted slots."""

    meta: LayerResult
    findings: list[Finding] = Field(default_factory=list)
    explanation: str = ""


def _finding(ctx: PairContext, pack: EvidencePack, slot: Slot,
             answer: SlotAnswer | None) -> Finding | None:
    if answer is None or answer.quote is None or not differs(slot, answer.answer):
        return None
    quote = answer.quote
    if len(quote.split()) < MIN_QUOTE_WORDS or not set(tokenize(answer.answer)) & set(
            tokenize(quote)) or front_matter(quote, ctx.ref, ctx.doc) is not None:
        return None
    found = validate_quote(answer.passage_id or "", quote, "closest", pack, EXACT)
    return Finding(slot=slot, answer=answer.answer, quote=found) if found is not None else None


def _failed(meta: LayerResult, tracker: CostTracker | None, deadline: float) -> ProbeRun | None:
    if tracker is not None and tracker.total_cost >= tracker.max_cost:
        return ProbeRun(meta=meta.model_copy(update={"error": "cost limit reached",
                                                     "error_kind": "budget"}))
    if deadline - time.monotonic() < 2 * MIN_SECONDS:  # the adjudicator may follow
        return ProbeRun(meta=meta.model_copy(update={"error": "per-pair time budget exhausted",
                                                     "error_kind": "timeout"}))
    return None


async def run_probe(ctx: PairContext, pack: EvidencePack, kind: PackKind, part: str,
                    slots: list[Slot], tracker: CostTracker | None, deadline: float) -> ProbeRun:
    """Ask the source about ``slots`` of ``part``; never raises for LLM/budget/time failures."""
    meta = LayerResult(layer=PROBE_LAYER, role="adjudicator", pack_kind=kind,
                       pack_summary=pack_summary(pack, kind))
    if (skipped := _failed(meta, tracker, deadline)) is not None:
        return skipped
    variables = {"section": "user", "passages": render_pack(pack), "coverage": pack.coverage,
                 "source_title": ctx.ref.title, "masked": masked(part, slots),
                 "slots": [{"number": s.number, "kind": s.kind} for s in slots]}
    try:
        result = await call_llm_raw(
            TEMPLATE, variables, SlotProbeOutput, role="adjudicator", cost_tracker=tracker,
            task=f"verify_{PROBE_LAYER}", timeout=deadline - time.monotonic(),
            system_template=TEMPLATE, system_variables={"section": "system"})
    except CostLimitExceededError as exc:
        return ProbeRun(meta=meta.model_copy(update={"error": f"cost limit reached: {exc}",
                                                     "error_kind": "budget"}))
    except (LLMError, TimeoutError) as exc:
        kind_ = exc.kind if isinstance(exc, LLMError) else "timeout"
        logger.warning("slot probe failed for claim %d / ref %d (%s): %s", ctx.claim.id,
                       ctx.ref.id, kind_, str(exc)[:200])
        return ProbeRun(meta=meta.model_copy(update={
            "error": f"{kind_}: {str(exc)[:300]}", "error_kind": kind_,
            "model_id": getattr(exc, "model_id", None) or ""}))
    meta = meta.model_copy(update={
        "model_id": result.model_id, "model_display": result.display_name or result.model_id,
        "provider": result.provider, "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd, "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens})
    answers = {a.slot: a for a in result.parsed.slots}
    findings = [f for s in slots if (f := _finding(ctx, pack, s, answers.get(s.number)))]
    return ProbeRun(meta=meta, findings=findings,
                    explanation=" ".join(result.parsed.explanation.split()))
