"""Stage 5 outcome assessment: LLM-error circuit breaker + cost summary."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel

from refcheck.models.verification import reached_llm

if TYPE_CHECKING:
    from refcheck.llm.cost_tracker import CostSummary
    from refcheck.models.verification import VerificationResult

LLM_ERROR_THRESHOLD = 0.05


class VerificationStageError(RuntimeError):
    """Stage 5 failed outright; the pipeline stops and the session errors."""


class VerifyOutcome(BaseModel):
    """How a verification run went, from its results."""

    total: int = 0
    sourced: int = 0
    llm_errors: int = 0
    error_rate: float = 0.0
    breaker_tripped: bool = False
    message: str = ""


def describe_exception(exc: BaseException) -> str:
    """User-facing text for an exception (message passed through as-is)."""
    msg = str(exc).strip()
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def assess_verifications(results: "list[VerificationResult]") -> VerifyOutcome:
    """Trip the breaker if >5% of sourced pairs ended in an LLM error.

    "Sourced" = pairs that went to the LLM cascade; pairs short-circuited for
    a source reason (scanned PDF, wrong paper) would only dilute the rate.
    """
    sourced = [r for r in results if reached_llm(r)]
    errors = sum(1 for r in sourced if r.cannot_verify_reason == "llm_error")
    rate = errors / len(sourced) if sourced else 0.0
    outcome = VerifyOutcome(
        total=len(results), sourced=len(sourced),
        llm_errors=errors, error_rate=round(rate, 4),
    )
    if rate <= LLM_ERROR_THRESHOLD:
        return outcome
    return outcome.model_copy(update={
        "breaker_tripped": True,
        "message": (
            f"Verification degraded: {errors} of {len(sourced)} sourced "
            f"claim-reference pairs ({rate:.0%}) failed with LLM/API errors "
            f"(limit {LLM_ERROR_THRESHOLD:.0%}). Results were saved; failed pairs "
            "are marked cannot_verify (llm_error). Check model/API status "
            "(/api/health?deep=true) and re-run verification."
        ),
    })


def cost_by_role(summary: "CostSummary") -> dict[str, float]:
    """Per-role cost if the tracker reports it (falls back to per-task)."""
    data = summary.model_dump()
    for key in ("by_role", "by_task"):
        value = data.get(key)
        if isinstance(value, Mapping) and value:
            return {
                str(k): round(float(v), 4)
                for k, v in value.items() if isinstance(v, int | float)
            }
    return {}


def format_cost(summary: "CostSummary") -> str:
    """Total plus per-role breakdown, e.g. "$0.42 (judge $0.36, verifier $0.05)"."""
    parts = sorted(cost_by_role(summary).items(), key=lambda kv: -kv[1])
    detail = ", ".join(f"{k} ${v:.2f}" for k, v in parts if v > 0)
    total = f"${summary.total_usd:.2f}"
    return f"{total} ({detail})" if detail else total


def outcome_progress(
    outcome: VerifyOutcome, summary: "CostSummary",
) -> dict[str, float]:
    """Numeric stage-complete payload: counts, error rate and cost by role."""
    progress: dict[str, float] = {
        "current": float(outcome.total),
        "total": float(outcome.total),
        "percent": 100.0,
        "llm_errors": float(outcome.llm_errors),
        "llm_error_rate": outcome.error_rate,
        "cost_usd": float(summary.total_usd),
    }
    for role, cost in cost_by_role(summary).items():
        progress[f"cost_{role}_usd"] = cost
    return progress
