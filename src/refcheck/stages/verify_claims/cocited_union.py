"""Co-cited full-text union check: one call after the element adjudicator (V5.5b).

On the V4.9 manuscript gold dev split, half of the gold-supported pairs still
partial after the adjudicator were "cocited_share": the surviving elements were
absent from THIS reference, but reviewers found them in the FULL TEXT of another
reference cited in the same sentence. The adjudicator only sees co-cited
abstracts (<= 250 tokens), which rarely carry such details.

Runs once per pair (cocited_union_apply.py decides what changes) when ALL hold:

* the adjudicator ran without error and the pair is still partially_supported;
* some surviving elements were categorised "absent" (or "cocited" with a quote
  the abstract check could not validate: the full text may state it); V5.8 #29 (F7):
  also "overstated" / "broadened" (this source states a weaker or narrower form; a
  co-cited reference may state the point fully - its exact quote must keep every
  number and quantifier, cocited_union_rules);
* at least one co-cited reference has a loaded source (cocited_union_pack);
* this reference supports its own share (taxonomy cocited_share (a)): the shown
  layer has a validated "supports" quote, or the adjudicator cleared an element
  with a validated quote from this source; otherwise the citation is tangential,
  not shared, and the check is "skipped" (no call).

The call sees the targeted co-cited passages (<= 3,000 tokens) and answers
cocited (passage id + verbatim quote) or absent per element; the clearing rule is
in cocited_union_rules.py. Never on negative verdicts (they are never partial).

Env: REFCHECK_COCITED_UNION=on|off (default on; it also needs REFCHECK_ADJUDICATE).
"""

import logging
import os
import time

from pydantic import BaseModel, Field

from refcheck.llm import CostLimitExceededError, CostTracker, LLMError, call_llm_raw
from refcheck.models.adjudication import CocitedOutput
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.adjudicate import MIN_SECONDS, Adjudication
from refcheck.stages.verify_claims.adjudicate_prompt import QUANTIFIERS
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision, match_checks
from refcheck.stages.verify_claims.cocited_union_pack import (
    UnionSource,
    render_sources,
    union_tokens,
)
from refcheck.stages.verify_claims.cocited_union_rules import UnionDecision, decide_union
from refcheck.stages.verify_claims.layers import LayerResult, PackKind, cited_for
from refcheck.stages.verify_claims.taxonomy_prompt import taxonomy_prompt
from refcheck.stages.verify_claims.verifier_helpers import PairContext

logger = logging.getLogger(__name__)

UNION_LAYER = "adjudicate_cocited"
TEMPLATE = "adjudicate_cocited"
UNION_CATEGORIES = frozenset({"absent", "cocited"})
DEGREE_CATEGORIES = frozenset({"overstated", "broadened"})  # V5.8 #29
MIN_RETRIEVAL_SECONDS = 20.0  # before retrieval: leave time for it and the call
_OFF = {"0", "false", "no", "off"}


def cocited_union_enabled() -> bool:
    """REFCHECK_COCITED_UNION (default on)."""
    value = os.getenv("REFCHECK_COCITED_UNION", "on").strip().lower()
    if value not in _OFF and value not in ("1", "true", "yes", "on", ""):
        logger.warning("Unknown REFCHECK_COCITED_UNION=%r; using 'on'", value)
    return value not in _OFF


class UnionRun(BaseModel):
    """Call metadata (``meta``) + per-element decisions."""

    meta: LayerResult
    decisions: list[UnionDecision] = Field(default_factory=list)
    explanation: str = ""

    @property
    def ok(self) -> bool:
        return self.meta.error is None

    @property
    def cleared(self) -> list[UnionDecision]:
        return [d for d in self.decisions if d.cleared]


def union_targets(adj: Adjudication) -> list[ElementDecision]:
    """Surviving elements the adjudicator found in nothing it was shown (module doc)."""
    wanted = UNION_CATEGORIES | (DEGREE_CATEGORIES if v57.enabled(29) else frozenset())
    return [d for d in adj.surviving if d.category in wanted]


def own_share_supported(label: LayerResult | None, adj: Adjudication) -> bool:
    """This reference backs its own share with a validated quote (module doc)."""
    return (label is not None and bool(label.quotes("supports"))) or any(
        d.validated is not None for d in adj.cleared)


def union_system_variables() -> dict[str, object]:
    guard = next(g for g in taxonomy_prompt().guards if g.id == "cocited_share")
    return {"section": "system", "guard": {"id": guard.id, "definition": guard.definition},
            "quantifiers": ", ".join(f"'{q}'" for q in QUANTIFIERS)}


def union_user_variables(ctx: PairContext, sources: list[UnionSource],
                         elements: list[str]) -> dict[str, object]:
    claim = ctx.claim
    return {"section": "user", "sources": render_sources(sources),
            "source_title": ctx.ref.title, "claim": ctx.claim_text or claim.extracted_claim,
            "sentence": claim.manuscript_text, "cited_for": cited_for(claim, ctx.claim_text),
            "elements": list(elements)}


def _skip(meta: LayerResult, tracker: CostTracker | None, deadline: float,
          min_seconds: float = MIN_SECONDS) -> LayerResult | None:
    if tracker is not None and tracker.total_cost >= tracker.max_cost:
        return meta.model_copy(update={"error": "cost limit reached", "error_kind": "budget"})
    if deadline - time.monotonic() < min_seconds:
        return meta.model_copy(update={"error": "per-pair time budget exhausted",
                                       "error_kind": "timeout"})
    return None


def budget_skip(pack_kind: PackKind, tracker: CostTracker | None,
                deadline: float) -> UnionRun | None:
    """A failed run, checked BEFORE any retrieval, when the cost cap is reached or less
    than MIN_RETRIEVAL_SECONDS are left (per-element retrieval may embed whole
    co-cited documents, then the call needs time)."""
    meta = LayerResult(layer=UNION_LAYER, role="adjudicator", pack_kind=pack_kind,
                       pack_summary="co-cited passages not retrieved")
    skipped = _skip(meta, tracker, deadline, MIN_RETRIEVAL_SECONDS)
    return None if skipped is None else UnionRun(meta=skipped)


async def run_union(ctx: PairContext, sources: list[UnionSource], elements: list[str],
                    pack_kind: PackKind, tracker: CostTracker | None,
                    deadline: float) -> UnionRun:
    """Ask about ``elements`` over the co-cited passages; never raises for LLM/budget/time."""
    ids = [p.id for s in sources for p in s.pack.passages]
    meta = LayerResult(layer=UNION_LAYER, role="adjudicator", pack_kind=pack_kind,
                       pack_summary=f"co-cited passages ({', '.join(ids[:3])}"
                       f"{' …' if len(ids) > 3 else ''}); {union_tokens(sources)} tokens")
    if (skipped := _skip(meta, tracker, deadline)) is not None:
        return UnionRun(meta=skipped)
    try:
        result = await call_llm_raw(
            TEMPLATE, union_user_variables(ctx, sources, elements), CocitedOutput,
            role="adjudicator", cost_tracker=tracker, task=f"verify_{UNION_LAYER}",
            timeout=deadline - time.monotonic(), system_template=TEMPLATE,
            system_variables=union_system_variables())
    except CostLimitExceededError as exc:
        return UnionRun(meta=meta.model_copy(update={
            "error": f"cost limit reached: {exc}", "error_kind": "budget"}))
    except (LLMError, TimeoutError) as exc:
        kind = exc.kind if isinstance(exc, LLMError) else "timeout"
        logger.warning("co-cited union check failed for claim %d / ref %d (%s): %s",
                       ctx.claim.id, ctx.ref.id, kind, str(exc)[:200])
        return UnionRun(meta=meta.model_copy(update={
            "error": f"{kind}: {str(exc)[:300]}", "error_kind": kind,
            "model_id": getattr(exc, "model_id", None) or ""}))
    checks = match_checks(elements, result.parsed.elements)
    meta = meta.model_copy(update={
        "model_id": result.model_id, "model_display": result.display_name or result.model_id,
        "provider": result.provider, "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd, "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens})
    return UnionRun(meta=meta, explanation=" ".join(result.parsed.explanation.split()),
                    decisions=[decide_union(e, c, sources)
                               for e, c in zip(elements, checks, strict=True)])
