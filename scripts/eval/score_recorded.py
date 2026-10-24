"""Score an app run's recorded verdicts on the manuscript gold set (no API calls).

  python scripts/eval/score_recorded.py --session sess_xxxxxxxxxxxx              # all gold pairs
  python scripts/eval/score_recorded.py --split dev --session sess_xxxxxxxxxxxx

Reads the gold rows (refcheck_v49_gold, excluded rows skipped) and the run's
verifications from ~/.refcheck/refcheck.db (read-only), matches them on
(sentence, reference), and writes items.jsonl + summary.json (mode
"recorded") under ~/.refcheck/eval/results/<run_name>/. With --split all the
dev and test blocks are logged and written to by_split.json as well, plus a
"review_D" block over the pairs review D covered (every tool-"supported" verdict
of one run, scored against each pair's gold label).
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from eval_cli import setup_logging
from eval_data import load_items, resolve_dataset
from eval_metrics import MetricBlock, RunSummary, compute_block, summarize
from eval_models import RESULTS_DIR, ItemRecord, RunMeta
from eval_partial import partial_line
from eval_report import block_line, summary_lines
from gold_db import DEFAULT_DB, load_session
from gold_models import GOLD_DATASET, GoldRow
from gold_recorded import find_verification, recorded_record
from pydantic import BaseModel, Field

logger = logging.getLogger("score_recorded")


class SplitBlocks(BaseModel):
    blocks: dict[str, MetricBlock] = Field(default_factory=dict)
    subsets: dict[str, MetricBlock] = Field(default_factory=dict)  # "review_D": its pairs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default=GOLD_DATASET, help="gold dataset name or .jsonl path")
    p.add_argument("--split", default="all", help="all | dev | test")
    p.add_argument("--session", required=True, help="app run (session id) to score")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--run-name", default="")
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return p.parse_args(argv)


def gold_rows(path: Path) -> list[GoldRow]:
    rows = [item.gold_row for item in load_items(path) if item.gold_row is not None]
    if not rows:
        raise SystemExit(f"{path} has no gold manuscript rows")
    return rows


def score(rows: list[GoldRow], session_id: str, db: Path) -> list[ItemRecord]:
    session = load_session(session_id, db)
    index = session.pair_index()
    return [recorded_record(row, find_verification(row, session, index)) for row in rows]


def split_blocks(rows: list[GoldRow], records: list[ItemRecord]) -> SplitBlocks:
    split_of = {r.id: r.split for r in rows}
    reviewed_d = {r.id for r in rows if r.review_d_cases}
    return SplitBlocks(blocks={
        split: compute_block([r for r in records if split_of.get(r.id) == split], None)
        for split in ("dev", "test")}, subsets={
        "review_D": compute_block([r for r in records if r.id in reviewed_d], None)
        } if reviewed_d else {})


def run(args: argparse.Namespace) -> RunSummary:
    path = resolve_dataset(args.dataset, args.split)
    rows = gold_rows(path)
    started = datetime.now().isoformat(timespec="seconds")
    records = score(rows, args.session, args.db)
    name = args.run_name or f"{path.stem}-recorded-{args.session}-{datetime.now():%Y%m%d-%H%M%S}"
    out_dir = args.results_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "items.jsonl").open("w", encoding="utf-8") as handle:
        for rec in records:
            handle.write(rec.model_dump_json() + "\n")
    roles = {lay.role: lay.model_id for rec in records for lay in rec.layers}
    meta = RunMeta(
        run_name=name, mode="recorded", dataset=args.dataset, split=args.split,
        dataset_path=str(path), n_items=len(records), source="auto", use_embeddings=True,
        concurrency=0, started_at=started, finished_at=datetime.now().isoformat(
            timespec="seconds"), roles=dict(sorted(roles.items())),
        thresholds={"source": f"recorded:{args.session}"},
        total_cost_usd=round(sum(r.cost_usd for r in records), 6))
    summary = summarize(records, meta)
    (out_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    for line in summary_lines(summary):
        logger.info("%s", line)
    if args.split in ("all", ""):
        blocks = split_blocks(rows, records)
        (out_dir / "by_split.json").write_text(blocks.model_dump_json(indent=2),
                                               encoding="utf-8")
        for split, block in {**blocks.blocks, **blocks.subsets}.items():
            logger.info("%s", block_line(f"  {split}", block))
            logger.info("    %s", partial_line(block.partial))
    missing = sum(1 for r in records if r.error)
    if missing:
        logger.warning("%d gold pairs have no verdict in %s", missing, args.session)
    logger.info("Results: %s", out_dir)
    return summary


if __name__ == "__main__":
    setup_logging()
    run(parse_args())
