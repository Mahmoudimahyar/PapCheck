"""Confidence scoring and threshold logic for PDF matching."""

from refcheck.models.matching import MatchResult

AUTO_ACCEPT_THRESHOLD = 0.90
CONFIRM_THRESHOLD = 0.60


def classify_match(result: MatchResult) -> MatchResult:
    """Classify a match result based on confidence thresholds."""
    if result.confidence >= AUTO_ACCEPT_THRESHOLD:
        return result.model_copy(update={"needs_user_confirmation": False})
    if result.confidence >= CONFIRM_THRESHOLD:
        return result.model_copy(update={"needs_user_confirmation": True})
    return result.model_copy(
        update={"match_method": "unmatched", "needs_user_confirmation": False}
    )
