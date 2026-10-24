"""Build a Citation-Integrity eval subset from a reference run: its misses, its over-harsh
rows and stratified controls (V5.7 eval plan step 3). Write it OUTSIDE the repo.

  python scripts/eval/build_ci_subset.py --run v56-cascade-ci-test --controls 60 \
      --label-noise <id>,<id> --out ~/.refcheck/eval/citation_integrity.v57sub.jsonl

Rows come from --dataset/--split (default citation_integrity test.bal), file order kept
inside each role:
- fn: a gold problem the run showed supported;
- fp: a row with fine label ACCURATE the run flagged (partial or negative);
- control: --controls of the remaining rows, stratified by fine label (largest-remainder
  allocation with at least one per label, a seeded random draw inside each label).
Each row is the dataset row plus subset_role, ref_verdict (the run's verdict) and
eval_flags ("etiquette" for fine label ETIQUETTE, "label_noise" for --label-noise ids),
so run_eval reports flagged rows apart from the clean ones (eval_hygiene groups).
<out>.manifest.json records the arguments, counts and ids per role.
"""

import argparse
import json
import logging
import random
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from eval_clearance import predicted_label
from eval_cli import setup_logging
from eval_data import resolve_dataset
from eval_models import RESULTS_DIR, ItemRecord
from eval_recorded import load_run

logger = logging.getLogger("build_ci_subset")
ETIQUETTE = "ETIQUETTE"
OK_FINE_LABEL = "ACCURATE"


def run_roles(records: Mapping[str, ItemRecord]) -> dict[str, str]:
    """Item id -> "fn" (gold problem shown supported) / "fp" (ACCURATE row flagged)."""
    roles: dict[str, str] = {}
    for item_id, rec in records.items():
        label = predicted_label(rec)
        if label is None:
            continue
        if rec.gold_binary == "problem" and label == "supported":
            roles[item_id] = "fn"
        elif rec.fine_label == OK_FINE_LABEL and label != "supported":
            roles[item_id] = "fp"
    return roles


def allocate(sizes: Mapping[str, int], total: int) -> dict[str, int]:
    """Largest-remainder split of ``total`` over the strata: at least one per non-empty
    stratum when ``total`` allows, never more than a stratum holds."""
    strata = {k: v for k, v in sorted(sizes.items()) if v > 0}
    pool = sum(strata.values())
    total = min(total, pool)
    if total <= 0:
        return {}
    floor = 1 if total >= len(strata) else 0
    counts = {k: min(v, max(floor, total * v // pool)) for k, v in strata.items()}
    order = sorted(strata, key=lambda k: (-((total * strata[k]) % pool), k))
    for step in range(len(order) * (total + 1)):  # hand out the rest, remainders first
        if sum(counts.values()) >= total:
            break
        key = order[step % len(order)]
        counts[key] += 1 if counts[key] < strata[key] else 0
    while sum(counts.values()) > total:  # floors overshot: trim the most over-served
        key = max((k for k in counts if counts[k] > floor),
                  key=lambda k: (counts[k] - total * strata[k] / pool, k))
        counts[key] -= 1
    return counts


def stratified(ids_by_label: Mapping[str, list[str]], total: int, seed: int) -> list[str]:
    """Seeded stratified draw of ``total`` ids (allocate); returned in label/file order."""
    rng = random.Random(seed)
    counts = allocate({k: len(v) for k, v in ids_by_label.items()}, total)
    picked: list[str] = []
    for label, count in counts.items():
        chosen = set(rng.sample(ids_by_label[label], count))
        picked += [i for i in ids_by_label[label] if i in chosen]
    return picked


def row_flags(row: Mapping[str, object], noise: set[str]) -> list[str]:
    flags = ["etiquette"] if row.get("fine_label") == ETIQUETTE else []
    return flags + (["label_noise"] if row.get("id") in noise else [])


def build_subset(rows: list[dict[str, object]], records: Mapping[str, ItemRecord],
                 controls: int, seed: int, noise: set[str]) -> list[dict[str, object]]:
    """The subset rows: fn, then fp, then controls (module doc)."""
    roles = run_roles(records)
    rest: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if str(row["id"]) not in roles:
            rest[str(row.get("fine_label") or "")].append(str(row["id"]))
    roles.update({i: "control" for i in stratified(rest, controls, seed)})
    by_id = {str(r["id"]): r for r in rows}
    out: list[dict[str, object]] = []
    for role in ("fn", "fp", "control"):
        for item_id in (str(r["id"]) for r in rows if roles.get(str(r["id"])) == role):
            row = by_id[item_id]
            ref = records.get(item_id)
            out.append({**row, "subset_role": role,
                        "ref_verdict": ref.verdict if ref is not None else "",
                        "eval_flags": row_flags(row, noise)})
    return out


def read_rows(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def manifest(args: argparse.Namespace, subset: list[dict[str, object]],
             noise: set[str]) -> dict[str, object]:
    ids: dict[str, list[str]] = defaultdict(list)
    for row in subset:
        ids[str(row["subset_role"])].append(str(row["id"]))
    flags: dict[str, int] = defaultdict(int)
    for row in subset:
        for flag in row["eval_flags"] if isinstance(row["eval_flags"], list) else []:
            flags[str(flag)] += 1
    missing = sorted(noise - {str(r["id"]) for r in subset})
    return {"run": args.run, "dataset": args.dataset, "split": args.split,
            "controls": args.controls, "seed": args.seed, "n": len(subset),
            "by_role": {k: len(v) for k, v in ids.items()}, "flags": dict(flags),
            "label_noise_not_in_subset": missing, "ids": dict(ids)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="reference run (results dir name)")
    p.add_argument("--dataset", default="citation_integrity")
    p.add_argument("--split", default="test.bal")
    p.add_argument("--controls", type=int, default=60)
    p.add_argument("--seed", type=int, default=57)
    p.add_argument("--label-noise", action="append", default=[],
                   help="comma-separated ids reported apart as label noise (repeatable)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> list[dict[str, object]]:
    args = parse_args(argv)
    noise = {i.strip() for v in args.label_noise for i in v.split(",") if i.strip()}
    rows = read_rows(resolve_dataset(args.dataset, args.split))
    subset = build_subset(rows, load_run(args.results_dir, args.run), args.controls,
                          args.seed, noise)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in subset),
                   encoding="utf-8")
    info = manifest(args, subset, noise)
    out.with_suffix(".manifest.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    logger.info("%d rows -> %s (by role %s, flags %s)", len(subset), out, info["by_role"],
                info["flags"])
    if info["label_noise_not_in_subset"]:
        logger.warning("label-noise ids not in the subset: %s", info["label_noise_not_in_subset"])
    return subset


if __name__ == "__main__":
    setup_logging()
    main()
