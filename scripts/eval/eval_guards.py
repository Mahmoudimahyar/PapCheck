"""Partial sub-type and guard metrics of the partial-verdict eval (V5.4, eval_partial.py).

- partial_type_accuracy_flagged / partial_type_flagged: sub-type accuracy on the gold
  partials the tool flagged (partial or negative);
- gold_supported_cleared / cleared_by_misread: gold supported pairs the tool shows
  supported, by any path, over ALL pairs (per tool_misread_type);
- over the pairs the misread's guard can act on (guard_can_run: the evidence re-check
  behind gold evidence_gap needs a full text, so abstract-only pairs are left out):
  misread_cleared_any = shown supported by any path, misread_guard_hit = shown
  supported WITH that guard in guards_applied (cleared by this guard);
- guards_fired / guards_by_gold: how often each guard fired, per gold 3-way class.
"""

from collections import Counter, defaultdict

from eval_models import ItemRecord
from eval_stats import safe_div

from refcheck.models.partial_types import GUARD_FOR_MISREAD

Scored = list[tuple[ItemRecord, str, str]]  # (record, gold 3-way, predicted 3-way)


# evidence_gap == coverage_limited: an evidence gap no full text can resolve is what the
# tool calls coverage_limited (and the reverse), so both name one type for type accuracy.
_SAME_TYPE = {"evidence_gap": "coverage_limited"}


def type_matches(gold: str, tool: str, secondary: list[str] | None = None) -> bool:
    """Same sub-type, with evidence_gap and coverage_limited counted as one type. V5.8 F15:
    an abstract-only partial is reported as coverage_limited by design (V5.4), so it also
    matches a gold missing_element whose secondary types include evidence_gap (the
    reviewer found the element missing in a full text the tool did not have)."""
    if tool == "coverage_limited" and gold == "missing_element" \
            and "evidence_gap" in (secondary or []):
        return True
    return _SAME_TYPE.get(gold, gold) == _SAME_TYPE.get(tool, tool)


def ratio(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)}"


def ratios(groups: dict[str, list[bool]]) -> dict[str, str]:
    return {k: ratio(v) for k, v in sorted(groups.items())}


def table(rows: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Counts per (row key, column key), both sorted."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for gold, pred in rows:
        counts[gold][pred] += 1
    return {g: dict(sorted(r.items())) for g, r in sorted(counts.items())}


def guard_can_run(rec: ItemRecord) -> bool:
    """The misread's guard can act on this pair (the evidence re-check needs a full text)."""
    return rec.tool_misread_type != "evidence_gap" or rec.coverage == "full_text"


def guard_metrics(scored: Scored) -> dict[str, object]:
    """PartialMetrics updates for sub-type accuracy, clearance and guards (module doc)."""
    flagged = [type_matches(r.gold_partial_type, r.partial_type, r.gold_secondary_types)
               for r, g, p in scored
               if g == "partial" and p != "supported" and r.gold_partial_type and r.partial_type]
    supported = [(r, p == "supported") for r, g, p in scored if g == "supported"]
    cleared: dict[str, list[bool]] = defaultdict(list)
    any_path: dict[str, list[bool]] = defaultdict(list)
    hit: dict[str, list[bool]] = defaultdict(list)
    for rec, ok in ((r, ok) for r, ok in supported if r.tool_misread_type):
        cleared[rec.tool_misread_type].append(ok)
        guard = GUARD_FOR_MISREAD.get(rec.tool_misread_type)
        if guard is not None and guard_can_run(rec):
            any_path[rec.tool_misread_type].append(ok)
            hit[rec.tool_misread_type].append(ok and guard in rec.guards_applied)
    fired = Counter(g for r, _, _ in scored for g in r.guards_applied)
    return {
        "partial_type_accuracy_flagged": safe_div(sum(flagged), len(flagged)),
        "partial_type_flagged": ratio(flagged),
        "gold_supported_cleared": ratio([ok for _, ok in supported]),
        "cleared_by_misread": ratios(cleared),
        "misread_cleared_any": ratios(any_path),
        "misread_guard_hit": ratios(hit),
        "guards_fired": dict(sorted(fired.items())),
        "guards_by_gold": table([(g, guard) for r, g, _ in scored for guard in r.guards_applied]),
    }
