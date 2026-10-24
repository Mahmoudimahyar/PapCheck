"""Tests for ModelReasoning serialization and evidence endpoint (V2)."""

from refcheck.models.verification import ModelReasoning, VerificationResult


def test_model_reasoning_serialization() -> None:
    """ModelReasoning serializes and deserializes correctly."""
    mr = ModelReasoning(
        model_name="anthropic/claude-sonnet-5-5",
        model_display="Claude Sonnet 4.5",
        verdict="supported",
        confidence=0.85,
        reasoning="The paper clearly states...",
        evidence_quotes=["exact quote from source"],
        source_section_preview="First 500 chars...",
        response_time_ms=2340,
        input_tokens=1847,
        output_tokens=312,
    )
    data = mr.model_dump()
    assert data["model_name"] == "anthropic/claude-sonnet-5-5"
    assert data["response_time_ms"] == 2340

    restored = ModelReasoning.model_validate(data)
    assert restored.model_display == "Claude Sonnet 4.5"
    assert restored.input_tokens == 1847


def test_verification_result_with_reasoning() -> None:
    """VerificationResult stores model_reasoning list."""
    mr = ModelReasoning(
        model_name="test-model",
        model_display="Test Model",
        verdict="supported",
        confidence=0.90,
        reasoning="Test reasoning",
        evidence_quotes=["quote1"],
        response_time_ms=1000,
        input_tokens=500,
        output_tokens=200,
    )
    result = VerificationResult(
        claim_id=1,
        reference_id=1,
        verdict="supported",
        confidence=0.90,
        reasoning="Test",
        model_reasoning=[mr],
        cannot_verify_reason=None,
        section_relevance="high",
        text_quality_score=0.95,
    )
    assert len(result.model_reasoning) == 1
    assert result.model_reasoning[0].model_display == "Test Model"


def test_verification_result_v2_fields_default() -> None:
    """V2 fields have correct defaults."""
    result = VerificationResult(claim_id=1, reference_id=1)
    assert result.model_reasoning == []
    assert result.cannot_verify_reason is None
    assert result.section_relevance == "high"
    assert result.text_quality_score == 1.0


def test_model_reasoning_json_roundtrip() -> None:
    """ModelReasoning survives JSON roundtrip."""
    mr = ModelReasoning(
        model_name="test",
        model_display="Test",
        verdict="cannot_verify",
        confidence=0.3,
        reasoning="Not enough info",
        evidence_quotes=[],
    )
    json_str = mr.model_dump_json()
    restored = ModelReasoning.model_validate_json(json_str)
    assert restored.verdict == "cannot_verify"
    assert restored.confidence == 0.3
