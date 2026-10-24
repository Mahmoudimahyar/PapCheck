"""Element adjudicator: one narrow question per element of a partial verdict (V5.5).

On the V4.9 manuscript gold dev split the cascade still showed half of the
gold-supported citations as partially_supported; in most of them the small
verifier, answering verdict + taxonomy + guards in one pass, listed elements
reviewers judged benign (an author's framing, a quantifier-free paraphrase, a
point stated in a shown passage or by a co-cited reference). A narrow
per-element question is easier for the same cheap model.

The model's category is NOT trusted on its own: the clearing rule (an exact
verbatim quote for stated / wording / framing / cocited, no disqualifier such as a
time frame, mechanism, population or number for framing / wording) and the
answer-to-element matching are in adjudicate_rules.py. Elements a deterministic
rule added ("lineage: ...", "number: ...") are never asked about and never cleared.
How a cleared element changes the result is in adjudicate_apply.py.

Env: REFCHECK_ADJUDICATE=on|off (default on); the model is role "adjudicator".
"""

import logging
import os
import time

from pydantic import BaseModel, Field

from refcheck.llm import CostLimitExceededError, CostTracker, LLMError, call_llm_raw
from refcheck.models.adjudication import AdjudicateOutput
from refcheck.stages.verify_claims.adjudicate_prompt import (
    TEMPLATE,
    adjudicate_system_variables,
    adjudicate_user_variables,
)
from refcheck.stages.verify_claims.adjudicate_rules import (
    ElementDecision,
    decide,
    is_locked,
    match_checks,
)
from refcheck.stages.verify_claims.layers import LayerResult, PackKind, pack_summary
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.verifier_helpers import PairContext

logger = logging.getLogger(__name__)

LAYER = "adjudicate"
MIN_SECONDS = 5.0
_OFF = {"0", "false", "no", "off"}


def adjudicate_enabled() -> bool:
    """REFCHECK_ADJUDICATE (default on)."""
    value = os.getenv("REFCHECK_ADJUDICATE", "on").strip().lower()
    if value not in _OFF and value not in ("1", "true", "yes", "on", ""):
        logger.warning("Unknown REFCHECK_ADJUDICATE=%r; using 'on'", value)
    return value not in _OFF


class Adjudication(BaseModel):
    """Call metadata (``meta``: a LayerResult without output) + per-element decisions."""

    meta: LayerResult
    decisions: list[ElementDecision] = Field(default_factory=list)
    explanation: str = ""

    @property
    def ok(self) -> bool:
        return self.meta.error is None

    @property
    def cleared(self) -> list[ElementDecision]:
        return [d for d in self.decisions if d.cleared]

    @property
    def surviving(self) -> list[ElementDecision]:
        return [d for d in self.decisions if not d.cleared]


def _skip(meta: LayerResult, tracker: CostTracker | None, deadline: float) -> LayerResult | None:
    """A failed meta layer when the budget or the per-pair time is exhausted."""
    if tracker is not None and tracker.total_cost >= tracker.max_cost:
        return meta.model_copy(update={"error": "cost limit reached", "error_kind": "budget"})
    if deadline - time.monotonic() < MIN_SECONDS:
        return meta.model_copy(update={"error": "per-pair time budget exhausted",
                                       "error_kind": "timeout"})
    return None


async def run_adjudication(ctx: PairContext, pack: EvidencePack, pack_kind: PackKind,
                           elements: list[str], tracker: CostTracker | None,
                           deadline: float) -> Adjudication:
    """Ask the adjudicator about ``elements`` (not the locked ones: they get a "rule"
    decision); never raises for LLM/budget/time failures."""
    asked = [e for e in elements if not is_locked(e)]
    meta = LayerResult(layer=LAYER, role="adjudicator", pack_kind=pack_kind,
                       pack_summary=pack_summary(pack, pack_kind))
    if (skipped := _skip(meta, tracker, deadline)) is not None:
        return Adjudication(meta=skipped)
    try:
        result = await call_llm_raw(
            TEMPLATE, adjudicate_user_variables(ctx.claim, ctx, pack, pack_kind, asked),
            AdjudicateOutput, role="adjudicator", cost_tracker=tracker, task=f"verify_{LAYER}",
            timeout=deadline - time.monotonic(), system_template=TEMPLATE,
            system_variables=adjudicate_system_variables())
    except CostLimitExceededError as exc:
        return Adjudication(meta=meta.model_copy(update={
            "error": f"cost limit reached: {exc}", "error_kind": "budget"}))
    except (LLMError, TimeoutError) as exc:
        kind = exc.kind if isinstance(exc, LLMError) else "timeout"
        logger.warning("adjudicate failed for claim %d / ref %d (%s): %s", ctx.claim.id,
                       ctx.ref.id, kind, str(exc)[:200])
        return Adjudication(meta=meta.model_copy(update={
            "error": f"{kind}: {str(exc)[:300]}", "error_kind": kind,
            "model_id": getattr(exc, "model_id", None) or ""}))
    answers = dict(zip(asked, match_checks(asked, result.parsed.elements), strict=True))
    meta = meta.model_copy(update={
        "model_id": result.model_id, "model_display": result.display_name or result.model_id,
        "provider": result.provider, "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd, "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens})
    return Adjudication(meta=meta, explanation=" ".join(result.parsed.explanation.split()),
                        decisions=[decide(e, answers.get(e), ctx, pack) for e in elements])
