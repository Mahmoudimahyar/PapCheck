"""L1 screen: six Decisions-API predicates per pair + the auto-clear gates.

s = min(topic_match, finding_stated, evidence_sufficient, 1 - finding_conflicts,
1 - claim_overreaches); P(problem) = 1 - s is kept for every pair (risk
ranking). A pair is clear-eligible only when every code gate holds and
s >= t_accept. Decisions API errors skip the screen for that pair.
"""

import logging
from functools import lru_cache

from pydantic import BaseModel, Field

from refcheck.llm import CostLimitExceededError, CostTracker, DecisionQuestion, LLMError, decide
from refcheck.llm.model_lookup import spec_for
from refcheck.llm.templates import render_template
from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.gates import (
    MAX_CLEAR_WORDS,
    has_negation_cue,
    has_non_year_digits,
    is_abstract_only,
    is_contrast,
    quality_ok,
    word_count,
)
from refcheck.stages.verify_claims.layers import cited_for
from refcheck.stages.verify_claims.retriever import render_pack
from refcheck.stages.verify_claims.verifier_helpers import PairContext

logger = logging.getLogger(__name__)

SUPPORT_PREDICATES = ("topic_match", "finding_stated", "evidence_sufficient")
PROBLEM_PREDICATES = ("finding_conflicts", "claim_overreaches")
SCREEN_PREDICATES = (*SUPPORT_PREDICATES, *PROBLEM_PREDICATES, "contains_instructions")
SCREEN_TIMEOUT_S = 20.0
# Gate name when calibration switched auto-clear off (eval re-scores ignore it).
AUTO_CLEAR_OFF_GATE = "auto_clear_off"


class ScreenResult(BaseModel):
    """Screen answers for one pair (probabilities by predicate name)."""

    probs: dict[str, float] = Field(default_factory=dict)
    refused: list[str] = Field(default_factory=list)
    s: float | None = None
    p_problem: float | None = None
    model: str = ""
    model_display: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.model)


@lru_cache(maxsize=1)
def screen_questions() -> tuple[DecisionQuestion, ...]:
    """The six predicate questions (instructions live in prompts/screen_claim.md)."""
    return tuple(
        DecisionQuestion(name=name, instructions=render_template(
            "screen_claim", {"section": "question", "name": name}).strip())
        for name in SCREEN_PREDICATES
    )


def build_screen_input(ctx: PairContext) -> str:
    """Decisions input (spec §4): claim, context, co-citations, source, passages.

    When the sentence attaches this reference to one clause (``cited_for``), that
    clause is the claim and the whole sentence is shown as context only.
    """
    ref = ctx.ref
    first_author = ref.authors[0].split(",")[0].strip() if ref.authors else ""
    part = cited_for(ctx.claim, ctx.claim_text)
    return render_template("screen_claim", {
        "section": "input", "claim": part or ctx.claim_text,
        "sentence": ctx.claim_text if part else "", "prev_sentence": ctx.prev_sentence,
        "co_cited_others": max(0, ctx.claim.co_cited_count - 1),
        "source_title": ref.title, "first_author": first_author, "year": ref.year,
        "passages": render_pack(ctx.pack),
    })


def combine(probs: dict[str, float]) -> float | None:
    """s over the available support/problem predicates (None when none answered)."""
    parts = [probs[n] for n in SUPPORT_PREDICATES if n in probs]
    parts += [1.0 - probs[n] for n in PROBLEM_PREDICATES if n in probs]
    return min(parts) if parts else None


async def run_screen(
    ctx: PairContext, cost_tracker: CostTracker | None = None,
    timeout: float = SCREEN_TIMEOUT_S,
) -> ScreenResult:
    """Ask the six predicates; never raises (errors are recorded on the result)."""
    try:
        decision = await decide(build_screen_input(ctx), list(screen_questions()),
                                role="screen", cost_tracker=cost_tracker, task="screen",
                                timeout=timeout)
    except CostLimitExceededError as exc:
        return ScreenResult(error=f"cost limit: {exc}")
    except LLMError as exc:
        logger.warning("Screen skipped for claim %d / ref %d: %s", ctx.claim.id, ctx.ref.id,
                       str(exc)[:200])
        return ScreenResult(error=f"{exc.kind}: {str(exc)[:200]}", model=exc.model_id or "")
    probs = {n: p for n in SCREEN_PREDICATES if (p := decision.probability(n)) is not None}
    s = combine(probs)
    return ScreenResult(
        probs=probs, refused=[n for n in SCREEN_PREDICATES if n not in probs], s=s,
        p_problem=None if s is None else round(1.0 - s, 6), model=decision.model,
        model_display=spec_for(decision.model, "decision").label,
        latency_ms=decision.latency_ms, cost_usd=decision.cost_usd,
        input_tokens=decision.input_tokens,
    )


def clear_gates(
    claim: Claim, ctx: PairContext, screen: ScreenResult | None,
    thresholds: ScreenThresholds,
) -> tuple[bool, list[str]]:
    """(clear-eligible, failed gate names). All gates must hold to auto-clear."""
    failed: list[str] = []
    text = ctx.claim_text or claim.extracted_claim
    if not thresholds.enabled:
        failed.append("screen_disabled")
    elif not thresholds.auto_clear:
        failed.append(AUTO_CLEAR_OFF_GATE)
    if is_abstract_only(ctx.coverage):
        failed.append("abstract_only")
    if not quality_ok(ctx.doc.quality_reason, ctx.doc.quality_score):
        failed.append("text_quality")
    if has_non_year_digits(text):
        failed.append("numeric_claim")
    if has_negation_cue(text):
        failed.append("negation")
    if word_count(text) > MAX_CLEAR_WORDS:
        failed.append("too_long")
    if is_contrast(claim.claim_type):
        failed.append("contrast")
    if screen is None or not screen.ok:
        failed.append("screen_unavailable")
    else:
        if screen.refused:
            failed.append("refusal")
        if screen.probs.get("contains_instructions", 1.0) >= thresholds.injection_max:
            failed.append("injection")
        if screen.s is None or screen.s < thresholds.t_accept:
            failed.append("below_threshold")
    return not failed, failed


def screen_conflicts(screen: ScreenResult | None, thresholds: ScreenThresholds) -> bool:
    """Screen sees a conflict or topic mismatch (blocks verifier-only finals)."""
    if screen is None or not screen.ok:
        return False  # no screen signal: cannot conflict
    conflict = screen.probs.get("finding_conflicts", 0.0) >= thresholds.t_contra
    off_topic = screen.probs.get("topic_match", 1.0) < thresholds.t_topic
    return conflict or off_topic
