"""Scoring hygiene (V5.7 #12): error shapes, the review tier and the scoring groups.

- tpr / tnr: gold problems flagged (partial or negative) / gold supported shown supported.
- near misses: a one-step error between supported and partial (gold partial shown
  supported = near_missed; gold supported shown partial = near_over); far misses skip a
  class (gold negative shown supported = far_missed; gold supported shown negative =
  far_over); partial <-> negative is a severity error, not a miss.
- review tier: a supported verdict the reader is still told to check (needs_review or the
  report's "check first" signal). missed_partial_surfaced = gold partials shown supported
  that carry such a flag; review_tier_recall_partial / _problem = gold partials / problems
  either flagged by the verdict or surfaced by the review tier; review_load = supported
  verdicts with a review flag.
- groups (summary "groups"): split:<dev|test>, flag:<etiquette|label_noise|...>,
  role:<fn|fp|control> (subset rows), source:<gold_source>, and "clean" (no eval flag)
  whenever any record carries a flag, so noisy rows are reported apart, not mixed in.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence

from eval_clearance import predicted_label
from eval_models import ItemRecord
from eval_partial import three_way
from eval_stats import safe_div
from pydantic import BaseModel


class Hygiene(BaseModel):
    tpr: float | None = None
    tpr_n: str = "0/0"
    tnr: float | None = None
    tnr_n: str = "0/0"
    near_missed: int = 0  # gold partial -> supported
    far_missed: int = 0  # gold negative -> supported
    near_over: int = 0  # gold supported -> partial
    far_over: int = 0  # gold supported -> negative
    severity_errors: int = 0  # partial <-> negative
    missed_partial_surfaced: str = "0/0"
    missed_problem_surfaced: str = "0/0"
    review_tier_recall_partial: float | None = None
    review_tier_recall_problem: float | None = None
    review_load: str = "0/0"
    needs_call: int = 0  # --offline pairs scored from the fallback run


def review_flag(rec: ItemRecord) -> bool:
    """The reader is told to check this result (needs_review or "check first")."""
    return rec.needs_review or rec.check_first


def scored_pairs(records: Sequence[ItemRecord]) -> list[tuple[ItemRecord, str, str]]:
    """(record, gold 3-way, predicted 3-way) of every scorable record."""
    out: list[tuple[ItemRecord, str, str]] = []
    for rec in records:
        label = predicted_label(rec)
        gold, pred = three_way(rec.gold_label), three_way(label) if label else None
        if gold is not None and pred is not None:
            out.append((rec, gold, pred))
    return out


def _ratio(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)}"


def compute_hygiene(records: Sequence[ItemRecord]) -> Hygiene | None:
    """Hygiene metrics over the scorable records (None when nothing is scorable)."""
    scored = scored_pairs(records)
    if not scored:
        return None
    problems = [(r, p) for r, g, p in scored if g != "supported"]
    partials = [(r, p) for r, g, p in scored if g == "partial"]
    ok = [p == "supported" for _, g, p in scored if g == "supported"]
    cells = Counter((g, p) for _, g, p in scored)
    caught_part = [p != "supported" or review_flag(r) for r, p in partials]
    caught_prob = [p != "supported" or review_flag(r) for r, p in problems]
    supported = [review_flag(r) for r, _, p in scored if p == "supported"]
    return Hygiene(
        tpr=safe_div(sum(p != "supported" for _, p in problems), len(problems)),
        tpr_n=_ratio([p != "supported" for _, p in problems]),
        tnr=safe_div(sum(ok), len(ok)), tnr_n=_ratio(ok),
        near_missed=cells[("partial", "supported")], far_missed=cells[("negative", "supported")],
        near_over=cells[("supported", "partial")], far_over=cells[("supported", "negative")],
        severity_errors=cells[("partial", "negative")] + cells[("negative", "partial")],
        missed_partial_surfaced=_ratio([review_flag(r) for r, p in partials
                                        if p == "supported"]),
        missed_problem_surfaced=_ratio([review_flag(r) for r, p in problems
                                        if p == "supported"]),
        review_tier_recall_partial=safe_div(sum(caught_part), len(caught_part)),
        review_tier_recall_problem=safe_div(sum(caught_prob), len(caught_prob)),
        review_load=_ratio(supported), needs_call=sum(1 for r in records if r.needs_call))


def group_records(records: Sequence[ItemRecord]) -> dict[str, list[ItemRecord]]:
    """Records per scoring group (module doc); empty when no record has a group key."""
    groups: dict[str, list[ItemRecord]] = defaultdict(list)
    flagged = any(r.eval_flags for r in records)
    for rec in records:
        keys = [f"split:{rec.split}"] if rec.split else []
        keys += [f"flag:{flag}" for flag in rec.eval_flags]
        keys += [f"role:{rec.subset_role}"] if rec.subset_role else []
        keys += [f"source:{rec.gold_source}"] if rec.gold_source else []
        keys += ["clean"] if flagged and not rec.eval_flags else []
        for key in keys:
            groups[key].append(rec)
    return dict(sorted(groups.items()))


def hygiene_line(name: str, h: Hygiene | None) -> str:
    """One compact log line of the hygiene metrics."""
    if h is None:
        return f"{name}: hygiene -"

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{100 * value:.1f}%"

    return (f"{name}: TPR {h.tpr_n}={pct(h.tpr)} TNR {h.tnr_n}={pct(h.tnr)} | missed near "
            f"{h.near_missed} far {h.far_missed} | over-harsh near {h.near_over} far "
            f"{h.far_over} | severity {h.severity_errors} | missed partials surfaced "
            f"{h.missed_partial_surfaced} (problems {h.missed_problem_surfaced}) | "
            f"review-tier recall partial={pct(h.review_tier_recall_partial)} problem="
            f"{pct(h.review_tier_recall_problem)} | review load {h.review_load}"
            + (f" | needs_call {h.needs_call}" if h.needs_call else ""))
