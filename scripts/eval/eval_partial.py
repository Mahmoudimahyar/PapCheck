"""Partial-verdict metrics: 3-way accuracy, harshness / miss rates, sub-type confusions.

3-way classes: supported | partial | negative (not_supported, contradicted, not_relevant;
insufficient_evidence and "not in source" cannot_verify count as not_supported, see
eval_clearance.predicted_label). Errors and other cannot_verify results are not scored.

- over_harsh_rate / missed_problem_rate / missed_partial_rate: gold supported -> tool
  partial or negative / gold negative -> tool supported / gold partial -> tool supported.
- coverage_limited: tool partials typed coverage_limited (abstract only: "could not
  verify" the rest, not an author error); over_harsh_excl_coverage leaves those pairs
  out of the over-harsh rate entirely, as cannot_verify results are.
- by_gold_partial_type: what the tool says (3-way) per gold partial sub-type.
- misread_flagged: per tool_misread_type (gold supported pairs that LOOK partial), how
  many the tool still flags (the "minor issue" routing should clear them).
- partial_type_confusion / misread_type_confusion: gold sub-type (or misread type) ->
  the tool's partial_type; type accuracy counts a gold evidence_gap as the tool's
  coverage_limited (no full text to resolve it), see type_matches.
- V5.4 sub-type accuracy (flagged), clearance and guard metrics: eval_guards.py
  (misread_cleared_any = cleared by any path vs misread_guard_hit = cleared by the
  misread's own guard, over the pairs that guard can act on).
"""

from collections import defaultdict
from collections.abc import Sequence

from eval_clearance import predicted_label
from eval_guards import guard_metrics, ratios, table, type_matches
from eval_models import ItemRecord
from eval_stats import safe_div
from pydantic import BaseModel, Field

THREE_WAY = {"supported": "supported", "partially_supported": "partial",
             "not_supported": "negative", "contradicted": "negative",
             "not_relevant": "negative"}


class WhatIf(BaseModel):
    """Headline rates under a counterfactual verdict mapping."""

    accuracy_3way: float | None = None
    over_harsh_rate: float | None = None
    missed_partial_rate: float | None = None


class PartialMetrics(BaseModel):
    n_scored: int = 0
    accuracy_3way: float | None = None
    confusion_3way: dict[str, dict[str, int]] = Field(default_factory=dict)  # gold -> pred
    over_harsh_rate: float | None = None
    over_harsh: str = "0/0"
    coverage_limited: int = 0  # tool partials typed coverage_limited (all gold labels)
    coverage_limited_gold_supported: int = 0
    over_harsh_excl_coverage_rate: float | None = None
    over_harsh_excl_coverage: str = "0/0"
    missed_problem_rate: float | None = None
    missed_problem: str = "0/0"
    missed_partial_rate: float | None = None
    missed_partial: str = "0/0"
    by_gold_partial_type: dict[str, dict[str, int]] = Field(default_factory=dict)
    misread_flagged: dict[str, str] = Field(default_factory=dict)
    partial_type_confusion: dict[str, dict[str, int]] = Field(default_factory=dict)
    partial_type_accuracy: float | None = None
    misread_type_confusion: dict[str, dict[str, int]] = Field(default_factory=dict)
    accuracy_3way_by_confidence: dict[str, float | None] = Field(default_factory=dict)
    # Tool partials: gold 3-way class -> the deciding layer's "problem_type/severity".
    tool_problem_by_gold: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Counterfactual routing: a "minor" tool partial shown as supported.
    whatif_minor_as_supported: WhatIf | None = None
    # V5.4 partial sub-types and guards (eval_guards.guard_metrics)
    partial_type_accuracy_flagged: float | None = None
    partial_type_flagged: str = "0/0"
    gold_supported_cleared: str = "0/0"
    cleared_by_misread: dict[str, str] = Field(default_factory=dict)
    misread_cleared_any: dict[str, str] = Field(default_factory=dict)
    misread_guard_hit: dict[str, str] = Field(default_factory=dict)
    guards_fired: dict[str, int] = Field(default_factory=dict)
    guards_by_gold: dict[str, dict[str, int]] = Field(default_factory=dict)


def three_way(label: str) -> str | None:
    return THREE_WAY.get(label)


def _rate(pairs: list[tuple[str, str]], gold: str, bad: set[str]) -> tuple[float | None, str]:
    rows = [p for g, p in pairs if g == gold]
    hits = sum(1 for p in rows if p in bad)
    return safe_div(hits, len(rows)), f"{hits}/{len(rows)}"


def _whatif_minor(scored: list[tuple[ItemRecord, str, str]]) -> WhatIf:
    pairs = [(g, "supported" if p == "partial" and r.severity == "minor" else p)
             for r, g, p in scored]
    return WhatIf(accuracy_3way=safe_div(sum(1 for g, p in pairs if g == p), len(pairs)),
                  over_harsh_rate=_rate(pairs, "supported", {"partial", "negative"})[0],
                  missed_partial_rate=_rate(pairs, "partial", {"supported"})[0])


def compute_partial(records: Sequence[ItemRecord]) -> PartialMetrics | None:
    """Partial metrics over the scorable records (None when nothing is scorable)."""
    scored: list[tuple[ItemRecord, str, str]] = []
    for rec in records:
        label = predicted_label(rec)
        gold, pred = three_way(rec.gold_label), three_way(label) if label else None
        if gold is not None and pred is not None:
            scored.append((rec, gold, pred))
    if not scored:
        return None
    pairs = [(g, p) for _, g, p in scored]
    harsh, harsh_n = _rate(pairs, "supported", {"partial", "negative"})
    limited = [(r, g) for r, g, p in scored if p == "partial"
               and r.partial_type == "coverage_limited"]
    harsh_x, harsh_x_n = _rate([(g, p) for r, g, p in scored if p != "partial"
                                or r.partial_type != "coverage_limited"],
                               "supported", {"partial", "negative"})
    missed, missed_n = _rate(pairs, "negative", {"supported"})
    soft, soft_n = _rate(pairs, "partial", {"supported"})
    misread: dict[str, list[bool]] = defaultdict(list)
    for rec, gold, pred in scored:
        if gold == "supported" and rec.tool_misread_type:
            misread[rec.tool_misread_type].append(pred != "supported")
    typed_recs = [r for r, g, p in scored
                  if g == "partial" and p == "partial" and r.gold_partial_type and r.partial_type]
    typed = [(r.gold_partial_type, r.partial_type) for r in typed_recs]
    by_conf: dict[str, list[bool]] = defaultdict(list)
    for rec, gold, pred in scored:
        if rec.gold_confidence:
            by_conf[rec.gold_confidence].append(gold == pred)
    return PartialMetrics(
        n_scored=len(scored),
        accuracy_3way=safe_div(sum(1 for g, p in pairs if g == p), len(pairs)),
        confusion_3way=table(pairs), over_harsh_rate=harsh, over_harsh=harsh_n,
        coverage_limited=len(limited),
        coverage_limited_gold_supported=sum(1 for _, g in limited if g == "supported"),
        over_harsh_excl_coverage_rate=harsh_x, over_harsh_excl_coverage=harsh_x_n,
        missed_problem_rate=missed, missed_problem=missed_n, missed_partial_rate=soft,
        missed_partial=soft_n,
        by_gold_partial_type=table([(r.gold_partial_type, p) for r, g, p in scored
                                     if g == "partial" and r.gold_partial_type]),
        misread_flagged=ratios(misread),
        partial_type_confusion=table(typed),
        partial_type_accuracy=safe_div(sum(type_matches(
            r.gold_partial_type, r.partial_type, r.gold_secondary_types) for r in typed_recs),
            len(typed)),
        misread_type_confusion=table([(r.tool_misread_type, r.partial_type)
                                       for r, g, p in scored if g == "supported"
                                       and r.tool_misread_type and r.partial_type]),
        accuracy_3way_by_confidence={k: safe_div(sum(v), len(v))
                                     for k, v in sorted(by_conf.items())},
        tool_problem_by_gold=table([(g, f"{r.problem_type or '?'}/{r.severity or '?'}")
                                     for r, g, p in scored if p == "partial"]),
        whatif_minor_as_supported=_whatif_minor(scored),
    ).model_copy(update=guard_metrics(scored))


def partial_line(metrics: PartialMetrics | None) -> str:
    """One compact text line of the headline partial metrics."""
    if metrics is None:
        return "3-way: -"

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{100 * value:.1f}%"

    line = (f"3-way acc={pct(metrics.accuracy_3way)} (n={metrics.n_scored}) | over-harsh "
            f"{metrics.over_harsh}={pct(metrics.over_harsh_rate)} (without coverage_limited "
            f"{metrics.over_harsh_excl_coverage}={pct(metrics.over_harsh_excl_coverage_rate)})"
            f" | coverage_limited partials {metrics.coverage_limited} (gold-supported "
            f"{metrics.coverage_limited_gold_supported}) | missed-problem "
            f"{metrics.missed_problem}={pct(metrics.missed_problem_rate)} | missed-partial "
            f"{metrics.missed_partial}={pct(metrics.missed_partial_rate)}")
    if metrics.partial_type_accuracy is not None:
        line += f" | partial-type acc={pct(metrics.partial_type_accuracy)}"
    if metrics.partial_type_accuracy_flagged is not None:
        line += (f" | type acc (flagged) {metrics.partial_type_flagged}="
                 f"{pct(metrics.partial_type_accuracy_flagged)}")
    line += f" | gold-supported cleared {metrics.gold_supported_cleared}"
    if metrics.guards_fired:
        line += " | guards " + ", ".join(f"{k}={v}" for k, v in metrics.guards_fired.items())
    whatif = metrics.whatif_minor_as_supported
    if whatif is not None:
        line += (f" | if minor->supported: acc={pct(whatif.accuracy_3way)} over-harsh="
                 f"{pct(whatif.over_harsh_rate)} missed-partial="
                 f"{pct(whatif.missed_partial_rate)}")
    return line
