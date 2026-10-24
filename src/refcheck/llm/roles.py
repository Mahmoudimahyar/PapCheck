"""Role status (static or probed) on top of role -> model resolution.

Resolution lives in refcheck.llm.candidates (re-exported here). A status says
which model a role resolves to and, V5.8, whether the role runs degraded: a
degraded fallback model (confirm), skipped (screen), BM25-only (embedding) or
no model at all, with the cause (billing / quota vs key vs network) and the fix.
"""

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from refcheck.llm.availability import (
    mark_available,
    mark_unavailable,
    reset_availability,
    unavailable_models,
)
from refcheck.llm.candidates import (
    degraded_candidates,
    degraded_fallbacks_enabled,
    is_available,
    is_degraded_model,
    primary_candidates,
    privacy_profile,
    resolve_role,
    role_candidates,
    role_effort,
    same_family,
    screen_enabled,
    unavailable_reason,
)
from refcheck.llm.degradation import Degradation, Mode, build
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.types import ALL_ROLES, PrivacyProfile, Role

__all__ = [
    "Role", "RoleStatus", "assess_degradation", "degraded_candidates",
    "degraded_fallbacks_enabled", "is_available", "is_degraded_model", "mark_available",
    "mark_unavailable", "primary_candidates", "privacy_profile", "reset_availability",
    "resolve_role", "role_candidates", "role_effort", "role_status", "same_family",
    "screen_enabled", "static_failures", "status_for", "unavailable_models",
    "unavailable_reason", "with_degradation",
]

_SOFT_MODE: dict[str, Mode] = {"screen": "skipped", "embedding": "bm25_only"}


class RoleStatus(BaseModel):
    """Resolution (and optional live probe) state of one role."""

    role: Role
    model_id: str | None = None
    litellm_id: str | None = None
    provider: str | None = None
    display_name: str | None = None
    reasoning_effort: str | None = None
    available: bool = False
    reason: str | None = None
    fallback_index: int = 0
    candidates: list[str] = Field(default_factory=list)
    privacy_profile: PrivacyProfile = "standard"
    probed: bool = False
    probe_ok: bool | None = None
    latency_ms: int | None = None
    checked_at: float | None = None
    tried: list[str] = Field(default_factory=list)
    # V5.8 degraded mode (see refcheck.llm.degradation)
    degraded: bool = False
    degraded_mode: str | None = None
    cause: str | None = None
    persistent: bool = False
    effect: str | None = None
    action: str | None = None


def _first_failure(role: Role, failures: Sequence[tuple[str, str | None, str]]
                   ) -> tuple[str | None, str | None, str]:
    """(kind, provider, text) of the first failed NORMAL candidate (the real cause)."""
    normal = {c.id: c.provider for c in primary_candidates(role)}
    for model_id, kind, text in failures:
        if model_id in normal:
            return kind, normal[model_id], text
    if failures:
        return failures[0][1], None, failures[0][2]
    return None, None, ""


def assess_degradation(role: Role, spec: ModelSpec | None,
                       failures: Sequence[tuple[str, str | None, str]]) -> Degradation | None:
    """Degradation of a role given its resolved spec and (model, kind, text) failures."""
    if spec is not None and not is_degraded_model(role, spec.id):
        return None
    if spec is None and not role_candidates(role):
        return None  # switched off on purpose (screen off, anthropic_only)
    kind, provider, text = _first_failure(role, failures)
    mode: Mode = "fallback" if spec is not None else _SOFT_MODE.get(role, "unavailable")
    item = build(role, mode, kind=kind, reason=text, provider=provider,
                 fallback_model=spec.id if spec else None)
    verifier = resolve_role("verifier") if role == "confirm" and spec is not None else None
    if verifier is not None and not same_family(verifier, spec):  # still a cross-family check
        item = item.model_copy(update={"effect": f"cross-check runs on the fallback model "
                                                  f"{spec.id if spec else ''}"})
    return item


def with_degradation(status: RoleStatus, item: Degradation | None) -> RoleStatus:
    """Copy of ``status`` carrying the degradation fields."""
    if item is None:
        return status
    return status.model_copy(update={
        "degraded": True, "degraded_mode": item.mode, "cause": item.cause,
        "persistent": item.persistent, "effect": item.effect, "action": item.action,
    })


def static_failures(candidates: Iterable[ModelSpec]) -> list[tuple[str, str | None, str]]:
    """(model, None, 'kind: why') for each candidate that cannot be used right now."""
    out: list[tuple[str, str | None, str]] = []
    for c in candidates:
        why = unavailable_reason(c)
        if why:
            out.append((c.id, None, why))
    return out


def status_for(role: Role) -> RoleStatus:
    """Static (no network) status of one role."""
    candidates = role_candidates(role)
    spec = resolve_role(role)
    reason = None
    failures = static_failures(candidates)
    if spec is None:
        if not candidates:
            disabled = role == "screen" or privacy_profile() == "anthropic_only"
            reason = "role disabled" if disabled else "no candidate models"
        else:
            reason = "; ".join(f"{mid}: {text}" for mid, _, text in failures)
    elif is_degraded_model(role, spec.id):
        reason = "; ".join(f"{mid}: {text}" for mid, _, text in failures) or None
    status = RoleStatus(
        role=role, model_id=spec.id if spec else None,
        litellm_id=spec.litellm_id if spec else None,
        provider=spec.provider if spec else None,
        display_name=spec.label if spec else None,
        reasoning_effort=spec.reasoning_effort if spec else None,
        available=spec is not None, reason=reason,
        fallback_index=[c.id for c in candidates].index(spec.id) if spec else 0,
        candidates=[c.id for c in candidates], privacy_profile=privacy_profile(),
    )
    return with_degradation(status, assess_degradation(role, spec, failures))


def role_status(roles: Iterable[Role] = ALL_ROLES) -> dict[str, RoleStatus]:
    """Static status for /api/health (no API calls)."""
    return {role: status_for(role) for role in roles}
