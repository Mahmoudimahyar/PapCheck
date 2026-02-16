"""Helper functions for converting model responses to votes."""

from refcheck.llm.multi_model import ModelResponse
from refcheck.llm.voting_models import ConsensusResult, ModelVote


def responses_to_votes(
    responses: list[ModelResponse], tier: int,
) -> list[ModelVote]:
    """Convert model responses to votes."""
    votes: list[ModelVote] = []
    for resp in responses:
        vote = response_to_vote(resp, tier)
        if vote:
            votes.append(vote)
    return votes


def response_to_vote(
    resp: ModelResponse, tier: int,
) -> ModelVote | None:
    """Convert a single model response to a vote."""
    if not resp.parsed:
        return None
    parsed = resp.parsed
    verdict = str(parsed.get("verdict", "cannot_verify"))
    confidence_raw = parsed.get("confidence", 0.0)
    confidence = float(str(confidence_raw)) if confidence_raw else 0.0

    evidence_raw = parsed.get("evidence_quotes", [])
    evidence: list[str] = []
    if isinstance(evidence_raw, list):
        evidence = [str(q) for q in evidence_raw]

    cost = (
        resp.input_tokens / 1_000_000 * resp.model.input_cost_per_m
        + resp.output_tokens / 1_000_000 * resp.model.output_cost_per_m
    )
    return ModelVote(
        model_name=resp.model.name,
        model_id=resp.model.litellm_id,
        abbreviation=resp.model.abbreviation,
        tier=tier,
        verdict=verdict,
        confidence=min(1.0, max(0.0, confidence)),
        reasoning=str(parsed.get("reasoning", "")),
        evidence_quotes=evidence,
        response_time_ms=resp.response_time_ms,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cost_usd=round(cost, 6),
    )


def build_tiebreaker(
    all_votes: list[ModelVote],
    final_vote: ModelVote,
    escalation_path: list[int],
) -> ConsensusResult:
    """Build consensus from a tiebreaker/final vote."""
    return ConsensusResult(
        verdict=final_vote.verdict,
        confidence=final_vote.confidence,
        consensus_type="tiebreaker",
        votes=all_votes,
        merged_reasoning=final_vote.reasoning,
        merged_evidence=final_vote.evidence_quotes,
        final_tier=final_vote.tier,
        escalation_path=list(escalation_path),
        agreement_ratio=calc_agreement(all_votes, final_vote.verdict),
    )


def fallback_consensus(
    all_votes: list[ModelVote],
    escalation_path: list[int],
) -> ConsensusResult:
    """When all tiers exhausted, use best available vote."""
    if not all_votes:
        return ConsensusResult(
            verdict="cannot_verify", confidence=0.0,
            consensus_type="no_models", escalation_path=escalation_path,
        )
    best = max(all_votes, key=lambda v: v.confidence)
    return ConsensusResult(
        verdict=best.verdict, confidence=max(0.0, best.confidence - 0.1),
        consensus_type="fallback", votes=all_votes,
        merged_reasoning=best.reasoning,
        merged_evidence=best.evidence_quotes,
        final_tier=best.tier, escalation_path=escalation_path,
        agreement_ratio=calc_agreement(all_votes, best.verdict),
    )


def calc_agreement(votes: list[ModelVote], verdict: str) -> float:
    """Calculate what fraction of active votes agree with the verdict."""
    active = [v for v in votes if v.verdict != "cannot_verify"]
    if not active:
        return 0.0
    matching = sum(1 for v in active if v.verdict == verdict)
    return round(matching / len(active), 3)
