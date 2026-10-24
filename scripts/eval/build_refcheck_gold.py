"""Build the RefCheck manuscript gold benchmark (refcheck_v49_gold) from the manual reviews.

  python scripts/eval/build_refcheck_gold.py --session sess_xxxxxxxxxxxx
  python scripts/eval/build_refcheck_gold.py --session sess_xxxxxxxxxxxx --labels FINAL SUPPORTED
      (FINAL / SUPPORTED: gold_work/labels_final.json and gold_work/labels_supported.json
      under ~/.refcheck/eval)
  python scripts/eval/build_refcheck_gold.py --session sess_xxxxxxxxxxxx
      --labels FINAL SUPPORTED REVIEW_D --source-session review_D=sess_yyyyyyyyyyyy
      (REVIEW_D: gold_work/labels_review_d.json; its new rows come from the later run)

Reads review A/B files and the fixed run's claims/references (DB opened
read-only) and writes ~/.refcheck/eval/refcheck_v49_gold.jsonl plus .dev/.test
(split by paper, ~60/40, stratified by label, fixed seed) and a manifest.
Optional labels files ({pair_id: {gold_label, gold_partial_type, tool_misread_type(s),
secondary_types, partial_types, severity, flags, gold_basis, gold_confidence, notes,
exclude}}; a pair id may appear in one file only) override/extend the
review-derived labels. Entries with gold_source "review_C"/"review_D" may name pairs
no review covers: their rows are built from the session (or the run named by
--source-session for that source; gold_extra) and join the split their paper
already has. keep_existing entries only annotate a pair the gold set already
labels (gold_annotate: label kept, review verdict/notes/flags recorded).
Output holds manuscript text: never write it into the repo.
"""

import argparse
import json
import logging
from pathlib import Path

from eval_models import EVAL_DIR
from gold_annotate import annotate, load_annotations
from gold_db import DEFAULT_DB, SessionData, load_session
from gold_extra import extra_rows, join_in_stages
from gold_manifest import build_manifest
from gold_merge import build_rows
from gold_models import GOLD_DATASET, REVIEW_LABELS, GoldRow, LabelOverride
from gold_reviews import load_review_a, load_review_b
from gold_split import (
    DEFAULT_DEV_FRACTION,
    DEFAULT_SEED,
    apply_labels,
    assign_splits,
    load_label_files,
)
from pydantic import BaseModel, Field

logger = logging.getLogger("build_refcheck_gold")
V49 = Path.home() / ".refcheck" / "e2e" / "v4.9"
GOLD_WORK = EVAL_DIR / "gold_work"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--review-a", type=Path, default=V49 / "review")
    p.add_argument("--notes-a", type=Path, default=GOLD_WORK / "review_a_manual_notes.json",
                   help="optional per-case notes of review A ({case: [verdict, evidence, fix]})")
    p.add_argument("--review-b", type=Path, default=V49 / "review_partial")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--session", required=True, help="app session id (sess_…) in the database")
    p.add_argument("--labels", type=Path, nargs="+", action="extend", default=None,
                   help="optional labels JSON file(s); repeatable")
    p.add_argument("--source-session", action="append", default=[], metavar="SOURCE=SESSION",
                   help="build new rows of one gold_source from another run, e.g. "
                        "review_D=sess_…; repeatable")
    p.add_argument("--out-dir", type=Path, default=EVAL_DIR)
    p.add_argument("--name", default=GOLD_DATASET)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--dev-fraction", type=float, default=DEFAULT_DEV_FRACTION)
    return p.parse_args(argv)


def _write(path: Path, rows: list[GoldRow]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def check_labels(labels: dict[str, LabelOverride]) -> None:
    bad = {k: v.gold_label for k, v in labels.items()
           if v.gold_label is not None and v.gold_label not in REVIEW_LABELS}
    if bad:
        raise SystemExit(f"labels file: unknown gold_label(s) {bad}")


def source_sessions(args: argparse.Namespace) -> dict[str, SessionData]:
    """--source-session SOURCE=SESSION pairs, each run loaded read-only."""
    out: dict[str, SessionData] = {}
    for item in args.source_session:
        source, sep, sid = item.partition("=")
        if not sep or not source.strip() or not sid.strip():
            raise SystemExit(f"--source-session expects SOURCE=SESSION, got {item!r}")
        out[source.strip()] = load_session(sid.strip(), args.db, with_verifications=False)
    return out


class Built(BaseModel):
    rows: list[GoldRow]
    unknown: list[str] = Field(default_factory=list)
    added: dict[str, str] = Field(default_factory=dict)
    annotated: dict[str, str] = Field(default_factory=dict)


def with_labels(rows: list[GoldRow], labels: dict[str, LabelOverride], session: SessionData,
                args: argparse.Namespace) -> Built:
    """Reviewed rows with labels applied + rows built from labels alone (review_C/D)
    + keep_existing annotations of labelled pairs."""
    extra, _ = extra_rows(labels, {r.id for r in rows}, session, source_sessions(args))
    new_ids = {r.id for r in extra}
    rows, unknown = apply_labels(rows, {k: v for k, v in labels.items() if k not in new_ids})
    extra, added = join_in_stages(rows, extra, args.dev_fraction, args.seed)
    notes = load_annotations(args.labels)
    check_labels(notes)
    rows, unknown_notes, annotated = annotate(rows + extra, notes)
    return Built(rows=sorted(rows, key=lambda r: (r.ref, r.claim_number)),
                 unknown=sorted(unknown + unknown_notes), added=added, annotated=annotated)


def build(args: argparse.Namespace) -> list[GoldRow]:
    session = load_session(args.session, args.db, with_verifications=False)
    verdicts = load_review_a(args.review_a, args.notes_a) + load_review_b(args.review_b)
    rows, missing = build_rows(verdicts, session)
    built = Built(rows=assign_splits(rows, args.dev_fraction, args.seed))
    if args.labels:
        labels = load_label_files(args.labels)
        check_labels(labels)
        built = with_labels(built.rows, labels, session, args)
    rows = built.rows
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write(args.out_dir / f"{args.name}.jsonl", rows)
    for split in ("dev", "test"):
        _write(args.out_dir / f"{args.name}.{split}.jsonl", [r for r in rows if r.split == split])
    info = build_manifest(rows, args, [f"{v.source}:{v.case}" for v in missing], built.unknown,
                          built.added, built.annotated)
    (args.out_dir / f"{args.name}.manifest.json").write_text(
        info.model_dump_json(indent=2), encoding="utf-8")
    logger.info("%d pairs (%d excluded) -> %s", info.n_rows, info.n_excluded, args.out_dir)
    logger.info("by split: %s", json.dumps(info.by_split))
    logger.info("by source: %s; confidence: %s", info.by_source, info.by_confidence)
    logger.info("added from labels: %d; annotated: %d; unknown label ids: %d",
                len(built.added), len(built.annotated), len(built.unknown))
    logger.info("needs adjudication: %d; excluded: %s", len(info.needs_adjudication),
                info.excluded)
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    build(parse_args())
