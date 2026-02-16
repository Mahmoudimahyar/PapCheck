"""Consensus logic for multi-model voting."""

import logging
from collections import Counter

from refcheck.llm.voting_models import ConsensusResult, ModelVote

logger = logging.getLogger(__name__)

_UNANIMOUS_BONUS = 0.05
_MAJORITY_PENALTY = 0.03
_FUZZY_DEDUP_THRESHOLD = 0.90


def determine_consensus(votes: list[ModelVote]) -> ConsensusResult:
    """Determine consensus from a list of model votes.

    Rules:
    1. ANY "contradicted" -> escalate (too important for cheap models)
    2. Filter "cannot_verify" (abstain)
    3. All abstain -> verdict = "cannot_verify"
    4. UNANIMOUS -> accept, confidence + 0.05 bonus
    5. SUPERMAJORITY (>=2/3) -> accept majority
    6. MAJORITY (>1/2) -> accept, lower confidence
    7. No majority -> consensus_type = "escalate"
    """
    if not votes:
        return _empty_result()

    # Rule 1: any contradicted -> escalate
    if any(v.verdict == "contradicted" for v in votes):
        return _escalate_result(votes, "contradicted_detected")

    # Rule 2: filter abstains
    active = [v for v in votes if v.verdict != "cannot_verify"]

    # Rule 3: all abstain
    if not active:
        reasoning, evidence = merge_evidence(votes, "cannot_verify")
        return ConsensusResult(
            verdict="cannot_verify", confidence=0.0,
            consensus_type="all_abstain", votes=votes,
            merged_reasoning=reasoning, merged_evidence=evidence,
            agreement_ratio=1.0,
        )

    # Count verdicts
    counts = Counter(v.verdict for v in active)
    total = len(active)
    top_verdict, top_count = counts.most_common(1)[0]
    ratio = top_count / total

    # Rule 4: unanimous
    if top_count == total:
        conf = min(1.0, _mean_confidence(active) + _UNANIMOUS_BONUS)
        reasoning, evidence = merge_evidence(active, top_verdict)
        return ConsensusResult(
            verdict=top_verdict, confidence=round(conf, 3),
            consensus_type="unanimous", votes=votes,
            merged_reasoning=reasoning, merged_evidence=evidence,
            agreement_ratio=1.0,
        )

    # Rule 5: supermajority (>=2/3)
    if ratio >= 2 / 3:
        agreeing = [v for v in active if v.verdict == top_verdict]
        reasoning, evidence = merge_evidence(agreeing, top_verdict)
        return ConsensusResult(
            verdict=top_verdict,
            confidence=round(_mean_confidence(agreeing), 3),
            consensus_type="supermajority", votes=votes,
            merged_reasoning=reasoning, merged_evidence=evidence,
            agreement_ratio=round(ratio, 3),
        )

    # Rule 6: majority (>1/2)
    if ratio > 0.5:
        agreeing = [v for v in active if v.verdict == top_verdict]
        conf = max(0.0, _mean_confidence(agreeing) - _MAJORITY_PENALTY)
        reasoning, evidence = merge_evidence(agreeing, top_verdict)
        return ConsensusResult(
            verdict=top_verdict, confidence=round(conf, 3),
            consensus_type="majority", votes=votes,
            merged_reasoning=reasoning, merged_evidence=evidence,
            agreement_ratio=round(ratio, 3),
        )

    # Rule 7: no majority -> escalate
    return _escalate_result(votes, "no_majority")


def merge_evidence(
    votes: list[ModelVote], verdict: str,
) -> tuple[str, list[str]]:
    """Best reasoning from highest-confidence agreeing model.

    Union of evidence quotes, fuzzy-deduped.
    """
    agreeing = [v for v in votes if v.verdict == verdict]
    if not agreeing:
        agreeing = votes
    if not agreeing:
        return "", []

    # Best reasoning from highest confidence
    best = max(agreeing, key=lambda v: v.confidence)
    reasoning = best.reasoning

    # Union of all evidence quotes, deduped
    all_quotes: list[str] = []
    seen_lower: set[str] = set()
    for v in agreeing:
        for q in v.evidence_quotes:
            normalized = q.strip().lower()
            if normalized and normalized not in seen_lower:
                seen_lower.add(normalized)
                all_quotes.append(q)

    return reasoning, all_quotes


def _mean_confidence(votes: list[ModelVote]) -> float:
    if not votes:
        return 0.0
    return sum(v.confidence for v in votes) / len(votes)


def _empty_result() -> ConsensusResult:
    return ConsensusResult(
        verdict="cannot_verify", confidence=0.0,
        consensus_type="no_votes",
    )


def _escalate_result(
    votes: list[ModelVote], reason: str,
) -> ConsensusResult:
    return ConsensusResult(
        verdict="escalate", confidence=0.0,
        consensus_type="escalate", votes=votes,
        merged_reasoning=f"Escalation needed: {reason}",
    )
