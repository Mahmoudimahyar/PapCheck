"""Role -> ordered candidate models, availability and resolution.

Each role has an ordered candidate list (env override or profile defaults);
the first AVAILABLE candidate wins. Available = provider key present AND not
marked unavailable (refcheck.llm.availability) after a hard failure
(auth/billing/404) in this process, or after a failed preflight probe.
V5.8: degraded fallbacks (model_registry.DEGRADED_FALLBACKS) follow the normal
candidates, so they are only used once every normal model is gone.

Env: ``REFCHECK_<ROLE>_MODEL`` (comma list allowed; replaces the defaults),
``REFCHECK_<ROLE>_EFFORT``, ``REFCHECK_SCREEN_ENABLED`` (default true),
``REFCHECK_PRIVACY_PROFILE`` = standard | anthropic_only,
``REFCHECK_DEGRADED_FALLBACKS`` (default on).
"""

import logging
import os
from collections.abc import Iterable

from refcheck.llm import keys
from refcheck.llm.availability import marked_reason
from refcheck.llm.model_lookup import spec_for
from refcheck.llm.model_registry import DEGRADED_FALLBACKS, PROFILE_ROLE_DEFAULTS, ROLE_EFFORT
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.types import ModelKind, PrivacyProfile, Role

logger = logging.getLogger(__name__)

ROLE_KIND: dict[Role, ModelKind] = {
    "screen": "decision", "embedding": "embedding", "verifier": "chat",
    "judge": "chat", "confirm": "chat", "adjudicator": "chat", "utility": "chat",
}
_FALSE = {"0", "false", "no", "off"}


def privacy_profile() -> PrivacyProfile:
    """Active privacy profile (invalid values fall back to standard)."""
    raw = os.environ.get("REFCHECK_PRIVACY_PROFILE", "standard").strip().lower()
    if raw == "anthropic_only":
        return "anthropic_only"
    if raw not in ("", "standard"):
        logger.warning("Unknown REFCHECK_PRIVACY_PROFILE=%r; using standard", raw)
    return "standard"


def screen_enabled() -> bool:
    """Screen layer switch (env) — always off under anthropic_only."""
    if privacy_profile() == "anthropic_only":
        return False
    return os.environ.get("REFCHECK_SCREEN_ENABLED", "true").strip().lower() not in _FALSE


def degraded_fallbacks_enabled() -> bool:
    """V5.8 degraded-mode fallbacks switch (default on)."""
    raw = os.environ.get("REFCHECK_DEGRADED_FALLBACKS", "on").strip().lower()
    return raw not in _FALSE


def _env_list(name: str) -> list[str]:
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


def role_effort(role: Role) -> str | None:
    """Requested effort for a role (env override or ROLE_EFFORT)."""
    override = os.environ.get(f"REFCHECK_{role.upper()}_EFFORT", "").strip().lower()
    return override or ROLE_EFFORT.get(role)


def _specs(role: Role, names: Iterable[str]) -> list[ModelSpec]:
    profile = privacy_profile()
    effort = role_effort(role)
    specs: list[ModelSpec] = []
    for name in names:
        spec = spec_for(name, ROLE_KIND[role])
        if profile == "anthropic_only" and spec.provider != "anthropic":
            logger.warning("Ignoring %s for role %s: privacy profile anthropic_only", name, role)
            continue
        specs.append(spec.with_effort(effort))
    return specs


def primary_candidates(role: Role) -> list[ModelSpec]:
    """The role's normal candidates (env override or profile defaults), effort applied."""
    if role == "screen" and not screen_enabled():
        return []
    names = _env_list(f"REFCHECK_{role.upper()}_MODEL") or PROFILE_ROLE_DEFAULTS[
        privacy_profile()][role]
    return _specs(role, names)


def degraded_candidates(role: Role) -> list[ModelSpec]:
    """Last-resort candidates (V5.8); never the verifier's own model for confirm."""
    names = DEGRADED_FALLBACKS.get(role, [])
    if not names or not degraded_fallbacks_enabled():
        return []
    taken = {c.id for c in primary_candidates(role)}
    if role == "confirm":  # a blind check by the verifier's own model is no check at all
        verifier = resolve_role("verifier")
        taken |= {verifier.id} if verifier is not None else {c.id for c in
                                                             primary_candidates("verifier")}
    return [s for s in _specs(role, names) if s.id not in taken]


def role_candidates(role: Role) -> list[ModelSpec]:
    """Ordered candidate specs for a role: normal ones, then degraded fallbacks."""
    primary = primary_candidates(role)
    if role == "screen" and not primary:
        return []
    return [*primary, *degraded_candidates(role)]


def is_degraded_model(role: Role, model_id: str | None) -> bool:
    """True when ``model_id`` is one of the role's degraded fallbacks."""
    return model_id is not None and any(c.id == model_id for c in degraded_candidates(role))


def is_available(spec: ModelSpec) -> bool:
    """Key present and not disabled by a hard failure (or a recent failed probe)."""
    if marked_reason(spec.id) is not None:
        return False
    return keys.has_key(spec.provider)


def unavailable_reason(spec: ModelSpec) -> str | None:
    """Why a spec is unavailable (None when it is usable), as 'kind: detail'."""
    reason = marked_reason(spec.id)
    if reason:
        return reason
    problem = keys.key_problem(spec.provider)
    if problem == "no_key":
        return f"no_key: no usable {spec.provider} API key (none configured)"
    if problem is not None:
        return f"{problem}: no usable {spec.provider} API key (every key failed: {problem})"
    return None


def resolve_role(role: Role, exclude: Iterable[str] = ()) -> ModelSpec | None:
    """First available candidate for a role, or None (role disabled/dead)."""
    skip = set(exclude)
    for spec in role_candidates(role):
        if spec.id not in skip and is_available(spec):
            return spec
    return None


def same_family(a: ModelSpec | None, b: ModelSpec | None) -> bool:
    """True when two layers' models come from the same model family."""
    return a is not None and b is not None and a.family == b.family
