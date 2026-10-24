"""Evaluate one eval item in one mode, using the production cascade code.

Modes: screen (Decisions API only), verifier (L2 on the standard pack, re-run
once on the expanded pack when insufficient on full text, or on the evidence
re-check pack when partial/negative with unsupported elements, like production),
judge (L3 alone on the expanded pack, judge_claim), confirm (the V5.1 blind
cross-check alone: verify_claim on the standard pack the verifier sees),
cascade (screen + run_cascade + build_result + annotate_source_fallback,
exactly the per-pair path of verifier.py). Every record carries the product's
partial fields (partial_type, partial_severity, guards_applied, unsupported_elements).
"""

import asyncio
import logging
import time
from collections.abc import Mapping

from eval_data import build_context
from eval_models import EvalConfig, EvalItem, ItemRecord, ScreenRecord
from eval_recorded import recorded_screen
from eval_records import (
    adjudication_update,
    classification,
    item_record,
    layer_record,
    partial_update,
    screen_update,
)
from pydantic import BaseModel, Field

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.types import Role
from refcheck.stages.generate_report.result_signals import check_first
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import ensure_expanded, run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.cocited import co_cited_documents
from refcheck.stages.verify_claims.concurrent import get_claim_budget
from refcheck.stages.verify_claims.layers import LayerResult, PackKind, cited_for, run_layer
from refcheck.stages.verify_claims.partial_fields import partial_fields
from refcheck.stages.verify_claims.post_checks import searchable_text
from refcheck.stages.verify_claims.recheck import evidence_recheck
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.screen import ScreenResult, clear_gates, run_screen
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import PairContext, annotate_source_fallback

logger = logging.getLogger(__name__)

TIMEOUT_GRACE_S = 30.0  # same hard-timeout grace as concurrent.py


class SingleRun(BaseModel):
    """Layer calls of a single-role mode, the deciding layer, pipeline guards and the
    elements the evidence re-check no longer reports (as the cascade records them)."""

    layers: list[LayerResult]
    last: LayerResult
    guards: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)


def wants_screen(cfg: EvalConfig) -> bool:
    return cfg.mode in ("screen", "cascade") or (cfg.mode == "verifier" and cfg.with_screen)


async def _layer(role: Role, name: str, ctx: PairContext, pack: EvidencePack, kind: PackKind,
                 tracker: CostTracker, deadline: float) -> LayerResult:
    template = "judge_claim" if role == "judge" else "verify_claim"  # same as the cascade
    return await run_layer(role, pack, ctx.claim, ctx, template, layer=name, pack_kind=kind,
                           cost_tracker=tracker, timeout=deadline - time.monotonic())


async def _verifier_layers(ctx: PairContext, tracker: CostTracker,
                           deadline: float) -> SingleRun:
    first = await _layer("verifier", "verifier", ctx, ctx.pack, "standard", tracker, deadline)
    if first.verdict == "insufficient_evidence" and ctx.coverage == "full_text":
        pack = await ensure_expanded(ctx, tracker)
        second = await _layer("verifier", "verifier_expanded", ctx, pack, "expanded", tracker,
                              deadline)
        return SingleRun(layers=[first, second], last=second)

    reruns: list[LayerResult] = []

    async def rerun(pack: EvidencePack) -> LayerResult:
        reruns.append(await _layer("verifier", "verifier_recheck", ctx, pack, "recheck",
                                   tracker, deadline))
        return reruns[-1]

    res = await evidence_recheck(ctx, first, rerun, tracker, deadline)
    if not res.guard:
        return SingleRun(layers=[first, *reruns], last=res.layer)
    return SingleRun(layers=[first, *reruns], last=res.layer, guards=["evidence_recheck"],
                     cleared=res.cleared)


async def single_layers(mode: str, ctx: PairContext, tracker: CostTracker,
                        deadline: float) -> SingleRun:
    """Layer calls, deciding layer and pipeline guards of a single-role mode."""
    if mode == "confirm":  # V5.1 cross-check: same prompt and pack as the verifier
        done = await _layer("confirm", "confirm", ctx, ctx.pack, "standard", tracker, deadline)
        return SingleRun(layers=[done], last=done)
    if mode == "verifier":
        return await _verifier_layers(ctx, tracker, deadline)
    pack = await ensure_expanded(ctx, tracker)
    done = await _layer("judge", "judge", ctx, pack, "expanded", tracker, deadline)
    return SingleRun(layers=[done], last=done)


async def _cascade(rec: ItemRecord, ctx: PairContext, screen: ScreenResult | None,
                   thresholds: ScreenThresholds, tracker: CostTracker,
                   budget: float) -> ItemRecord:
    start = time.monotonic()
    outcome = await run_cascade(ctx, screen, thresholds, deadline=start + budget,
                                cost_tracker=tracker)
    latency = int((time.monotonic() - start) * 1000) + (screen.latency_ms if screen else 0)
    result = annotate_source_fallback(
        build_result(ctx, screen, outcome, thresholds, latency), ctx.doc)
    return rec.model_copy(update={
        **classification(outcome.label_layer),
        **partial_update(result.partial_type, result.partial_severity, result.guards_applied,
                         result.unsupported_elements),
        "layers": [layer_record(lay) for lay in outcome.layers], "verdict": result.verdict,
        "cannot_verify_reason": result.cannot_verify_reason, "decided_by": result.decided_by,
        "consensus_type": result.consensus_type, "layer_path": result.layer_path,
        "needs_review": result.needs_user_review, "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
        "error": outcome.error if result.cannot_verify_reason == "llm_error" else None,
        **adjudication_update(outcome.adjudication), "check_first": check_first(result),
    })


async def _screen(item_id: str, ctx: PairContext, tracker: CostTracker,
                  screens: Mapping[str, ScreenRecord]) -> ScreenResult:
    """The recorded screen answer (--screen-from), else a live screen call."""
    recorded = screens.get(item_id)
    return recorded_screen(recorded) if recorded is not None else await run_screen(ctx, tracker)


async def _evaluate(rec: ItemRecord, item: EvalItem, ids: tuple[int, int],
                    doc: SourceDocument, cfg: EvalConfig, thresholds: ScreenThresholds,
                    tracker: CostTracker, budget: float, cocited: Mapping[int, SourceDocument],
                    screens: Mapping[str, ScreenRecord]) -> ItemRecord:
    ctx = await build_context(item, ids[0], ids[1], doc, cfg.use_embeddings, tracker)
    ctx.co_cited_docs = co_cited_documents(ctx.co_cited, cocited)  # as verifier.py does
    rec = rec.model_copy(update={"retrieval_version": ctx.pack.retrieval_version,
                                 "pack_tokens": ctx.pack.total_tokens})
    screen: ScreenResult | None = None
    if wants_screen(cfg) and thresholds.enabled:
        screen = await _screen(item.id, ctx, tracker, screens)
        rec = rec.model_copy(update=screen_update(
            screen, *clear_gates(ctx.claim, ctx, screen, thresholds)))
    if cfg.mode == "screen":
        return rec.model_copy(update={"verdict": "n/a", "error": screen.error if screen
                                      else "screen disabled"})
    if cfg.mode == "cascade":
        return await _cascade(rec, ctx, screen, thresholds, tracker, budget)
    start = time.monotonic()
    run = await single_layers(cfg.mode, ctx, tracker, start + budget)
    layers, last = run.layers, run.last
    wall = int((time.monotonic() - start) * 1000)
    # Same inputs as cascade_helpers._post_rules (cited part, source text, re-check finds).
    fields = partial_fields(last.verdict or "", last, layers, ctx.coverage, run.guards,
                            claim_part=cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text,
                            source_text=searchable_text(ctx.doc), recheck_cleared=run.cleared)
    return rec.model_copy(update={
        **classification(last),
        **partial_update(fields.partial_type, fields.partial_severity, fields.guards_applied,
                         fields.unsupported_elements),
        "layers": [layer_record(lay) for lay in layers],
        "verdict": last.verdict if last.output is not None else "error",
        "layer_path": [*rec.layer_path, *(lay.layer for lay in layers)],
        "cost_usd": rec.cost_usd + sum(lay.cost_usd for lay in layers),
        "latency_ms": rec.latency_ms + wall, "error": last.error,
    })


async def evaluate_item(item: EvalItem, claim_id: int, ref_id: int, doc: SourceDocument,
                        cfg: EvalConfig, thresholds: ScreenThresholds, tracker: CostTracker,
                        cocited: Mapping[int, SourceDocument] | None = None,
                        screens: Mapping[str, ScreenRecord] | None = None) -> ItemRecord:
    """One item -> ItemRecord; never raises (failures become error records). ``cocited``:
    loaded sources of co-cited references by number (eval_cocited); ``screens``: recorded
    screen answers by item id (--screen-from; items without one call the screen)."""
    rec = item_record(item, cfg.mode, coverage=doc.coverage,
                      quality_reason=doc.quality_reason)
    budget = float(get_claim_budget())
    try:
        return await asyncio.wait_for(
            _evaluate(rec, item, (claim_id, ref_id), doc, cfg, thresholds, tracker, budget,
                      cocited or {}, screens or {}),
            timeout=budget + TIMEOUT_GRACE_S)
    except TimeoutError:
        return rec.model_copy(update={"error": "timeout: per-pair budget exceeded"})
    except Exception as exc:  # one broken item must not stop the run
        logger.exception("Item %s failed", item.id)
        return rec.model_copy(update={"error": f"{type(exc).__name__}: {str(exc)[:300]}"})
