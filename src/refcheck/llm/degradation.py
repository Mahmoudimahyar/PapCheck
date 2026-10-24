"""Graceful degradation (V5.8): which LLM roles run degraded, why, and what to do.

Only the verifier is a hard role. When a soft role loses every normal model:
confirm falls back to an Anthropic model that is not the verifier (same family,
so its confirmations go to review; spend capped), the screen is skipped (risk
ranking only) and retrieval uses BM25 only. Each case is recorded here: in a
process-wide registry (``/api/health``) and on the run's CostTracker (report).
``cause`` separates persistent problems (billing / quota, bad or missing key,
unknown model: "add credits") from transient ones (network, rate limit).
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from refcheck.llm.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

Cause = Literal["billing", "auth", "no_key", "not_found", "network", "rate_limit", "refusal",
                "budget", "other"]
Mode = Literal["fallback", "skipped", "bm25_only", "unavailable"]
PERSISTENT_CAUSES: frozenset[str] = frozenset({"billing", "auth", "no_key", "not_found"})
_KIND_CAUSE: dict[str, Cause] = {
    "billing": "billing", "auth": "auth", "no_key": "no_key", "not_found": "not_found",
    "transient": "network", "timeout": "network", "rate_limit": "rate_limit",
    "refusal": "refusal", "content_filter": "refusal", "budget": "budget",
}
_CAUSE_TEXT: dict[str, str] = {
    "billing": "no credits / quota exhausted", "auth": "API key rejected",
    "no_key": "no API key configured", "not_found": "model not available to this account",
    "network": "temporary network / server error", "rate_limit": "rate limited",
    "refusal": "the model refused", "budget": "degraded-mode spending cap reached",
    "other": "error",
}
# File a run's degradations are saved to, next to the session (report hand-off).
RUN_FILE = "llm_degradations.json"
_PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini",
                   "xai": "xAI"}
_EFFECTS: dict[str, str] = {
    "screen": "fast screen skipped (risk ranking only; every pair still goes to the verifier)",
    "embedding": "retrieval uses keyword (BM25) ranking only",
    "confirm": "cross-check runs on {model}, the same model family as the verifier: its "
               "confirmations are queued for human review",
}


class Degradation(BaseModel):
    """One role running degraded (or not at all) in this process / run."""

    role: str
    mode: Mode
    cause: Cause = "other"
    persistent: bool = False
    reason: str = ""
    provider: str | None = None
    fallback_model: str | None = None
    effect: str = ""
    action: str | None = None
    at: float = 0.0
    failures: int = 0  # transient soft-role failures counted in the run (0: not counted)


def cause_of(kind: str | None, text: str = "") -> Cause:
    """Map an LLM ErrorKind (or a 'kind: message' reason string) onto a Cause."""
    if kind in _KIND_CAUSE:
        return _KIND_CAUSE[kind]
    head = text.split(":", 1)[0].strip().lower()
    if head in _KIND_CAUSE:
        return _KIND_CAUSE[head]
    low = text.lower()
    if any(m in low for m in ("insufficient_quota", "credit", "quota", "billing")):
        return "billing"
    if "no usable" in low or "api key" in low:
        return "no_key"
    return "other"


def action_for(cause: str, provider: str | None) -> str | None:
    """What the user can do about it (None = transient, retried automatically)."""
    name = _PROVIDER_NAMES.get(provider or "", provider or "the provider")
    if cause == "billing":
        return f"Add credits to the {name} account (or set a key with credit), then re-run."
    if cause in ("auth", "no_key"):
        return f"Check the {name} API key in .env, then re-run."
    if cause == "not_found":
        return f"Pick another model for this role (REFCHECK_<ROLE>_MODEL); {name} rejected it."
    if cause == "budget":
        return "Raise REFCHECK_DEGRADED_MAX_USD, or restore the normal model."
    return None


def effect_for(role: str, mode: Mode, fallback_model: str | None) -> str:
    """Plain-language consequence for the report / UI."""
    if mode == "fallback" and role != "confirm":
        return f"runs on the fallback model {fallback_model}"
    if mode == "unavailable":
        return "no working model: this role is skipped"
    return _EFFECTS.get(role, "degraded").format(model=fallback_model or "a fallback model")


def build(role: str, mode: Mode, *, kind: str | None = None, reason: str = "",
          provider: str | None = None, fallback_model: str | None = None) -> Degradation:
    """A Degradation with cause / action / effect filled in."""
    cause = cause_of(kind, reason)
    return Degradation(
        role=role, mode=mode, cause=cause, persistent=cause in PERSISTENT_CAUSES,
        reason=reason[:240], provider=provider, fallback_model=fallback_model,
        effect=effect_for(role, mode, fallback_model), action=action_for(cause, provider),
        at=time.time(),
    )


def describe(item: Degradation) -> str:
    """One sentence: role, cause, effect and (if persistent) the fix."""
    who = _PROVIDER_NAMES.get(item.provider or "", item.provider or "")
    why = _CAUSE_TEXT.get(item.cause, item.cause)
    text = f"{item.role}: {who + ' ' if who else ''}{why} — {item.effect}."
    if item.failures and not item.persistent:
        text = f"{text[:-1]} for {item.failures} failed calls; the other calls ran normally."
    return f"{text} {item.action}" if item.action else text


_lock = threading.Lock()
_registry: dict[str, Degradation] = {}
_TRANSIENT_TTL_S = 900.0


def note(item: Degradation) -> None:
    """Record a degradation process-wide (latest per role)."""
    with _lock:
        if item.role not in _registry:
            logger.warning("Degraded LLM role: %s", describe(item))
        _registry[item.role] = item


def record(item: Degradation, tracker: "CostTracker | None" = None) -> None:
    """Note a degradation process-wide and on the run's tracker (report / summary)."""
    note(item)
    if tracker is not None:
        tracker.note_degraded(item)


def current() -> dict[str, Degradation]:
    """Live degradations (transient ones expire after 15 minutes)."""
    now = time.time()
    with _lock:
        for role, item in list(_registry.items()):
            if not item.persistent and now - item.at > _TRANSIENT_TTL_S:
                del _registry[role]
        return dict(_registry)


def clear(role: str | None = None) -> None:
    """Forget one role's degradation (it recovered) or all of them (tests)."""
    with _lock:
        if role is None:
            _registry.clear()
        else:
            _registry.pop(role, None)


def save(path: Path, items: dict[str, Degradation]) -> None:
    """Write a run's degradations next to its session (read back by the report)."""
    try:
        if items:
            payload = {role: item.model_dump() for role, item in items.items()}
            path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not save degraded-role notes to %s: %s", path, exc)


def load(path: Path) -> dict[str, Degradation]:
    """Read a run's degradations ({} when none were recorded or the file is unreadable)."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Degradation] = {}
    for role, item in raw.items():
        try:
            out[str(role)] = Degradation.model_validate(item)
        except ValueError:
            continue
    return out
