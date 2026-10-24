"""Co-cited-only clearance makes a citation tangential, not partial (V5.7 #13).

The element adjudicator may clear an element as "cocited" (a co-cited reference's
abstract states it). When EVERY element it cleared was cleared only that way, none was
stated by this source (no stated / wording / framing clearance with a validated quote
of it) and the only survivors are the author's framing or a broadened scope, THIS
reference states nothing of what it is cited for: the citation belongs to the other
reference(s). Gold case: an oxygen-generating hydrogel attributed to a paper on
VEGF-driven vascularisation that mentions oxygen generation only in a list of others'
work; the shown partial (scope) hid a misplaced citation. The result is not_supported
(tangential_source, major) with a citation-placement note and a review flag. Off with
REFCHECK_V57_DISABLE=13.
"""

from refcheck.models.partial_types import LEGACY_FOR_TYPE, default_severity
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.layers import LayerResult

TANGENTIAL = "tangential_source"
_FRAMING_SURVIVORS = frozenset({"framing", "broadened"})


def cocited_only(adj: Adjudication) -> bool:
    """Every cleared element is "cocited", none this source's, survivors framing only."""
    cleared, surviving = adj.cleared, adj.surviving
    return v57.enabled(13) and adj.ok and bool(cleared) and bool(surviving) \
        and all(d.category == "cocited" for d in cleared) \
        and all(d.category in _FRAMING_SURVIVORS for d in surviving)


def tangential_note(adj: Adjudication) -> str:
    shown = "; ".join(f"'{d.element}'" for d in adj.cleared)
    return ("Element check: this reference states none of the elements checked; "
            f"{shown} is stated only by another reference cited in the same sentence, so "
            "this citation looks misplaced (tangential source): cite that reference for "
            "the point, or check whether this one belongs here.")


def tangential_layer(adj: Adjudication, label: LayerResult) -> LayerResult:
    """The adjudicate layer as a not_supported / tangential_source JudgeOutput."""
    base = label.output
    output = JudgeOutput.model_validate({
        "verdict": "not_supported", "confidence": base.confidence if base else 0.5,
        "quotes": [], "severity": default_severity(TANGENTIAL) or "major",
        "problem_type": LEGACY_FOR_TYPE.get(TANGENTIAL, "not_in_source"),
        "explanation": f"{tangential_note(adj)} {adj.explanation}".strip(),
        "missing": None, "partial_type": TANGENTIAL,
        "unsupported_elements": [d.element for d in adj.decisions][:5]})
    return adj.meta.model_copy(update={"output": output, "validated_quotes": []})
