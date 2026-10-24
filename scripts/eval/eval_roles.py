"""Role set-up for run_eval.py: CLI overrides -> the app's env switches, then a preflight.

The element adjudicator (role "adjudicator", REFCHECK_ADJUDICATE) is optional
in the app (a failed call leaves the verdict unchanged), so a dead adjudicator
only logs a warning, like a dead screen. V5.8: in cascade mode only HARD_ROLES
(the verifier) abort; a confirm without OpenAI runs on the same-family fallback
(llm/candidates.py) and is logged as degraded.
"""

import logging
import os

from eval_models import EvalConfig
from eval_runner import wants_screen

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.health import PreflightError, failed_roles, preflight
from refcheck.llm.roles import resolve_role
from refcheck.llm.types import HARD_ROLES, Role
from refcheck.stages.verify_claims.adjudicate import adjudicate_enabled
from refcheck.stages.verify_claims.calibration import ScreenThresholds

logger = logging.getLogger("run_eval")
MODE_ROLES: dict[str, list[Role]] = {
    "screen": [], "verifier": ["verifier"], "judge": ["judge"], "confirm": ["confirm"],
    "cascade": ["verifier", "judge", "confirm"],
}
RoleSetup = tuple[ScreenThresholds, dict[str, str | None], dict[str, str | None]]


def apply_overrides(cfg: EvalConfig) -> None:
    """Per-role model / effort overrides and the adjudicator / union-check switches go
    through the app's own env switches (REFCHECK_<ROLE>_MODEL / _EFFORT,
    REFCHECK_ADJUDICATE, REFCHECK_COCITED_UNION, REFCHECK_STRICT_CLEARANCE)."""
    for role, model in cfg.models.items():
        os.environ[f"REFCHECK_{role.upper()}_MODEL"] = model
    for role, effort in cfg.efforts.items():
        os.environ[f"REFCHECK_{role.upper()}_EFFORT"] = effort
    if cfg.adjudicate is not None:
        os.environ["REFCHECK_ADJUDICATE"] = cfg.adjudicate
    if cfg.cocited_union is not None:
        os.environ["REFCHECK_COCITED_UNION"] = cfg.cocited_union
    if cfg.strict_clearance is not None:
        os.environ["REFCHECK_STRICT_CLEARANCE"] = cfg.strict_clearance


def run_roles(cfg: EvalConfig, screen_on: bool) -> list[Role]:
    """Roles this run calls (adjudicator only in cascade mode, when switched on)."""
    roles = list(MODE_ROLES[cfg.mode])
    if cfg.mode == "cascade" and adjudicate_enabled():
        roles.append("adjudicator")
    if screen_on:
        roles.append("screen")
    return roles


async def check_roles(cfg: EvalConfig, thresholds: ScreenThresholds,
                      tracker: CostTracker) -> RoleSetup:
    """Preflight the roles this mode needs; a dead screen disables it (as in stage 5)."""
    roles = run_roles(cfg, wants_screen(cfg) and thresholds.enabled)
    statuses = await preflight(roles, cost_tracker=tracker) if roles else {}
    failed = failed_roles(statuses)
    # V5.8 G1: as in stage 5, only HARD_ROLES (the verifier) abort a cascade run; a
    # single-role mode still needs the role it measures.
    hard = [r for r in failed if r in HARD_ROLES or r == cfg.mode]
    if hard:
        details = "; ".join(f"{r}: {statuses[r].reason}" for r in hard)
        raise PreflightError(f"no working model for role(s) {', '.join(hard)} — {details}")
    if "adjudicator" in failed:
        logger.warning("No working adjudicator model (%s): partial verdicts stay unchanged",
                       statuses["adjudicator"].reason)
    for line in tracker.summary().degraded.values():
        logger.warning("Degraded role: %s", line)
    if "screen" in failed:
        logger.warning("Screen disabled for this run: %s", statuses["screen"].reason)
        thresholds = thresholds.model_copy(update={"enabled": False})
    return (thresholds, {r: s.model_id for r, s in statuses.items()},
            {r: s.reasoning_effort for r, s in statuses.items()})


def offline_roles(cfg: EvalConfig, thresholds: ScreenThresholds) -> RoleSetup:
    """check_roles stand-in for --offline: no preflight call; each role resolves to the
    model a live run would use (inside eval_cache.offline_scope every provider is keyed)."""
    roles = run_roles(cfg, wants_screen(cfg) and thresholds.enabled)
    specs = {role: resolve_role(role) for role in roles}
    return (thresholds, {r: s.id if s else None for r, s in specs.items()},
            {r: s.reasoning_effort if s else None for r, s in specs.items()})
