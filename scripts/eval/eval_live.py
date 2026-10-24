"""--live-roles for an --offline run (eval_cache): chat calls of the listed roles may be
sent, everything else (other roles, embeddings, the screen) stays cache-only.

A live role resolves to the model a normal run would use (offline every provider counts as
keyed, so the role's first candidate wins) and only its calls to that very model are
sent: a fallback to another model or provider stays cache-only. A sent call goes through the normal
client (completion.complete: retries, key ring, cost tracking) and structured.call_spec
writes its answer to the cache; the cache key (model, effort, prompts, schema) never
depends on which env var held the key, so the entry is the one a normal run reads.
Keys: everything is blanked except --live-keys (default: every key env var of the live
roles' providers), which must belong to those providers. --max-cost is a hard cap enforced
here on each call's estimated cost before it is sent (in-flight calls reserved; spend is
the larger of the run's CostTracker and LiveCalls' own tally of answered calls); the run's
CostTracker is left uncapped so a budget error never turns a pair into an unscored one.
A live call that is not answered (over the cap, failed, or in a pair that already missed a
cache-only call and is scored from --fallback-from anyway) is recorded as a live miss
("live-chat:<role>"), so its pair is scored from --fallback-from. Preflight: one tiny probe
per live model. --live-check sends nothing: keys stay blank and every live call is
recorded as a live miss, a free dry run listing the pairs that would call.
"""

import logging
import math
import os
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from eval_cache import (
    EST_OUTPUT_TOKENS,
    ChatStandIn,
    cache_only_complete,
    chat_chars,
    estimate,
    pair_missed,
    record_miss,
)
from eval_models import EvalConfig
from pydantic import BaseModel, Field

from refcheck.llm import completion, keys
from refcheck.llm.completion import CompletionOutcome
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.errors import LLMCallError, LLMError, short_error
from refcheck.llm.health import probe_model
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.roles import resolve_role
from refcheck.llm.usage import compute_cost

if TYPE_CHECKING:
    from refcheck.llm.types import Role

logger = logging.getLogger("run_eval")
_LIVE_CHARS_PER_TOKEN = 3  # conservative token estimate for the cost cap


class LivePlan(BaseModel):
    """The roles an --offline run may send, their resolved models and kept keys."""

    models: dict[str, str]  # role -> resolved model id
    providers: dict[str, str]  # role -> provider of that model
    keep: list[str] = Field(default_factory=list)  # key env vars kept (none: --live-check)
    check: bool = False
    max_cost: float = 0.0


def provider_env(provider: str) -> list[str]:
    return keys.PROVIDER_ENV_KEYS.get(provider, [f"{provider.upper()}_API_KEY"])


def live_plan(cfg: EvalConfig) -> LivePlan | None:
    """The --live-roles plan (None without it); SystemExit on an unusable set-up."""
    if not cfg.live_roles:
        return None
    if not cfg.offline:
        raise SystemExit("--live-roles needs --offline")
    with patch.object(keys, "has_key", lambda provider: True):  # as in offline_roles
        specs = {role: resolve_role(cast("Role", role)) for role in cfg.live_roles}
    dead = [role for role, spec in specs.items() if spec is None]
    if dead:
        raise SystemExit(f"--live-roles: no model for {', '.join(dead)}")
    resolved = {role: spec for role, spec in specs.items() if spec is not None}
    providers = {spec.provider for spec in resolved.values()}
    allowed = {name for p in providers for name in provider_env(p)}
    keep = [] if cfg.live_check else (cfg.live_keys or sorted(allowed))
    foreign = sorted(set(keep) - allowed)
    if foreign:
        raise SystemExit(f"--live-keys {foreign}: not a key of {sorted(providers)}")
    for provider in providers if not cfg.live_check else ():
        if not any(os.environ.get(n, "").strip() for n in keep if n in provider_env(provider)):
            raise SystemExit(f"--live-roles: no {provider} key set among {keep}")
    return LivePlan(models={r: s.id for r, s in resolved.items()},
                    providers={r: s.provider for r, s in resolved.items()},
                    keep=keep, check=cfg.live_check, max_cost=cfg.max_cost)


def tracker_cap(cfg: EvalConfig) -> float:
    """The run's CostTracker cap: uncapped with --live-roles (LiveCalls enforces it)."""
    return math.inf if cfg.live_roles else cfg.max_cost


class LiveCalls:
    """structured.complete stand-in: sends the plan's calls, cache-only for the rest."""

    def __init__(self, plan: LivePlan) -> None:
        self.plan = plan
        self.reserved = 0.0
        self.spent = 0.0  # own tally: holds the cap when a caller passes no tracker
        self.sent = 0

    def _fail(self, spec: ModelSpec, role: str, chars: int, why: str) -> LLMCallError:
        record_miss(estimate("chat", spec, role, chars, EST_OUTPUT_TOKENS, live=True))
        return LLMCallError(f"live {role} call not answered ({why})", "other", spec.id)

    async def complete(self, spec: ModelSpec, messages: object, *args: object,
                       **kwargs: object) -> CompletionOutcome:
        role = str(kwargs.get("role") or "")
        if (self.plan.providers.get(role) != spec.provider
                or self.plan.models.get(role) != spec.id):
            await cache_only_complete(spec, messages, *args, **kwargs)
        chars = chat_chars(messages)
        if self.plan.check:
            raise self._fail(spec, role, chars, "--live-check: not sent")
        if pair_missed():
            raise self._fail(spec, role, chars, "pair already needs a fallback: not sent")
        tracker = kwargs.get("cost_tracker")
        spent = max(tracker.total_cost if isinstance(tracker, CostTracker) else 0.0,
                    self.spent)
        est = estimate("chat", spec, role, chars * 4 // _LIVE_CHARS_PER_TOKEN,
                       2 * EST_OUTPUT_TOKENS).est_cost_usd
        if spent + self.reserved + est > self.plan.max_cost:
            logger.warning("--max-cost $%.2f reached ($%.4f spent): %s call not sent",
                           self.plan.max_cost, spent, role)
            raise self._fail(spec, role, chars, "--max-cost reached: not sent")
        self.reserved += est
        try:
            outcome = await completion.complete(spec, messages, *args, **kwargs)  # type: ignore[arg-type]
        except LLMCallError as exc:
            record_miss(estimate("chat", spec, role, chars, EST_OUTPUT_TOKENS, live=True))
            logger.warning("live %s call (%s) failed: %s", role, spec.id, short_error(exc))
            raise
        finally:
            self.reserved -= est
        self.spent += compute_cost(spec, outcome.usage)
        self.sent += 1
        logger.info("live %s call #%d sent (%s)", role, self.sent, spec.id)
        return outcome


def chat_stand_in(plan: LivePlan | None) -> ChatStandIn:
    """The offline chat stand-in: LiveCalls with --live-roles, else cache-only."""
    return LiveCalls(plan).complete if plan is not None else cache_only_complete


async def preflight_live(plan: LivePlan | None, tracker: CostTracker) -> None:
    """One tiny probe per live model (inside offline_scope); SystemExit when it fails.
    No probe for --live-check (nothing is sent)."""
    if plan is None or plan.check:
        return
    for role, model in plan.models.items():
        spec = resolve_role(cast("Role", role))
        if spec is None or spec.id != model:
            raise SystemExit(f"--live-roles: {role} no longer resolves to {model}")
        try:
            await probe_model(spec, cast("Role", role), tracker)
        except (LLMError, TimeoutError) as exc:
            raise SystemExit(f"--live-roles preflight: {role} ({model}) failed: "
                             f"{short_error(exc, 200)}") from exc
        logger.info("live %s: %s ok (keys kept: %s)", role, model, plan.keep)
