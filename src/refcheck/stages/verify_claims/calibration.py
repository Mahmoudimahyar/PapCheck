"""Screen (L1) thresholds: calibrated file, env overrides, safe defaults.

WP-F's calibration script writes ``~/.refcheck/calibration/screen.json``::

    {"t_accept": 0.985, "injection_max": 0.2, "enabled": true, "auto_clear": true,
     "policy": {"t_contra": 0.5, "t_topic": 0.5}, ...}

``auto_clear: false`` (a failed calibration) keeps the screen pre-pass and its
conflict check but never lets it finalize a pair; ``enabled: false`` turns the
screen off entirely. Unknown keys are ignored. Env overrides: ``REFCHECK_SCREEN_T_ACCEPT``,
``REFCHECK_SCREEN_ENABLED`` and ``REFCHECK_SCREEN_CALIBRATION`` (file path).
"""

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from refcheck.llm.roles import screen_enabled

logger = logging.getLogger(__name__)

DEFAULT_T_ACCEPT = 0.97
DEFAULT_INJECTION_MAX = 0.2
DEFAULT_T_CONTRA = 0.5
DEFAULT_T_TOPIC = 0.5
_DEFAULT_PATH = Path.home() / ".refcheck" / "calibration" / "screen.json"


class ScreenThresholds(BaseModel):
    """Routing thresholds for the Decisions-API screen."""

    t_accept: float = Field(default=DEFAULT_T_ACCEPT, ge=0.0, le=1.0)
    injection_max: float = Field(default=DEFAULT_INJECTION_MAX, ge=0.0, le=1.0)
    enabled: bool = True
    auto_clear: bool = True  # False: screen runs (ranking, conflicts) but never clears
    source: str = "default"  # "default" | file path | "env"
    # Extra cut-offs from calibration: t_contra (finding_conflicts must stay
    # below), t_topic (topic_match must reach) — used for "screen conflicts".
    policy: dict[str, float] = Field(default_factory=dict)

    @property
    def t_contra(self) -> float:
        return float(self.policy.get("t_contra", DEFAULT_T_CONTRA))

    @property
    def t_topic(self) -> float:
        return float(self.policy.get("t_topic", DEFAULT_T_TOPIC))


def calibration_path() -> Path:
    """Where calibrated thresholds are read from."""
    override = os.environ.get("REFCHECK_SCREEN_CALIBRATION", "").strip()
    return Path(override) if override else _DEFAULT_PATH


def _from_file(path: Path) -> ScreenThresholds | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable screen calibration %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        logger.warning("Ignoring screen calibration %s: not a JSON object", path)
        return None
    policy_raw = raw.get("policy")
    policy = {str(k): float(v) for k, v in policy_raw.items()
              if isinstance(v, int | float) and not isinstance(v, bool)} \
        if isinstance(policy_raw, dict) else {}
    fields: dict[str, object] = {"source": str(path), "policy": policy}
    for key in ("t_accept", "injection_max", "enabled", "auto_clear"):
        if key in raw:
            fields[key] = raw[key]
    try:
        return ScreenThresholds.model_validate(fields)
    except ValidationError as exc:
        logger.warning("Ignoring invalid screen calibration %s: %s", path, exc)
        return None


def _env_t_accept() -> float | None:
    raw = os.environ.get("REFCHECK_SCREEN_T_ACCEPT", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring REFCHECK_SCREEN_T_ACCEPT=%r (not a number)", raw)
        return None
    if not 0.0 <= value <= 1.0:
        logger.warning("Ignoring REFCHECK_SCREEN_T_ACCEPT=%r (outside 0..1)", raw)
        return None
    return value


def load_thresholds() -> ScreenThresholds:
    """Calibrated thresholds (if any) with env overrides applied."""
    thresholds = _from_file(calibration_path()) or ScreenThresholds()
    t_accept = _env_t_accept()
    if t_accept is not None:
        thresholds = thresholds.model_copy(update={"t_accept": t_accept, "source": "env"})
    if not screen_enabled():
        # REFCHECK_SCREEN_ENABLED=false or the anthropic_only privacy profile.
        thresholds = thresholds.model_copy(update={"enabled": False})
    return thresholds
