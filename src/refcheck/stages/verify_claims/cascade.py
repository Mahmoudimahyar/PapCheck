"""Routing for one sourced pair (V5.1): verifier decides, negatives are cross-checked.

Chosen by replay (Citation-Integrity test, 200 pairs): the cheap verifier alone beat
every verifier->judge cascade at 1/20th of the cost. First, a partial / negative verdict
on a full text listing unsupported elements gets ONE evidence re-check (recheck.py; a
decisive second verdict is routed instead). A re-run that overturns a negative (or
contradicted-by-quote) verdict is cross-checked and reviewed; a re-checked verdict is
never labelled as decided by the screen.

Rules: a clear-eligible "supported" with a validated supports quote is final (screen);
a positive with a validated supports quote and no screen conflict is final (verifier);
"insufficient" on full text is re-run once on the expanded pack, then cannot_verify.
A negative gets a BLIND cross-family check ("confirm"): agreement confirms it;
disagreement is "disputed", reviewed, shown as dispute.disputed_verdict. Unusual
positives (no validated quote, a screen conflict / topic mismatch, a "supported" still
listing elements) get the same cross-check (escalation.py; opt-in: judge). Partials go
once to the element adjudicator (adjudicate_apply.py). V5.7: a re-checked "supported"
whose upgrade is not final goes to it with the first run's elements (#1); a same-element
re-run keeps the first type (#11); a fragment span is never cleared to supported (#7);
a weak "supported" is flagged "check first" (#9). V5.8: colour-key reads run off-loop.
"""

import asyncio
import os
import time

from pydantic import BaseModel, Field

from refcheck.llm import CostTracker, Role
from refcheck.models.claim import Claim
from refcheck.models.verification import DecidedBy
from refcheck.stages.verify_claims.adjudicate_apply import AdjudicationSummary, adjudicate_outcome
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.check_first import check_first_outcome
from refcheck.stages.verify_claims.escalation import (
    cross_check_negative,
    cross_check_overturn,
    cross_check_positive,
    judge_positive,
)
from refcheck.stages.verify_claims.figure_key import colour_finding
from refcheck.stages.verify_claims.fragment import hold_fragment
from refcheck.stages.verify_claims.layers import LayerResult, PackKind, cited_for, run_layer
from refcheck.stages.verify_claims.partial_fields import uncovered_elements
from refcheck.stages.verify_claims.recheck import evidence_recheck, overturned
from refcheck.stages.verify_claims.recheck_closure import close_recheck, keep_first_type
from refcheck.stages.verify_claims.retriever import EvidencePack, expanded_pack
from refcheck.stages.verify_claims.screen import ScreenResult, clear_gates, screen_conflicts
from refcheck.stages.verify_claims.verifier_helpers import PairContext


class CascadeOutcome(BaseModel):
    """Final routing decision for a pair (before post-processing)."""

    verdict: str  # a layer verdict, or "cannot_verify"
    label_layer: LayerResult | None = None  # layer whose verdict/explanation is used
    decided_by: DecidedBy = "none"
    consensus_type: str = ""
    tier: int = 1
    layers: list[LayerResult] = Field(default_factory=list)
    layer_path: list[str] = Field(default_factory=list)
    needs_review: bool = False
    notes: list[str] = Field(default_factory=list)
    cv_reason: str | None = None
    error: str | None = None
    clear_eligible: bool = False
    failed_gates: list[str] = Field(default_factory=list)
    guards: list[str] = Field(default_factory=list)  # pipeline guards ("evidence_recheck")
    recheck_cleared: list[str] = Field(default_factory=list)  # no longer reported (re-check)
    adjudication: AdjudicationSummary | None = None  # element adjudicator (V5.5)


def focus_query(claim: Claim, claim_text: str) -> str:
    """Retrieval query: the clause THIS reference is cited for (when the sentence
    narrows it) first, then the whole sentence for context."""
    part = cited_for(claim, claim_text)
    return f"{part} {claim_text}" if part else claim_text


async def ensure_expanded(ctx: PairContext, cost_tracker: CostTracker | None) -> EvidencePack:
    """Expanded pack (<= 8,000 tokens), computed once per pair (focus_query)."""
    if ctx.expanded is None:
        query = focus_query(ctx.claim, ctx.claim_text)
        ctx.expanded = ctx.pack if ctx.coverage != "full_text" else await expanded_pack(
            query, ctx.doc, cost_tracker=cost_tracker)
    return ctx.expanded


def verifier_final(l2: LayerResult, eligible: bool, screen: ScreenResult | None,
                   thresholds: ScreenThresholds) -> tuple[DecidedBy, str, int] | None:
    """(decided_by, consensus_type, tier) when a positive verifier result is final.

    A re-checked verdict (pack "recheck") needed more than the screen saw, so it is
    never labelled screen_clear. A "supported" still listing elements no validated
    dismissal clears is an unusual positive (cross-checked, elements kept).
    """
    if l2.output is None or l2.axis != "positive" or not l2.quotes("supports"):
        return None
    if l2.verdict == "supported" and uncovered_elements(l2.output):
        return None
    if eligible and l2.verdict == "supported" and l2.pack_kind != "recheck":
        return "screen", "screen_clear", 1
    if not screen_conflicts(screen, thresholds):
        return "verifier", "verifier", 2
    return None


class _Run:
    def __init__(self, ctx: PairContext, screen: ScreenResult | None,
                 thresholds: ScreenThresholds, cost_tracker: CostTracker | None,
                 deadline: float) -> None:
        self.ctx, self.screen, self.thresholds = ctx, screen, thresholds
        self.tracker, self.deadline = cost_tracker, deadline
        self.first: LayerResult | None = None  # the first verifier run, once re-checked
        self.rechecked: LayerResult | None = None  # the re-check's re-run (recheck.py)
        eligible, failed = clear_gates(ctx.claim, ctx, screen, thresholds)
        self.out = CascadeOutcome(verdict="cannot_verify", clear_eligible=eligible,
                                  failed_gates=failed,
                                  layer_path=["screen"] if screen and screen.ok else [])

    async def layer(self, role: Role, layer: str, pack: EvidencePack,
                    expanded: bool, model: str | None = None,
                    kind: PackKind | None = None) -> LayerResult:
        template = "judge_claim" if role == "judge" else "verify_claim"
        result = await run_layer(
            role, pack, self.ctx.claim, self.ctx, template, layer=layer,
            pack_kind=kind or ("expanded" if expanded else "standard"),
            cost_tracker=self.tracker, timeout=self.deadline - time.monotonic(), model=model)
        self.out.layers.append(result)
        self.out.layer_path.append(layer)
        return result

    async def recheck(self, l2: LayerResult) -> LayerResult:
        """Evidence re-check of a partial / negative verdict (recheck.py)."""
        async def rerun(pack: EvidencePack) -> LayerResult:
            return await self.layer("verifier", "verifier_recheck", pack, expanded=False,
                                    kind="recheck")

        res = await evidence_recheck(self.ctx, l2, rerun, self.tracker, self.deadline)
        if res.guard:
            self.out.guards.append("evidence_recheck")
            self.out.recheck_cleared = res.cleared
        if res.ran:
            self.first, self.rechecked = l2, res.layer
        return keep_first_type(l2, res.layer)

    async def expanded(self) -> EvidencePack:
        return await ensure_expanded(self.ctx, self.tracker)

    def final(self, label: LayerResult | None, verdict: str, decided_by: DecidedBy,
              consensus: str, tier: int, **extra: object) -> CascadeOutcome:
        return self.out.model_copy(update={
            "verdict": verdict, "label_layer": label, "decided_by": decided_by,
            "consensus_type": consensus, "tier": tier, **extra})

    def failed(self, layer: LayerResult) -> CascadeOutcome:
        tier = 2 if layer.role == "verifier" else 3
        return self.final(None, "cannot_verify", "none", "llm_error", tier,
                          cv_reason="llm_error", error=f"{layer.layer}: {layer.error}")


async def run_cascade(ctx: PairContext, screen: ScreenResult | None,
                      thresholds: ScreenThresholds, *, deadline: float,
                      cost_tracker: CostTracker | None = None) -> CascadeOutcome:
    """Route one sourced pair (V5.1, see module docstring), then adjudicate a partial."""
    run = _Run(ctx, screen, thresholds, cost_tracker, deadline)
    await asyncio.to_thread(colour_finding, ctx)  # G2: PDF / OCR reads cached off the loop
    out = close_recheck(await _route(run, ctx, screen, thresholds, cost_tracker),
                        run.first, run.rechecked)
    out = hold_fragment(ctx, out, await adjudicate_outcome(ctx, out, cost_tracker, deadline))
    return await check_first_outcome(ctx, screen, out, cost_tracker, deadline)


async def _route(run: _Run, ctx: PairContext, screen: ScreenResult | None,
                 thresholds: ScreenThresholds, cost_tracker: CostTracker | None,
                 ) -> CascadeOutcome:
    l2 = await run.layer("verifier", "verifier", ctx.pack, expanded=False)
    if l2.output is None:
        return run.failed(l2)
    first, l2 = l2, await run.recheck(l2)  # partial / negative + unsupported elements
    if overturned(first, l2):
        return await cross_check_overturn(run, first, l2)
    if (done := verifier_final(l2, run.out.clear_eligible, screen, thresholds)) is not None:
        return run.final(l2, l2.verdict or "", *done)
    if l2.verdict == "insufficient_evidence" and ctx.coverage == "full_text":
        pack = await ensure_expanded(ctx, cost_tracker)
        l2 = await run.layer("verifier", "verifier_expanded", pack, expanded=True)
        if l2.output is None:
            return run.failed(l2)
        if (done := verifier_final(l2, run.out.clear_eligible, screen, thresholds)) is not None:
            return run.final(l2, l2.verdict or "", *done)
    if l2.axis is None:  # still insufficient: the source does not let us decide
        reason = ("insufficient_in_source" if ctx.coverage == "full_text"
                  else "abstract_insufficient")
        return run.final(l2, "cannot_verify", "verifier", "verifier", 2, cv_reason=reason)
    if l2.axis == "negative":
        return await cross_check_negative(run, l2)
    if os.getenv("REFCHECK_JUDGE_UNUSUAL_POSITIVES", "") == "1":
        return await judge_positive(run, l2)
    return await cross_check_positive(run, l2)
