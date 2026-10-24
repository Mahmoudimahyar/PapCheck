"""Fixed-sequence Clopper-Pearson calibration of the screen's t_accept.

Thresholds are tested from the most conservative (0.99) downwards. At each
t the WHOLE clearance rule is applied (code gates + s >= t + verifier
co-sign when the run has verifier calls) and H0 "problem rate among cleared
pairs > alpha" is rejected when the one-sided Clopper-Pearson upper bound is
<= alpha. Testing stops at the first t that fails (fixed-sequence procedure:
no multiplicity correction needed); the chosen t_accept is the last one
that passed. If even the first fails, auto-clear must stay off.
"""

from collections.abc import Iterable, Sequence

from eval_clearance import cleared, has_verifier, verifier_layer
from eval_models import ItemRecord
from eval_stats import clopper_pearson_upper, safe_div
from pydantic import BaseModel


class ScanRow(BaseModel):
    """The clearance rule evaluated at one threshold."""

    t_accept: float
    n_cleared: int
    problems: int
    coverage: float | None
    problem_rate: float | None
    upper_bound: float
    passed: bool


def default_grid(start: float = 0.99, stop: float = 0.50, step: float = 0.01) -> list[float]:
    """Descending thresholds start, start - step, ..., stop (rounded to 4 dp)."""
    count = int(round((start - stop) / step)) + 1
    return [round(start - i * step, 4) for i in range(count)]


def merge_records(runs: Iterable[Sequence[ItemRecord]]) -> list[ItemRecord]:
    """Merge runs by item id: the screen from the first run that has one, the
    verifier layers from the first run that has them (e.g. a screen run + a
    verifier run on the same split)."""
    merged: dict[str, ItemRecord] = {}
    for records in runs:
        for rec in records:
            base = merged.get(rec.id)
            if base is None:
                merged[rec.id] = rec
                continue
            update: dict[str, object] = {}
            if base.screen is None and rec.screen is not None:
                update.update(screen=rec.screen, gate_failures=rec.gate_failures,
                              clear_eligible=rec.clear_eligible)
            if not has_verifier(base) and has_verifier(rec):
                update["layers"] = [lay for lay in rec.layers if lay.role == "verifier"]
            if update:
                merged[rec.id] = base.model_copy(update=update)
    return list(merged.values())


def scan(records: Sequence[ItemRecord], grid: Sequence[float], alpha: float,
         confidence: float = 0.95, cosign: bool = True) -> list[ScanRow]:
    """Evaluate every threshold, marking the fixed-sequence pass/fail."""
    rows: list[ScanRow] = []
    still_testing = True
    for t in grid:
        hits = [r for r in records if cleared(r, t, cosign)]
        problems = sum(1 for r in hits if r.gold_binary == "problem")
        bound = clopper_pearson_upper(problems, len(hits), confidence)
        passed = still_testing and bound <= alpha
        still_testing = passed
        rows.append(ScanRow(t_accept=t, n_cleared=len(hits), problems=problems,
                            coverage=safe_div(len(hits), len(records)),
                            problem_rate=safe_div(problems, len(hits)),
                            upper_bound=round(bound, 6), passed=passed))
    return rows


def choose(rows: Sequence[ScanRow]) -> ScanRow | None:
    """Lowest threshold that passed before the first failure (rows in test order)."""
    chosen: ScanRow | None = None
    for row in rows:
        if not row.passed:
            break
        chosen = row
    return chosen


def cosign_available(records: Sequence[ItemRecord]) -> bool:
    return any(has_verifier(r) for r in records)


def verifier_errors(records: Sequence[ItemRecord]) -> int:
    """Pairs whose decisive verifier call failed (they can never be co-signed)."""
    return sum(1 for r in records
               if (lay := verifier_layer(r)) is not None and lay.verdict is None)
