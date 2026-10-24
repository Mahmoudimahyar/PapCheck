"""Calibrate the screen's auto-clear threshold t_accept from eval run(s) on dev.

  python scripts/eval/calibrate_screen.py --run ~/.refcheck/eval/results/<cascade-run>
  python scripts/eval/calibrate_screen.py --run <screen-run> --run <verifier-run> --alpha 0.03

Fixed-sequence Clopper-Pearson scan (see eval_calibration.py) over the whole
clearance rule; writes ~/.refcheck/calibration/screen.json (read by
refcheck.stages.verify_claims.calibration) with the policy metadata that the
threshold is only valid for: screen model, question-template hash,
retrieval version, dataset, n, coverage and the bound. When no threshold
passes, the file disables auto-clear (auto_clear=false) but keeps the screen
pre-pass on (P(problem) ranking and the conflict check still run).
"""

import argparse
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from eval_calibration import (
    ScanRow,
    choose,
    cosign_available,
    default_grid,
    merge_records,
    scan,
    verifier_errors,
)
from eval_data import screen_template_hash
from eval_models import ItemRecord, RunMeta
from eval_report import table
from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.calibration import DEFAULT_INJECTION_MAX, calibration_path

logger = logging.getLogger("calibrate_screen")


class CalibrationFile(BaseModel):
    """screen.json: thresholds read by the app + provenance (unknown keys are ignored)."""

    t_accept: float
    injection_max: float = DEFAULT_INJECTION_MAX
    enabled: bool
    auto_clear: bool
    policy: dict[str, float] = Field(default_factory=dict)
    meta: dict[str, object] = Field(default_factory=dict)
    scan: list[ScanRow] = Field(default_factory=list)


def load_run(path: Path) -> tuple[list[ItemRecord], RunMeta | None]:
    """Records (+ meta when summary.json exists) from a run dir or an items.jsonl."""
    items = path / "items.jsonl" if path.is_dir() else path
    summary = items.parent / "summary.json"
    lines = items.read_text(encoding="utf-8").splitlines()
    records = [ItemRecord.model_validate_json(line) for line in lines if line.strip()]
    meta = None
    if summary.is_file():
        meta = RunMeta.model_validate(json.loads(summary.read_text(encoding="utf-8"))["meta"])
    return records, meta


def build_file(rows: list[ScanRow], chosen: ScanRow | None, records: list[ItemRecord],
               metas: list[RunMeta], args: argparse.Namespace, cosign: bool) -> CalibrationFile:
    screen_models = Counter(r.screen.model for r in records if r.screen and r.screen.model)
    hashes = {m.screen_template_hash for m in metas if m.screen_template_hash}
    current = screen_template_hash()
    if hashes and hashes != {current}:
        logger.warning("Screen template changed since the run(s) (%s != %s): the calibration "
                       "may not apply to the current questions", sorted(hashes), current)
    meta: dict[str, object] = {
        "method": "fixed-sequence one-sided Clopper-Pearson", "alpha": args.alpha,
        "confidence": args.confidence, "cosign": cosign,
        "screen_model": ", ".join(screen_models) or None,
        "question_template_hash": ", ".join(sorted(hashes)) or current,
        "retrieval_version": sorted({v for m in metas for v in m.retrieval_versions}),
        "dataset": sorted({m.dataset_path for m in metas}), "runs": [str(p) for p in args.run],
        "n": len(records), "n_cleared": chosen.n_cleared if chosen else 0,
        "coverage": chosen.coverage if chosen else 0.0,
        "problems": chosen.problems if chosen else None,
        "upper_bound": chosen.upper_bound if chosen else (rows[0].upper_bound if rows else None),
        "created": datetime.now().isoformat(timespec="seconds"),
        "reason": None if chosen else "no threshold met the bound; auto-clear disabled",
    }
    return CalibrationFile(
        t_accept=chosen.t_accept if chosen else 1.0, injection_max=args.injection_max,
        enabled=True, auto_clear=chosen is not None,
        policy={"t_contra": args.t_contra, "t_topic": args.t_topic}, meta=meta, scan=rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, action="append", required=True,
                   help="run dir or items.jsonl (repeat to merge screen + verifier runs)")
    p.add_argument("--alpha", type=float, default=0.03, help="max problem rate among cleared")
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--start", type=float, default=0.99)
    p.add_argument("--stop", type=float, default=0.50)
    p.add_argument("--step", type=float, default=0.01)
    p.add_argument("--no-cosign", action="store_true", help="ignore verifier co-sign")
    p.add_argument("--include-synthetic", action="store_true")
    p.add_argument("--injection-max", type=float, default=DEFAULT_INJECTION_MAX)
    p.add_argument("--t-contra", type=float, default=0.5)
    p.add_argument("--t-topic", type=float, default=0.5)
    p.add_argument("--out", type=Path, default=None, help="default: the app's screen.json")
    p.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> CalibrationFile:
    args = parse_args(argv)
    runs = [load_run(path.expanduser()) for path in args.run]
    records = merge_records([recs for recs, _ in runs])
    metas = [meta for _, meta in runs if meta is not None]
    if not args.include_synthetic:
        records = [r for r in records if not r.synthetic]
    records = [r for r in records if r.screen is not None]
    if not records:
        raise SystemExit("No records with screen results in the given run(s)")
    cosign = cosign_available(records) and not args.no_cosign
    rows = scan(records, default_grid(args.start, args.stop, args.step), args.alpha,
                args.confidence, cosign)
    chosen = choose(rows)
    result = build_file(rows, chosen, records, metas, args, cosign)
    logger.info("%d pairs, co-sign %s (%d verifier errors)", len(records),
                "on" if cosign else "off", verifier_errors(records))
    for line in table(["t", "cleared", "problems", "coverage", "rate", "CP-upper", "pass"],
                      [[f"{r.t_accept:.2f}", str(r.n_cleared), str(r.problems),
                        f"{r.coverage or 0:.3f}", f"{r.problem_rate or 0:.3f}",
                        f"{r.upper_bound:.4f}", "yes" if r.passed else "no"] for r in rows]):
        logger.info("%s", line)
    if chosen is None:
        logger.warning("No t_accept met CP upper <= %.3f: auto-clear must stay off", args.alpha)
    else:
        logger.info("t_accept=%.2f: coverage %.1f%%, %d/%d problems, CP upper %.4f",
                    chosen.t_accept, 100 * (chosen.coverage or 0), chosen.problems,
                    chosen.n_cleared, chosen.upper_bound)
    if not args.dry_run:
        out = args.out or calibration_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Wrote %s", out)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
