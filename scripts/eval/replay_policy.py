"""Compare dispute policies offline on recorded runs and a manual gold (no API calls).

  python scripts/eval/replay_policy.py \
      --cascade ~/.refcheck/eval/results/v51-cascade-ci-test \
      --cascade ~/.refcheck/eval/results/v51-cascade-scifact-test \
      --paired ~/.refcheck/eval/results/compare-...-verifier-claude-haiku-5-5-low \
               ~/.refcheck/eval/results/compare-...-verifier-gpt-6-luna-low \
      --gold ~/.refcheck/e2e/v4.9/review/manual_gold.json \
      --db ~/.refcheck/refcheck.db --session sess_xxxxxxxxxxxx

The manual gold is a JSON list of {case, claim_id, ref, manual}; the verifier
and cross-check verdicts of each case are read from the session's stored votes
(abbreviations "V" and "C"), with the database opened read-only. Only counts
are logged — never claim or source text.
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

from eval_models import ItemRecord
from policy_replay import (
    POLICIES,
    Policy,
    Scores,
    gold_agrees,
    replay_cascade,
    replay_paired,
    score,
)
from pydantic import BaseModel

logger = logging.getLogger("replay_policy")


class GoldCase(BaseModel):
    """One manually reviewed pair with the two recorded model verdicts."""

    case: int
    manual: str
    verifier: str
    confirm: str | None


def load_records(path: Path) -> list[ItemRecord]:
    items = path / "items.jsonl" if path.is_dir() else path
    with items.open(encoding="utf-8") as fh:
        return [ItemRecord.model_validate_json(line) for line in fh if line.strip()]


def load_gold(gold_path: Path, db_path: Path, session: str) -> list[GoldCase]:
    rows = json.loads(gold_path.read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    cases: list[GoldCase] = []
    try:
        for row in rows:
            found = con.execute(
                "SELECT votes_json FROM verifications WHERE session_id=? AND claim_id=? "
                "AND reference_id=?", (session, row["claim_id"], row["ref"])).fetchone()
            if found is None:
                logger.warning("case %s: no stored verification", row["case"])
                continue
            votes = {v.get("abbreviation"): v.get("verdict") for v in json.loads(found[0])}
            cases.append(GoldCase(case=row["case"], manual=row["manual"],
                                  verifier=votes.get("V") or "", confirm=votes.get("C")))
    finally:
        con.close()
    return cases


def _fmt(s: Scores) -> str:
    p = s.problem

    def num(x: float | None) -> str:
        return "-" if x is None else f"{x:.3f}"

    acc = "-" if s.accuracy_6way is None else f"{100 * s.accuracy_6way:.1f}%"
    return f"n={s.n} acc6={acc} problem P/R={num(p.precision)}/{num(p.recall)}"


def gold_agreement(cases: list[GoldCase], policy: Policy) -> str:
    shown = [policy(c.verifier, c.confirm) if c.verifier in ("not_supported", "contradicted",
                                                               "not_relevant") else c.verifier
             for c in cases]
    hits = sum(1 for c, v in zip(cases, shown, strict=True) if gold_agrees(c.manual, v))
    usable = [c for c in cases if c.manual != "wrong_paper"]
    hits_usable = sum(1 for c, v in zip(cases, shown, strict=True)
                      if c.manual != "wrong_paper" and gold_agrees(c.manual, v))
    return f"{hits}/{len(cases)} (excluding wrong-paper cases {hits_usable}/{len(usable)})"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cascade", type=Path, action="append", default=[],
                    help="cascade run dir or items.jsonl (repeatable)")
    ap.add_argument("--paired", type=Path, nargs=2, action="append", default=[],
                    metavar=("VERIFIER_RUN", "CONFIRM_RUN"),
                    help="verifier-mode runs of the verifier and the confirm model")
    ap.add_argument("--gold", type=Path, help="manual gold JSON (needs --db and --session)")
    ap.add_argument("--db", type=Path, default=Path.home() / ".refcheck" / "refcheck.db")
    ap.add_argument("--session", default="")
    args = ap.parse_args(argv)
    cascades = {p.name: load_records(p) for p in args.cascade}
    paired = {f"{a.name} x {b.name}": (load_records(a), {r.id: r for r in load_records(b)})
              for a, b in args.paired}
    gold = load_gold(args.gold, args.db, args.session) if args.gold and args.session else []
    for name, policy in POLICIES.items():
        logger.info("== %s", name)
        if gold:
            logger.info("  manual gold: %s", gold_agreement(gold, policy))
        for run, recs in cascades.items():
            pred = [replay_cascade(r, policy) for r in recs]
            logger.info("  %s: %s", run, _fmt(score([r.gold_label for r in recs], pred)))
        for run, (vrecs, crecs) in paired.items():
            pred = [replay_paired(r, crecs.get(r.id), policy) for r in vrecs]
            logger.info("  %s: %s", run, _fmt(score([r.gold_label for r in vrecs], pred)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
