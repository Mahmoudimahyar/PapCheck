"""Convert cascade layers into the result trace (ModelReasoning, votes, evidence)."""

import logging
from collections import Counter

from refcheck.models.evidence import EvidenceSection
from refcheck.models.verification import (
    ModelReasoning,
    VerificationResult,
    VoteRecord,
    reached_llm,
)
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.evidence_builder import build_evidence_sections
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.retriever import EvidencePack, passage_label
from refcheck.stages.verify_claims.screen import SCREEN_PREDICATES, ScreenResult

logger = logging.getLogger(__name__)

LAYER_DISPLAY = {
    "verifier": "Verifier", "verifier_expanded": "Verifier (expanded)",
    "verifier_recheck": "Verifier (evidence re-check)", "judge": "Judge", "confirm": "Confirm",
    "adjudicate": "Element check", "adjudicate_cocited": "Element check (co-cited)",
    "post_rules": "Rule check",  # V5.6 deterministic outcome rules (outcome_rules.py)
    "adjudicate_slots": "Element check (claim slots)",  # V5.7 #2 slot audit (slot_apply.py)
    "slot_probe": "Slot probe",  # V5.7 #15, experimental (slot_probe.py)
}
# The element adjudicator and its co-cited union check are a cheap verifier-tier model (tier 2).
LAYER_TIER = {"screen": 1, "verifier": 2, "verifier_expanded": 2, "verifier_recheck": 2,
              "judge": 3, "confirm": 4, "adjudicate": 2, "adjudicate_cocited": 2,
              "adjudicate_slots": 2, "slot_probe": 2}
_ABBREV = {"verifier": "V", "verifier_expanded": "V+", "verifier_recheck": "VR", "judge": "J",
           "confirm": "C", "adjudicate": "A", "adjudicate_cocited": "AC", "post_rules": "R",
           "adjudicate_slots": "AS", "slot_probe": "SP"}
_MAX_SECTIONS = 4
_TRACE_CHARS = 160
LLM_ERROR_THRESHOLD = 0.05  # circuit breaker (stage event handled by services.verify_outcome)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TRACE_CHARS else text[:_TRACE_CHARS].rsplit(" ", 1)[0] + " …"


def audit_trace(layer: LayerResult) -> str:
    """V5.6: context-only quotes and rejected clearances, kept in the layer trace."""
    parts = [f' Context only, not evidence ({q.context}): "{_short(q.text)}"'
             for q in layer.context_quotes]
    parts += [f" Clearance not accepted: {line}." for line in layer.rejected_dismissals]
    return "".join(parts)


def layer_reasoning(layer: LayerResult) -> ModelReasoning:
    """One trace entry, e.g. model_display "Judge · claude-sonnet-5-5"."""
    prefix = LAYER_DISPLAY.get(layer.layer, layer.layer.title())
    display = f"{prefix} · {layer.model_display or layer.model_id or 'unavailable'}"
    if layer.output is None:
        return ModelReasoning(model_name=layer.model_id, model_display=display, verdict="error",
                              reasoning=f"Layer failed: {layer.error}",
                              source_section_preview=layer.pack_summary,
                              response_time_ms=layer.latency_ms)
    out = layer.output
    text = out.explanation
    if out.missing:
        text += f" Missing: {out.missing}"
    if out.severity != "none" or out.problem_type != "none":
        text += f" [severity {out.severity}, problem {out.problem_type}]"
    if layer.invalid_quotes:
        text += f" ({len(layer.invalid_quotes)} quote(s) not found in the source)"
    text += audit_trace(layer)
    return ModelReasoning(
        model_name=layer.model_id, model_display=display, verdict=out.verdict,
        confidence=out.confidence, reasoning=text.strip(),
        evidence_quotes=[q.text for q in layer.validated_quotes],
        source_section_preview=layer.pack_summary, response_time_ms=layer.latency_ms,
        input_tokens=layer.input_tokens, output_tokens=layer.output_tokens,
    )


def screen_reasoning(screen: ScreenResult, eligible: bool, failed_gates: list[str],
                     thresholds: ScreenThresholds) -> ModelReasoning:
    """Trace entry for the Decisions-API screen."""
    probs = ", ".join(f"{n} {screen.probs[n]:.2f}" for n in SCREEN_PREDICATES
                      if n in screen.probs)
    s_text = "n/a" if screen.s is None else f"{screen.s:.3f}"
    gates = "all gates passed" if eligible else "not auto-clearable: " + ", ".join(failed_gates)
    text = f"P(support)={s_text} (threshold {thresholds.t_accept:.3f}); {probs}; {gates}."
    if screen.refused:
        text += f" Refused: {', '.join(screen.refused)}."
    verdict = "likely_supported" if eligible else (
        "possible_problem" if screen.p_problem is not None and screen.p_problem >= 0.5
        else "screen_inconclusive")
    return ModelReasoning(
        model_name=screen.model, model_display=screen.model_display or screen.model,
        verdict=verdict, confidence=screen.s or 0.0, reasoning=text,
        response_time_ms=screen.latency_ms, input_tokens=screen.input_tokens,
    )


def layer_vote(layer: LayerResult) -> VoteRecord:
    return VoteRecord(
        model_name=layer.model_display or layer.model_id,
        abbreviation=_ABBREV.get(layer.layer, "?"),
        tier=LAYER_TIER.get(layer.layer, 0), verdict=layer.verdict or "error",
        confidence=layer.output.confidence if layer.output else 0.0,
    )


def screen_vote(screen: ScreenResult, eligible: bool) -> VoteRecord:
    return VoteRecord(model_name=screen.model_display or screen.model, abbreviation="S", tier=1,
                      verdict="likely_supported" if eligible else "escalate",
                      confidence=screen.s or 0.0)


def evidence_sections_for(
    pack: EvidencePack, quotes: list[str], cited_ids: list[str], claim_text: str,
) -> list[EvidenceSection]:
    """Sections for the UI: passages cited by validated quotes, else the top passages."""
    wanted = [p for p in pack.passages if p.id.upper() in {c.upper() for c in cited_ids}]
    passages = (wanted or pack.passages)[:_MAX_SECTIONS]
    if not passages:
        return []
    sections = build_evidence_sections(
        source_sections=[p.text for p in passages],
        source_headings=[f"[{p.id}] {passage_label(p)}" for p in passages],
        evidence_quotes=quotes, source_text=pack.joined_text, claim_text=claim_text,
    )
    return [s.model_copy(update={"page_number": p.page}) for s, p in zip(sections, passages,
                                                                          strict=True)]


def log_tier_stats(results: list[VerificationResult]) -> None:
    """Log how pairs were decided, review count, LLM errors and cost (+ circuit breaker)."""
    decided = Counter(r.decided_by for r in results)
    verdicts = Counter(r.verdict for r in results)
    errors = sum(1 for r in results if r.cannot_verify_reason == "llm_error")
    review = sum(1 for r in results if r.needs_user_review)
    cost = sum(r.cost_usd for r in results)
    logger.info("Verified %d pairs: decided_by=%s verdicts=%s review=%d llm_errors=%d cost=$%.4f",
                len(results), dict(decided), dict(verdicts), review, errors, cost)
    attempted = sum(1 for r in results if reached_llm(r))
    if attempted and errors / attempted > LLM_ERROR_THRESHOLD:
        logger.error("Circuit breaker: %d of %d sourced pairs failed with LLM/API errors",
                     errors, attempted)
