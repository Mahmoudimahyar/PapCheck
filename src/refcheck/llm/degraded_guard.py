"""Degraded-mode bookkeeping and spending cap for chat calls (V5.8).

A call that lands on a degraded fallback (e.g. confirm on claude-sonnet-5-5
because the OpenAI account has no credits) is recorded on the run's tracker,
and once the role's degraded spend reaches the cap the call is refused with
CostLimitExceededError: the cascade then keeps the verifier's verdict and
queues the pair for review ("cross-check call failed"), so cost stays bounded.

Cap: ``REFCHECK_DEGRADED_MAX_USD`` (USD per role per run), default the smaller
of $2 and a quarter of the run budget (CostTracker.max_cost). Each degraded call
reserves its estimated cost (the role's mean degraded call so far, else
EST_CALL_USD) under the tracker's lock before it is sent and releases it after,
so concurrent calls (12 pairs at once) cannot all pass a cap that one of them
would reach: the spend stays within the cap plus about one call.

Soft roles (screen / embedding): a persistent failure (billing, key, model) is
recorded at once; a transient one (timeout, network, rate limit) only after
TRANSIENT_MIN failures in the run, with the count, so one timed-out call among
hundreds is not reported as a run-wide outage.
"""

import logging
import os

from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.degradation import record
from refcheck.llm.errors import LLMError, short_error
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.roles import (
    assess_degradation,
    degraded_candidates,
    is_available,
    is_degraded_model,
    primary_candidates,
    static_failures,
)
from refcheck.llm.types import Role

logger = logging.getLogger(__name__)

__all__ = ["degraded_cap_usd", "fallback_allowed", "guard_degraded", "note_soft_failure",
           "release_degraded"]

_DEFAULT_CAP_USD = 2.0
_BUDGET_SHARE = 0.25
EST_CALL_USD = 0.03  # a degraded confirm call (sonnet, low effort) before any is recorded
TRANSIENT_MIN = 3


def degraded_cap_usd(tracker: CostTracker) -> float:
    """Per-role, per-run spending cap for degraded fallback models."""
    raw = os.environ.get("REFCHECK_DEGRADED_MAX_USD", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            logger.warning("Ignoring invalid REFCHECK_DEGRADED_MAX_USD=%r", raw)
    return min(_DEFAULT_CAP_USD, _BUDGET_SHARE * tracker.max_cost)


def fallback_allowed(role: Role, spec: ModelSpec) -> bool:
    """A degraded fallback replaces normal models only when they are GONE (no key,
    no credits, benched by a failed probe), never after one refusal / bad answer."""
    if not is_degraded_model(role, spec.id):
        return True
    return not any(is_available(c) for c in primary_candidates(role))


def guard_degraded(role: Role, spec: ModelSpec, tracker: CostTracker | None,
                   last_error: LLMError | None) -> float:
    """Record a degraded call and reserve its estimated cost against the cap (no-op,
    0.0, for normal models); pass the result to ``release_degraded`` after the call."""
    if not is_degraded_model(role, spec.id):
        return 0.0
    failures = static_failures(primary_candidates(role))
    if last_error is not None:
        failures.insert(0, (last_error.model_id or "", last_error.kind,
                            f"{last_error.kind}: {short_error(last_error, 200)}"))
    item = assess_degradation(role, spec, failures)
    if item is not None:
        record(item, tracker)
    if tracker is None:
        return 0.0
    cap = degraded_cap_usd(tracker)
    models = {c.id for c in degraded_candidates(role)}
    reserved = tracker.reserve(role, models, cap, EST_CALL_USD)
    if reserved is None:
        spent = tracker.spent(role, models)
        raise CostLimitExceededError(
            f"degraded-mode cap ${cap:.2f} for role {role} reached (${spent:.2f} spent or "
            f"reserved on {spec.id}); set REFCHECK_DEGRADED_MAX_USD to allow more")
    return reserved


def release_degraded(role: Role | None, tracker: CostTracker | None, reserved: float) -> None:
    """Give back a call's reservation (its real cost is recorded by then)."""
    if role is not None and tracker is not None and reserved:
        tracker.release(role, reserved)


_OUTAGE_KINDS = frozenset({"billing", "auth", "not_found", "unavailable", "transient",
                           "timeout", "rate_limit"})


def note_soft_failure(role: Role, model_id: str | None, kind: str | None, text: str,
                      tracker: CostTracker | None) -> None:
    """Record that a soft role (screen / embedding) failed and was skipped for a call.

    Only outages count (billing / key / network...); a one-off bad request or an
    unreadable answer for one input is not a degraded role, and a transient failure
    only from the TRANSIENT_MIN-th in the run on (module doc).
    """
    if kind not in _OUTAGE_KINDS:
        return
    failures = ([(model_id, kind, f"{kind}: {text}")] if model_id and kind != "unavailable"
                else static_failures(primary_candidates(role)))
    item = assess_degradation(role, None, failures)
    if item is None:
        return
    if not item.persistent and tracker is not None:
        count = tracker.count_soft_failure(role)
        if count < TRANSIENT_MIN:
            return  # a few transient failures are not a run-wide outage (module doc)
        item = item.model_copy(update={"failures": count})
    record(item, tracker)
