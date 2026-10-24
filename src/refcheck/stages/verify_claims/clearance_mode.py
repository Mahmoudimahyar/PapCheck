"""V5.6 strict clearance switch: REFCHECK_STRICT_CLEARANCE=on|off (default off).

off (default) = the V5.5 verifier behaviour, byte-identical requests so the LLM
cache reuses the V5.5 verifier / re-check / confirm / judge answers:
  * prompts verify_claim.md / judge_claim.md / verify_taxonomy.md (V5.5 rubric:
    guards are named in benign_notes, no quote needed);
  * the V5.5 output schema (models/verification_v55.py: no quote ``states``, no
    ``dismissed``); answers are converted to ``JudgeOutput`` with those at defaults;
  * guards come from benign_notes, except that a cocited_share note is dropped when
    no co-cited reference with an abstract was shown (``checked_notes``);
  * no states-based context-only quotes.
on = the V5.6 strict clearance measured on the 281-pair gold set (over-harsh 66/198
gold-supported vs 37 in V5.5, 3-way 72.2% vs 80.4%): *_strict.md prompts ("no quote,
no clearance", quote "states"), the full schema, and the dismissal audit
(dismissals.py). Both modes keep the front-matter quote exclusion, quote de-dup and
every deterministic rule (number, lineage, wrong PDF, credit panels, secondary note)
plus the adjudicator / union rules. Strict answers are NOT in the LLM cache (the gold
measurement used a throw-away cache): a strict run pays in full unless an earlier
strict run used --reuse-cache.
"""

import logging
import os

from pydantic import BaseModel

from refcheck.models import verification_v55
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims.verifier_helpers import PairContext

ENV = "REFCHECK_STRICT_CLEARANCE"
_ON = frozenset({"1", "true", "yes", "on"})
_OFF = frozenset({"0", "false", "no", "off", ""})
STRICT_SUFFIX = "_strict"
# Fields the V5.5 schema does not have (dropped from any off-mode output).
_V56_FIELDS: dict[str, object] = {"dismissed": True, "quotes": {"__all__": {"states"}}}

logger = logging.getLogger(__name__)


def strict_clearance() -> bool:
    """REFCHECK_STRICT_CLEARANCE (default off); read at call time."""
    value = os.getenv(ENV, "off").strip().lower()
    if value not in _ON and value not in _OFF:
        logger.warning("Unknown %s=%r; using 'off'", ENV, value)
    return value in _ON


def template_for(template: str, strict: bool) -> str:
    """The prompt a layer renders: "verify_claim" / "judge_claim", or their *_strict."""
    base = template.removesuffix(STRICT_SUFFIX)
    return base + STRICT_SUFFIX if strict else base


def request_model(strict: bool) -> type[BaseModel]:
    """Output model sent as the schema (its name and schema enter the cache key)."""
    return JudgeOutput if strict else verification_v55.JudgeOutput


def layer_output(parsed: BaseModel, strict: bool) -> JudgeOutput:
    """The parsed answer as a JudgeOutput; off mode drops ``states`` / ``dismissed``
    (so a quote counts as stating and guards come from benign_notes, as in V5.5)."""
    if strict and isinstance(parsed, JudgeOutput):
        return parsed
    data = parsed.model_dump(exclude=None if strict else _V56_FIELDS)  # type: ignore[arg-type]
    return JudgeOutput.model_validate(data)


def checked_notes(out: JudgeOutput, ctx: PairContext) -> JudgeOutput:
    """V5.5: ``out`` without a cocited_share note when no co-cited abstract was shown
    (the model cannot know what another reference states from its title alone)."""
    if "cocited_share" not in out.benign_notes or any(r.abstract for r in ctx.co_cited):
        return out
    kept = [note for note in out.benign_notes if note != "cocited_share"]
    return out.model_copy(update={"benign_notes": kept})
