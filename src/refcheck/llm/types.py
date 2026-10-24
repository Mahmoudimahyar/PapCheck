"""Shared literal types for the LLM layer (kept tiny to avoid import cycles)."""

from typing import Literal

Role = Literal["screen", "verifier", "judge", "confirm", "adjudicator", "utility", "embedding"]
ALL_ROLES: tuple[Role, ...] = (
    "screen", "verifier", "judge", "confirm", "adjudicator", "utility", "embedding",
)
# V5.8: only a dead verifier stops a run; every other role degrades (llm.degradation).
HARD_ROLES: tuple[Role, ...] = ("verifier",)
ModelKind = Literal["chat", "decision", "embedding"]
PrivacyProfile = Literal["standard", "anthropic_only"]

# Error kinds produced by refcheck.llm.errors.classify_error.
ErrorKind = Literal[
    "rate_limit", "transient", "timeout", "billing", "auth", "not_found",
    "bad_request", "context_window", "content_filter", "invalid_output",
    "refusal", "budget", "unavailable", "other",
]

# Hard failures make a model (or key) unusable for the rest of the process.
HARD_FAILURES: frozenset[str] = frozenset({"billing", "auth", "not_found", "unavailable"})
RETRYABLE: frozenset[str] = frozenset({"rate_limit", "transient", "timeout"})
