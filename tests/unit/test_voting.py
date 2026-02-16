"""Tests for voting consensus logic."""

from refcheck.llm.voting import determine_consensus, merge_evidence
from refcheck.llm.voting_models import ModelVote


def _vote(
    verdict: str = "supported",
    confidence: float = 0.85,
    name: str = "Model",
    tier: int = 0,
    reasoning: str = "Good evidence",
    evidence: list[str] | None = None,
) -> ModelVote:
    return ModelVote(
        model_name=name, model_id=f"test/{name}",
        abbreviation=name[:2].upper(), tier=tier,
        verdict=verdict, confidence=confidence,
        reasoning=reasoning,
        evidence_quotes=evidence or ["quote1"],
    )


class TestUnanimous:
    """VT-01: 3/3 unanimous -> accept."""

    def test_all_supported(self) -> None:
        votes = [_vote("supported", 0.85), _vote("supported", 0.90), _vote("supported", 0.80)]
        result = determine_consensus(votes)
        assert result.verdict == "supported"
        assert result.consensus_type == "unanimous"
        assert result.agreement_ratio == 1.0
        # Mean 0.85 + 0.05 bonus = 0.9
        assert result.confidence >= 0.85

    def test_unanimous_gets_confidence_bonus(self) -> None:
        votes = [_vote("supported", 0.80), _vote("supported", 0.80), _vote("supported", 0.80)]
        result = determine_consensus(votes)
        assert result.confidence == 0.85  # 0.80 + 0.05

    def test_all_not_supported(self) -> None:
        votes = [_vote("not_supported"), _vote("not_supported"), _vote("not_supported")]
        result = determine_consensus(votes)
        assert result.verdict == "not_supported"
        assert result.consensus_type == "unanimous"


class TestSupermajority:
    """VT-02: 2/3 agree -> supermajority."""

    def test_two_of_three(self) -> None:
        votes = [
            _vote("supported", 0.85),
            _vote("supported", 0.80),
            _vote("partially_supported", 0.70),
        ]
        result = determine_consensus(votes)
        assert result.verdict == "supported"
        assert result.consensus_type == "supermajority"
        assert result.agreement_ratio >= 0.66


class TestEscalate:
    """VT-03: all different -> escalate."""

    def test_all_different_verdicts(self) -> None:
        votes = [
            _vote("supported", 0.85),
            _vote("not_supported", 0.80),
            _vote("partially_supported", 0.70),
        ]
        result = determine_consensus(votes)
        assert result.consensus_type == "escalate"

    def test_split_fifty_fifty(self) -> None:
        votes = [_vote("supported", 0.85), _vote("not_supported", 0.80)]
        result = determine_consensus(votes)
        assert result.consensus_type == "escalate"


class TestContradicted:
    """VT-04: 1 contradicted + 2 supported -> escalate."""

    def test_any_contradicted_escalates(self) -> None:
        votes = [
            _vote("supported", 0.90),
            _vote("supported", 0.85),
            _vote("contradicted", 0.80),
        ]
        result = determine_consensus(votes)
        assert result.consensus_type == "escalate"
        assert result.verdict == "escalate"


class TestAllCannotVerify:
    """VT-05: all cannot_verify -> accept cannot_verify."""

    def test_all_abstain(self) -> None:
        votes = [
            _vote("cannot_verify", 0.30),
            _vote("cannot_verify", 0.20),
            _vote("cannot_verify", 0.10),
        ]
        result = determine_consensus(votes)
        assert result.verdict == "cannot_verify"
        assert result.consensus_type == "all_abstain"


class TestMergeEvidence:
    """Test evidence merging from multiple votes."""

    def test_best_reasoning_from_highest_confidence(self) -> None:
        votes = [
            _vote("supported", 0.90, reasoning="Best reasoning"),
            _vote("supported", 0.70, reasoning="Okay reasoning"),
        ]
        reasoning, _ = merge_evidence(votes, "supported")
        assert reasoning == "Best reasoning"

    def test_deduplicates_evidence_quotes(self) -> None:
        votes = [
            _vote("supported", evidence=["quote A", "quote B"]),
            _vote("supported", evidence=["quote B", "quote C"]),
        ]
        _, evidence = merge_evidence(votes, "supported")
        assert len(evidence) == 3

    def test_empty_votes_returns_empty(self) -> None:
        reasoning, evidence = merge_evidence([], "supported")
        assert reasoning == ""
        assert evidence == []


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_votes_returns_no_votes(self) -> None:
        result = determine_consensus([])
        assert result.consensus_type == "no_votes"
        assert result.verdict == "cannot_verify"

    def test_single_vote_is_unanimous(self) -> None:
        result = determine_consensus([_vote("supported", 0.90)])
        assert result.verdict == "supported"
        assert result.consensus_type == "unanimous"

    def test_cannot_verify_filtered_before_counting(self) -> None:
        votes = [
            _vote("supported", 0.85),
            _vote("cannot_verify", 0.10),
            _vote("supported", 0.80),
        ]
        result = determine_consensus(votes)
        assert result.verdict == "supported"
        assert result.consensus_type == "unanimous"
