"""Tests for the not_relevant verdict across backend models and API."""


from refcheck.models.cannot_verify import CannotVerifyReason
from refcheck.models.verification import VerificationResult


class TestNotRelevantVerdict:
    """Verify not_relevant is accepted throughout the stack."""

    def test_verdict_literal_accepts_not_relevant(self) -> None:
        """VerificationResult should accept 'not_relevant' verdict."""
        result = VerificationResult(
            claim_id=1,
            reference_id=1,
            verdict="not_relevant",
            confidence=0.90,
            tier=1,
        )
        assert result.verdict == "not_relevant"

    def test_cannot_verify_reason_has_not_relevant(self) -> None:
        """CannotVerifyReason enum should include NOT_RELEVANT."""
        assert hasattr(CannotVerifyReason, "NOT_RELEVANT")
        assert CannotVerifyReason.NOT_RELEVANT.value == "not_relevant"

    def test_retry_fields_on_verification_result(self) -> None:
        """VerificationResult should have retry tracking fields."""
        result = VerificationResult(
            claim_id=1,
            reference_id=1,
            verdict="cannot_verify",
            confidence=0.0,
            tier=1,
            retry_strategy_used="broader_sections",
            retry_attempts=2,
        )
        assert result.retry_strategy_used == "broader_sections"
        assert result.retry_attempts == 2

    def test_default_retry_fields(self) -> None:
        """Retry fields default to None/0."""
        result = VerificationResult(
            claim_id=1,
            reference_id=1,
            verdict="supported",
            confidence=0.85,
            tier=1,
        )
        assert result.retry_strategy_used is None
        assert result.retry_attempts == 0


class TestResultsSummaryNotRelevant:
    """Verify not_relevant in the results API schema."""

    def test_results_summary_has_not_relevant(self) -> None:
        from refcheck.api.routes.results_schemas import ResultsSummary

        summary = ResultsSummary(
            total=10,
            supported=5,
            partially_supported=2,
            not_supported=1,
            contradicted=0,
            cannot_verify=1,
            not_relevant=1,
        )
        assert summary.not_relevant == 1
