"""Deterministic rules on a routed outcome, after the element adjudicator (V5.6).

Post-routing checks normally add notes and review flags only (post_checks.py). The
three rules here are the explicit exceptions that CHANGE a verdict, because the manual
review of 191 "supported" verdicts found a deterministic signal that was reported
or available but ignored:

* figure (number_rule.py, L3): a figure of the cited span the source states nowhere
  but states differently by more than a factor 2 -> a "supported" verdict becomes
  partially_supported (specific_detail_mismatch; minor for a true bound, else major).
  Full-text sources only: "stated nowhere" in an abstract only means "not in the
  abstract";
* lineage (lineage.py, L4): the sentence opens with a lineage connective ("Building
  on these results") but this reference is older than the work cited in the previous
  sentence -> a "supported" verdict becomes partially_supported (specific_detail_
  mismatch, minor); a partial one gets the lineage element added;
* colour key (figure_key.py, V5.8 G2): the cited legend / sentence gives a marker a
  colour the source figure's own key contradicts ("MK1 (green), MK2 (red)" where the
  key shows them swapped) -> partially_supported (specific_detail_mismatch, major); a partial one
  gets the "colour key: ..." element added (first). A weaker reading (not
  ``decisive``: one marker, another figure's key) only adds a note and a review flag.

Each adds its element ("number: ...", "lineage: ...", "colour key: ...": never cleared
by a model, the rules run after it; adjudicate_rules.LOCKED_PREFIXES) as a deterministic
layer RULE_LAYER (role "adjudicator": not another opinion in the agreement ratio) that
becomes the label layer, plus a note and a review flag. Negative / undecided verdicts
are left alone. A "supported" verdict the rules turn into a partial loses the notes that
announced it as supported (the element check's "... so the verdict is supported instead
of partially supported") and its consensus becomes RULE_CONSENSUS (a "disputed" /
"verifier_unconfirmed" one is kept for the review UI), so a partial never shows as
screen-cleared or adjudicated-supported. Last, a figure-credit line verified on
provenance only (credit.provenance_only) that is shown as supported gets CREDIT_NOTE and
a review flag (L1).
"""

from typing import TYPE_CHECKING

from refcheck.models.partial_types import LEGACY_FOR_TYPE
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims.credit import provenance_only
from refcheck.stages.verify_claims.figure_key import colour_finding
from refcheck.stages.verify_claims.layers import LayerResult, cited_for
from refcheck.stages.verify_claims.lineage import lineage_conflict
from refcheck.stages.verify_claims.number_rule import figure_conflict
from refcheck.stages.verify_claims.partial_fields import type_layer
from refcheck.stages.verify_claims.post_checks import searchable_text
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

RULE_LAYER = "post_rules"
RULE_TYPE = "specific_detail_mismatch"
RULE_CONSENSUS = "rule"
CREDIT_NOTE = "Figure credit: provenance verified; the panel content was not checked."
_MAX_ELEMENTS = 5  # JudgeOutput keeps at most five
_KEEP_CONSENSUS = frozenset({"disputed", "verifier_unconfirmed"})  # adjudicate_result
_SUPPORTED_NOTE = "instead of partially supported"  # the element checks' "now supported" notes


def _quotes(label: LayerResult) -> list[dict[str, str]]:
    return [{"passage_id": q.passage_id, "text": q.text, "role": q.role}
            for q in label.validated_quotes]


def rule_layer(out: "CascadeOutcome", elements: list[str], severity: str, explanation: str,
               partial_type: str = RULE_TYPE, name: str = RULE_LAYER) -> LayerResult | None:
    """The deterministic layer: a partial with ``elements`` (a major rule's put before a
    partial's own, so the author action and first element follow it; a minor one after);
    ``partial_type`` / ``name`` for a new partial (the V5.7 slot probe's own layer)."""
    label = out.label_layer
    if label is None or label.output is None:
        return None
    base = type_layer(out.verdict, label, out.layers) if out.verdict != "supported" else None
    base_out = base.output if base is not None and base.output is not None else None
    if base_out is not None:  # already partial: keep its type, add the elements
        kept = base_out.unsupported_elements[:_MAX_ELEMENTS - len(elements)]
        ordered = [*elements, *kept] if severity == "major" else [*kept, *elements]
        update = {"verdict": "partially_supported", "unsupported_elements": ordered,
                  "explanation": f"{explanation} {base_out.explanation}".strip(),
                  "severity": "major" if severity == "major" else base_out.severity}
        output = base_out.model_copy(update=update)
    else:
        output = JudgeOutput.model_validate({
            "verdict": "partially_supported", "confidence": label.output.confidence,
            "quotes": _quotes(label), "severity": severity,
            "problem_type": LEGACY_FOR_TYPE[partial_type], "missing": None,
            "explanation": f"{explanation} First check: {label.output.explanation}".strip(),
            "partial_type": partial_type, "unsupported_elements": elements})
    return LayerResult(layer=name, role="adjudicator", output=output,
                       validated_quotes=list(label.validated_quotes),
                       model_display="deterministic rule", pack_kind=label.pack_kind,
                       pack_summary=label.pack_summary)


def _findings(ctx: PairContext, out: "CascadeOutcome",
              review: list[str]) -> tuple[list[str], list[str], str]:
    """(elements, notes, severity) of the rules that apply to this outcome; a colour-key
    finding that is not decisive only adds its note to ``review``."""
    elements: list[str] = []
    notes: list[str] = []
    severity = "minor"
    lineage = lineage_conflict(ctx.claim.manuscript_text, ctx.prev_sentence, ctx.ref.year)
    if lineage is not None:
        elements.append(lineage.element)
        notes.append(lineage.note)
    part = cited_for(ctx.claim, ctx.claim_text)
    if out.verdict == "supported" and ctx.coverage == "full_text" \
            and (part or ctx.claim.co_cited_count <= 1):
        figure = figure_conflict(part or ctx.claim_text, searchable_text(ctx.doc))
        if figure is not None:
            elements.insert(0, figure.element)
            notes.insert(0, figure.note)
            severity = figure.severity
    colour = colour_finding(ctx)  # V5.8 G2: a legend colour key the source figure contradicts
    if colour is not None and not colour.decisive:
        review.append(colour.note)
    elif colour is not None:
        elements.insert(0, colour.element)
        notes.insert(0, colour.note)
        severity = "major"
    return elements, notes, severity


def demoted(out: "CascadeOutcome", consensus: str = RULE_CONSENSUS) -> tuple[list[str], str]:
    """(notes, consensus_type) of an outcome a rule (or the V5.7 slot probe, consensus
    "adjudicated") turns into a partial (module doc)."""
    if out.verdict != "supported":
        return out.notes, out.consensus_type
    notes = [n for n in out.notes if not (n.startswith("Element check:") and _SUPPORTED_NOTE in n)]
    keep = out.consensus_type in _KEEP_CONSENSUS
    return notes, out.consensus_type if keep else consensus


def apply_outcome_rules(ctx: PairContext, out: "CascadeOutcome") -> "CascadeOutcome":
    """The outcome after the deterministic rules (module doc)."""
    if out.verdict in ("supported", "partially_supported") and RULE_LAYER not in out.layer_path:
        review: list[str] = []
        elements, notes, severity = _findings(ctx, out, review)
        layer = rule_layer(out, elements, severity, " ".join(notes)) if elements else None
        if layer is not None:
            kept, consensus = demoted(out)
            out = out.model_copy(update={
                "verdict": "partially_supported", "label_layer": layer,
                "layers": [*out.layers, layer], "layer_path": [*out.layer_path, RULE_LAYER],
                "notes": [*kept, *notes, *review], "consensus_type": consensus,
                "needs_review": True})
        elif review:  # a weak colour-key reading: a note and a review flag, no verdict change
            out = out.model_copy(update={"notes": [*out.notes, *review], "needs_review": True})
    if out.verdict == "supported" and provenance_only(ctx) and CREDIT_NOTE not in out.notes:
        out = out.model_copy(update={"notes": [*out.notes, CREDIT_NOTE], "needs_review": True})
    return out
