"""Reuse of an earlier run's records: screen answers (--screen-from) and the verdicts that
score an --offline run's needs_call pairs (--fallback-from), plus the offline cost report.

The screen (Decisions API) is not cached, so a replay reuses the probabilities recorded
per item; the ScreenResult is rebuilt exactly as screen.run_screen builds it (s, p_problem
rounded to 6 places, model, error), with cost and latency 0 because no call is made.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from eval_models import ItemRecord, MissedCall, ScreenRecord
from pydantic import BaseModel, Field

from refcheck.llm.model_lookup import spec_for
from refcheck.stages.verify_claims.screen import ScreenResult

LOWER_BOUND_NOTE = ("lower bound: a call after a missed one depends on its answer, so a "
                    "live run may need more")


class OfflineReport(BaseModel):
    """What a live run would still have to call (and roughly pay) for this replay."""

    pairs_needing_calls: int = 0
    pairs_without_fallback: int = 0  # needs_call pairs the fallback run does not score
    calls_by_role: dict[str, int] = Field(default_factory=dict)  # "chat:verifier" -> n
    est_cost_usd: float = 0.0
    setup_calls: int = 0  # misses outside any pair (source loading)
    note: str = LOWER_BOUND_NOTE


def load_run(results_dir: Path, run_name: str) -> dict[str, ItemRecord]:
    """The run's records by item id (items.jsonl); SystemExit when the run is missing."""
    path = results_dir / run_name / "items.jsonl"
    if not path.is_file():
        raise SystemExit(f"no recorded run {run_name!r}: {path} not found")
    records: dict[str, ItemRecord] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rec = ItemRecord.model_validate_json(line)
                records[rec.id] = rec
    return records


def recorded_screens(records: Mapping[str, ItemRecord]) -> dict[str, ScreenRecord]:
    """Item id -> its recorded screen answer (items without one are left out)."""
    return {item_id: rec.screen for item_id, rec in records.items() if rec.screen is not None}


def _display(model: str) -> str:
    try:
        return spec_for(model, "decision").label if model else ""
    except Exception:  # noqa: BLE001 - an unknown recorded model only loses its label
        return ""


def recorded_screen(rec: ScreenRecord) -> ScreenResult:
    """The ScreenResult run_screen returned for this record (no call: cost/latency 0)."""
    return ScreenResult(
        probs=dict(rec.probs), refused=list(rec.refused), s=rec.s,
        p_problem=None if rec.s is None else round(1.0 - rec.s, 6), model=rec.model,
        model_display=_display(rec.model), input_tokens=rec.input_tokens, error=rec.error)


# Fields a fallback record keeps from the current item (its gold may be newer).
_ITEM_FIELDS = ("id", "dataset", "synthetic", "gold_label", "gold_binary", "fine_label",
                "gold_partial_type", "gold_secondary_types", "tool_misread_type",
                "gold_confidence", "split", "gold_source", "eval_flags", "subset_role", "coverage",
                "quality_reason")


def fallback_record(current: ItemRecord, reference: ItemRecord | None,
                    misses: list[MissedCall]) -> ItemRecord:
    """A needs_call pair: the reference run's tool fields under the current gold, or an
    unscored error record when the reference run has no verdict for it."""
    flags = {"needs_call": True, "missed_calls": list(misses), "cost_usd": 0.0}
    if reference is None:
        return current.model_copy(update={
            **flags, "verdict": "error",
            "error": f"needs_call: {len(misses)} uncached call(s), no fallback verdict"})
    keep = {name: getattr(current, name) for name in _ITEM_FIELDS}
    return reference.model_copy(update={**keep, **flags, "mode": current.mode})


def _call_key(call: MissedCall) -> str:
    return f"{'live-' if call.live else ''}{call.kind}:{call.role or '-'}"


def offline_report(records: Iterable[ItemRecord],
                   setup: list[MissedCall]) -> OfflineReport:
    """Pairs that need calls, calls per kind:role and their estimated cost."""
    needs = [r for r in records if r.needs_call]
    calls = [c for r in needs for c in r.missed_calls] + list(setup)
    return OfflineReport(
        pairs_needing_calls=len(needs),
        pairs_without_fallback=sum(1 for r in needs if r.verdict == "error"),
        calls_by_role=dict(sorted(Counter(_call_key(c) for c in calls)
                                  .items())),
        est_cost_usd=round(sum(c.est_cost_usd for c in calls), 6), setup_calls=len(setup))


def offline_line(report: OfflineReport | None) -> str:
    """One log line of the offline report ("" when the run was not offline)."""
    if report is None:
        return ""
    roles = ", ".join(f"{k}={v}" for k, v in report.calls_by_role.items()) or "none"
    return (f"offline: {report.pairs_needing_calls} pair(s) need uncached calls "
            f"({report.pairs_without_fallback} without a fallback verdict); calls {roles}; "
            f"est. ${report.est_cost_usd:.4f} for a live run ({report.note}); "
            f"setup misses {report.setup_calls}")
