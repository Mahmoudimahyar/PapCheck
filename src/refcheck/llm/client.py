"""Unified LLM call wrapper: template -> role/model -> validated Pydantic.

``call_llm`` returns the parsed model; ``call_llm_raw`` also returns usage,
cost, latency and the model that actually answered. Without an explicit
``model`` the role's first available model is used and hard failures
(billing/auth/404) or exhausted retries fall back to the next candidate.
V5.8: a degraded fallback (model_registry.DEGRADED_FALLBACKS) is recorded on the
tracker and its spend is capped (degraded_guard), so an outage cannot run up cost.
"""

import logging
import time
from collections.abc import Mapping
from typing import TypeVar

from pydantic import BaseModel

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.degraded_guard import fallback_allowed, guard_degraded, release_degraded
from refcheck.llm.errors import (
    LLMCallError,
    LLMError,
    LLMResponseInvalidError,
    NoModelAvailableError,
)
from refcheck.llm.model_lookup import spec_for
from refcheck.llm.retry import deadline_from
from refcheck.llm.roles import mark_unavailable, resolve_role, role_candidates, role_effort
from refcheck.llm.structured import LLMCallResult, call_spec, parse_output
from refcheck.llm.templates import render_template
from refcheck.llm.types import Role

logger = logging.getLogger(__name__)

__all__ = [
    "LLMCallResult", "LLMResponseInvalidError", "call_llm", "call_llm_raw", "parse_output",
]

T = TypeVar("T", bound=BaseModel)

_FALLBACK_KINDS = frozenset({
    "rate_limit", "transient", "timeout", "refusal", "content_filter",
    "invalid_output", "context_window",
})
# A refusal/content filter is usually a provider-side classifier decision, so
# the next attempt skips every candidate of the same model family.
_FAMILY_SKIP_KINDS = frozenset({"refusal", "content_filter"})


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline - 1.0


async def call_llm_raw(
    template: str,
    variables: Mapping[str, object],
    output_model: type[T],
    model: str | None = None,
    role: Role | None = "utility",
    max_retries: int = 1,
    use_cache: bool = True,
    cost_tracker: CostTracker | None = None,
    task: str = "llm",
    max_output_tokens: int | None = None,
    *,
    system_template: str | None = None,
    system_variables: Mapping[str, object] | None = None,
    timeout: float | None = None,
) -> LLMCallResult[T]:
    """Render ``template`` and call the role's model (or ``model``).

    ``system_template`` renders a stable, cache-marked system prefix; a
    ``CACHE_BREAKPOINT`` line inside ``template`` marks a cacheable user
    prefix. ``timeout`` is the wall-clock budget for the whole call
    including retries/fallbacks. Raises LLMCallError, LLMResponseInvalidError
    (incl. LLMRefusalError), NoModelAvailableError or CostLimitExceededError.
    """
    user_text = render_template(template, dict(variables))
    system_text = (render_template(system_template, dict(system_variables or {}))
                   if system_template else None)
    deadline = deadline_from(timeout)
    args = (user_text, system_text, output_model, role, max_retries, use_cache,
            cost_tracker, task, max_output_tokens, deadline)
    if model is not None:
        spec = spec_for(model).with_effort(role_effort(role) if role else None)
        reserved = guard_degraded(role, spec, cost_tracker, None) if role is not None else 0.0
        try:
            return await call_spec(spec, *args)
        finally:
            release_degraded(role, cost_tracker, reserved)

    wanted: Role = role or "utility"
    tried: list[str] = []
    last_error: LLMError | None = None
    while True:
        spec_or_none = resolve_role(wanted, exclude=tried)
        if spec_or_none is not None and not fallback_allowed(wanted, spec_or_none):
            spec_or_none = None  # a refusal / bad answer is not an outage: no degraded model
        if spec_or_none is None:
            if last_error is not None:
                raise last_error  # every candidate failed: surface the real cause
            raise NoModelAvailableError(f"no available model for role '{wanted}'")
        reserved = guard_degraded(wanted, spec_or_none, cost_tracker, last_error)
        try:
            return await call_spec(spec_or_none, *args)
        except (LLMCallError, LLMResponseInvalidError) as exc:
            if exc.is_hard:
                mark_unavailable(spec_or_none.id, f"{exc.kind}: {exc}")
            elif exc.kind not in _FALLBACK_KINDS or _expired(deadline):
                raise
            tried.append(spec_or_none.id)
            if exc.kind in _FAMILY_SKIP_KINDS:
                family = spec_or_none.family
                tried.extend(c.id for c in role_candidates(wanted) if c.family == family)
            last_error = exc
            logger.warning("Role %s: %s failed (%s); trying next model", wanted,
                           spec_or_none.id, exc.kind)
        finally:
            release_degraded(wanted, cost_tracker, reserved)


async def call_llm(
    template: str,
    variables: Mapping[str, object],
    output_model: type[T],
    model: str | None = None,
    role: Role | None = "utility",
    max_retries: int = 1,
    use_cache: bool = True,
    cost_tracker: CostTracker | None = None,
    task: str = "llm",
    max_output_tokens: int | None = None,
    *,
    system_template: str | None = None,
    system_variables: Mapping[str, object] | None = None,
    timeout: float | None = None,
) -> T:
    """Like call_llm_raw but returns only the validated Pydantic object."""
    result = await call_llm_raw(
        template, variables, output_model, model, role, max_retries, use_cache,
        cost_tracker, task, max_output_tokens, system_template=system_template,
        system_variables=system_variables, timeout=timeout,
    )
    return result.parsed
