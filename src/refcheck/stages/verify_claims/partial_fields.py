"""Partial sub-type fields of a VerificationResult (taxonomy v1.1, models/partial_types.py).

* partial_type: the genuine type for partial / negative verdicts (exactly one),
  "coverage_limited" only for a PARTIAL verdict on an abstract-only source whose
  element is merely absent from the abstract (not contradicted, not stated
  differently); a negative verdict or a full text never gets it (the verdict's
  default type instead); None for supported / cannot_verify;
* partial_severity: the layer's minor/major, else (or when the type was remapped)
  the type's default;
* author_action: the type's action naming the first unsupported element; a
  supported result cleared by a co-cited reference gets the citation-placement note;
* unsupported_elements: the layer's elements; on a supported result only those no
  validated dismissal clears (V5.6, dismissals.py; a "supported" that still lists them
  is an unusual positive, cascade.verifier_final, and the reviewer sees them);
* guards_applied (+ one note each) only where a guard really cleared something: a
  supported result gets the layer's benign notes + pipeline guards (evidence_recheck);
  a partial gets only the evidence re-check, and only when its (positive) re-run no
  longer reports an element that is not listed now either (note "cleared part of the
  concern"; a still-negative re-run clears nothing, recheck.py; a benign note names no
  element, so it stays in the layer trace); a negative verdict gets none.

The classification comes from the layer whose verdict is shown: the label
layer when its verdict is the shown one (e.g. the cross-check's), else the
verifier that routed the pair (a softened dispute keeps the verifier's type), then the
deterministic corrections of subtype_rules.corrected_type (V5.8).
"""

from pydantic import BaseModel, Field

from refcheck.models.partial_types import (
    GUARD_LABELS,
    GUARD_ORDER,
    LEGACY_PROBLEM_MAP,
    author_action,
    default_severity,
    guards_from_notes,
    is_genuine,
)
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.lineage import lineage_action
from refcheck.stages.verify_claims.recheck import is_listed
from refcheck.stages.verify_claims.source_numbers import figures_only_absent
from refcheck.stages.verify_claims.subtype_rules import corrected_type

# Fallback type when a layer gave neither a partial_type nor a mappable problem_type.
DEFAULT_TYPE: dict[str, str] = {
    "partially_supported": "missing_element",
    "not_supported": "tangential_source",
    "contradicted": "specific_detail_mismatch",
    "not_relevant": "tangential_source",
}
# Types that mean "absent from the abstract" when no full text was available. A
# specific_detail_mismatch qualifies only when the abstract lacks the claim's figures
# without stating a different one of the same kind (figures_only_absent).
_ABSENCE_TYPES = frozenset({"missing_element", "coverage_limited"})


class PartialFields(BaseModel):
    """The new VerificationResult fields + human-readable guard notes."""

    partial_type: str | None = None
    partial_severity: str | None = None
    author_action: str = ""
    unsupported_elements: list[str] = Field(default_factory=list)
    guards_applied: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def result_update(self) -> dict[str, object]:
        return self.model_dump(exclude={"notes"})


def type_layer(verdict: str, label: LayerResult | None,
               layers: list[LayerResult]) -> LayerResult | None:
    """The layer whose classification goes with the shown verdict (module doc)."""
    if label is not None and label.output is not None and label.verdict == verdict:
        return label
    routed = [lay for lay in layers if lay.role == "verifier" and lay.axis is not None]
    last = routed[-1] if routed else None
    if (last is not None and last.verdict == "supported" and verdict != "supported"
            and label is not None and label.output is not None):
        return label  # softened unusual-positive dispute: the cross-check found the problem
    return last or label


def genuine_type(out: JudgeOutput | None, verdict: str) -> str:
    """The layer's partial_type, else its legacy problem_type mapped, else a default."""
    if out is not None and is_genuine(out.partial_type):
        return out.partial_type
    legacy = LEGACY_PROBLEM_MAP.get(out.problem_type if out is not None else "", "")
    return legacy or DEFAULT_TYPE.get(verdict, "missing_element")


def coverage_type(partial_type: str, verdict: str, coverage: str, contradicted: bool,
                  figures_absent: bool = False) -> str:
    """coverage_limited only for a partial verdict's abstract-only absences (module doc)."""
    absence = verdict == "partially_supported" and coverage != "full_text" and not contradicted
    if not absence:
        if partial_type != "coverage_limited":
            return partial_type
        if verdict == "partially_supported" and contradicted:
            return "specific_detail_mismatch"
        return DEFAULT_TYPE.get(verdict, "missing_element")
    if partial_type in _ABSENCE_TYPES:
        return "coverage_limited"
    if partial_type == "specific_detail_mismatch" and figures_absent:
        return "coverage_limited"
    return partial_type


def guard_notes(guards: list[str]) -> list[str]:
    """One short note per guard ("Co-cited reference: ...")."""
    return [f"{GUARD_LABELS[g][0]}: {GUARD_LABELS[g][1]}" for g in guards if g in GUARD_LABELS]


def uncovered_elements(out: JudgeOutput | None) -> list[str]:
    """Elements a layer lists that no validated dismissal clears (V5.6).

    A layer's ``dismissed`` holds only audited clearances (dismissals.py); an output
    built in code without dismissals (the element adjudicator) clears all its listed
    elements with its benign notes, as before.
    """
    if out is None:
        return []
    if out.dismissed:
        cleared = [d.element for d in out.dismissed]
        return [e for e in out.unsupported_elements if not is_listed(e, cleared)]
    if guards_from_notes(list(out.benign_notes)):
        return []
    return list(out.unsupported_elements)


def partial_clearing(verdict: str, pipeline_guards: list[str], recheck_cleared: list[str],
                     elements: list[str]) -> list[str]:
    """Re-check finds that cleared part of a partial's concern (no longer listed)."""
    if verdict != "partially_supported" or "evidence_recheck" not in pipeline_guards:
        return []
    return [e for e in recheck_cleared if not is_listed(e, elements)]


def cleared_part_note(found: list[str]) -> str:
    """The partial's evidence re-check note: what is no longer reported, not a full clearance."""
    shown = "; ".join(f"'{e}'" for e in found)
    return (f"{GUARD_LABELS['evidence_recheck'][0]}: cleared part of the concern; {shown} "
            "no longer reported after a targeted search of the full text. The elements "
            "still listed remain unsupported.")


def _supported(out: JudgeOutput | None, pipeline_guards: list[str]) -> PartialFields:
    """No type; the guards that cleared it, maybe a placement note, uncovered elements."""
    found = set(guards_from_notes(list(out.benign_notes) if out else []))
    found.update(pipeline_guards)
    guards = [g for g in GUARD_ORDER if g in found]
    action = GUARD_LABELS["cocited_share"][1] if "cocited_share" in guards else ""
    return PartialFields(author_action=action, unsupported_elements=uncovered_elements(out),
                         guards_applied=guards, notes=guard_notes(guards))


def _severity(out: JudgeOutput | None, ptype: str, genuine: str) -> str | None:
    """The layer's minor/major for its own type; the type's default otherwise."""
    if out is not None and out.severity in ("minor", "major") and ptype == genuine \
            and ptype != "coverage_limited":
        return out.severity
    return default_severity(ptype)


def partial_fields(verdict: str, label: LayerResult | None, layers: list[LayerResult],
                   coverage: str, pipeline_guards: list[str], claim_part: str = "",
                   source_text: str = "",
                   recheck_cleared: list[str] | None = None) -> PartialFields:
    """PartialFields for a routed (supported / partial / negative) result.

    ``claim_part`` / ``source_text`` (the cited part, the available source text) decide
    whether an abstract-only specific_detail_mismatch is a mere absence;
    ``recheck_cleared``: the first-run elements a positive re-check run no longer reports.
    """
    layer = type_layer(verdict, label, layers)
    out = layer.output if layer is not None else None
    if verdict == "supported":
        return _supported(out, pipeline_guards)
    if verdict not in DEFAULT_TYPE:  # undecided (insufficient evidence / error)
        return PartialFields()
    contradicted = layer is not None and bool(layer.quotes("contradicts"))
    own = genuine_type(out, verdict)
    genuine = corrected_type(own, verdict, layer, layers)
    absent = coverage != "full_text" and genuine == "specific_detail_mismatch" \
        and figures_only_absent(claim_part, source_text)
    ptype = coverage_type(genuine, verdict, coverage, contradicted, absent)
    elements = list(out.unsupported_elements) if out else []
    found = partial_clearing(verdict, pipeline_guards, recheck_cleared or [], elements)
    return PartialFields(
        partial_type=ptype, partial_severity=_severity(out, ptype, own),
        author_action=lineage_action(elements[0] if elements else None)
        or author_action(ptype, elements[0] if elements else None),
        unsupported_elements=elements, guards_applied=["evidence_recheck"] if found else [],
        notes=[cleared_part_note(found)] if found else [])
