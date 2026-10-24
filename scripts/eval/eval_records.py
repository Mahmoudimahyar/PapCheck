"""Per-item record helpers for eval_runner.py (layer / screen records, classifications)."""

from eval_clearance import POLICY_GATES
from eval_models import EvalItem, ItemRecord, LayerRecord, Mode, ScreenRecord

from refcheck.stages.verify_claims.adjudicate_apply import AdjudicationSummary
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.screen import ScreenResult


def item_record(item: EvalItem, mode: Mode, **fields: object) -> ItemRecord:
    """A record carrying every gold / scoring-group field of ``item`` (plus ``fields``)."""
    return ItemRecord.model_validate({
        "id": item.id, "dataset": item.dataset, "synthetic": item.synthetic,
        "gold_label": item.gold_label, "gold_binary": item.gold_binary,
        "fine_label": item.fine_label, "mode": mode,
        "gold_partial_type": item.gold_partial_type,
        "gold_secondary_types": list(item.gold_secondary_types),
        "tool_misread_type": item.tool_misread_type, "gold_confidence": item.gold_confidence,
        "split": item.split, "gold_source": item.gold_source,
        "eval_flags": list(item.eval_flags), "subset_role": item.subset_role, **fields})


def screen_record(screen: ScreenResult) -> ScreenRecord:
    return ScreenRecord(probs=screen.probs, refused=screen.refused, s=screen.s,
                        model=screen.model, latency_ms=screen.latency_ms,
                        cost_usd=screen.cost_usd, input_tokens=screen.input_tokens,
                        error=screen.error)


def partial_type_of(layer: LayerResult | None) -> str:
    """The layer's partial sub-type ("" until the layer output has that field)."""
    out = layer.output if layer is not None else None
    return str(getattr(out, "partial_type", "") or "")


def classification(layer: LayerResult | None) -> dict[str, str]:
    """severity / problem_type / partial_type of the layer whose verdict is shown."""
    out = layer.output if layer is not None else None
    return {"severity": out.severity if out else "", "problem_type": out.problem_type
            if out else "", "partial_type": partial_type_of(layer)}


def partial_update(partial_type: str | None, severity: str | None, guards: list[str],
                   elements: list[str]) -> dict[str, object]:
    """The product's partial fields for an ItemRecord."""
    return {"partial_type": partial_type or "", "partial_severity": severity or "",
            "guards_applied": list(guards), "unsupported_elements": list(elements)}


def adjudication_update(summary: AdjudicationSummary | None) -> dict[str, object]:
    """What the element adjudicator and the co-cited union check after it did ("" / {}
    when they did not run)."""
    if summary is None:
        return {"adjudication": "", "adjudicated_elements": {}, "cocited_union": ""}
    return {"adjudication": summary.outcome, "adjudicated_elements": dict(summary.categories),
            "cocited_union": summary.union.outcome if summary.union is not None else ""}


def screen_update(screen: ScreenResult, eligible: bool, failed: list[str]) -> dict[str, object]:
    """Record fields after the screen (gate failures without the policy gates)."""
    return {"screen": screen_record(screen), "clear_eligible": eligible,
            "gate_failures": [g for g in failed if g not in POLICY_GATES],
            "layer_path": ["screen"] if screen.ok else [],
            "cost_usd": screen.cost_usd, "latency_ms": screen.latency_ms}


def layer_record(layer: LayerResult) -> LayerRecord:
    out = layer.output
    return LayerRecord(
        layer=layer.layer, role=layer.role, model_id=layer.model_id,
        verdict=out.verdict if out else None, severity=out.severity if out else None,
        problem_type=out.problem_type if out else None,
        partial_type=partial_type_of(layer) or None,
        confidence=out.confidence if out else None,
        quote_roles=[q.role for q in layer.validated_quotes],
        invalid_quotes=len(layer.invalid_quotes), latency_ms=layer.latency_ms,
        cost_usd=layer.cost_usd, input_tokens=layer.input_tokens,
        output_tokens=layer.output_tokens, error=layer.error, error_kind=layer.error_kind,
        pack_kind=layer.pack_kind, cached=out is not None and layer.latency_ms == 0,
    )
