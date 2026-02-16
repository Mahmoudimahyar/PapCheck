"""Data models for multi-model voting and consensus."""

from pydantic import BaseModel, Field


class ModelVote(BaseModel):
    """A single model's vote on a verification claim."""

    model_name: str
    model_id: str
    abbreviation: str
    tier: int
    verdict: str
    confidence: float
    reasoning: str
    evidence_quotes: list[str] = Field(default_factory=list)
    response_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ConsensusResult(BaseModel):
    """Result of the multi-model voting consensus."""

    verdict: str
    confidence: float
    consensus_type: str  # unanimous, supermajority, majority, tiebreaker, escalate
    votes: list[ModelVote] = Field(default_factory=list)
    merged_reasoning: str = ""
    merged_evidence: list[str] = Field(default_factory=list)
    final_tier: int = 0
    escalation_path: list[int] = Field(default_factory=list)
    agreement_ratio: float = 0.0
