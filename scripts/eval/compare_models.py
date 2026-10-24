"""Compare candidate models for one role on the same split; print a Pareto table.

  python scripts/eval/compare_models.py --role verifier \
      --candidates gpt-6-luna:none,gpt-6-luna:low,claude-haiku-5-5:low \
      --dataset citation_integrity --split dev.bal --limit 200

Each candidate (model[:effort]) is a normal run_eval run in the role's own
mode (verifier / judge / confirm; the screen is skipped), so every run also
has its own results dir. The table ranks accuracy against $/1k pairs and
p50 latency and marks the non-dominated (Pareto) candidates.
"""

import argparse
import asyncio
import logging
import os
from datetime import datetime

from eval_cli import setup_logging
from eval_metrics import RunSummary
from eval_models import RESULTS_DIR, EvalConfig
from eval_report import pareto_flags, table
from pydantic import BaseModel
from run_eval import run

logger = logging.getLogger("compare_models")


class Candidate(BaseModel):
    model: str
    effort: str | None = None

    @property
    def label(self) -> str:
        return f"{self.model}:{self.effort}" if self.effort else self.model


class CompareRow(BaseModel):
    candidate: str
    run_name: str
    n_scored: int
    n_errors: int
    accuracy: float | None
    macro_f1: float | None
    problem_f1: float | None
    problem_recall: float | None
    cost_per_1k: float | None
    p50_ms: float | None
    p90_ms: float | None
    pareto: bool = False


def parse_candidates(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for part in (p.strip() for p in text.split(",")):
        if part:
            model, _, effort = part.partition(":")
            out.append(Candidate(model=model, effort=effort or None))
    return out


def row_for(candidate: Candidate, summary: RunSummary) -> CompareRow:
    head = summary.headline
    return CompareRow(
        candidate=candidate.label, run_name=summary.meta.run_name, n_scored=head.n_scored,
        n_errors=head.n_errors, accuracy=head.accuracy_6way, macro_f1=head.macro_f1,
        problem_f1=head.problem.f1, problem_recall=head.problem.recall,
        cost_per_1k=head.cost_per_1k_pairs, p50_ms=head.latency_p50_ms,
        p90_ms=head.latency_p90_ms)


def mark_pareto(rows: list[CompareRow]) -> list[CompareRow]:
    points = [(r.accuracy or 0.0, r.cost_per_1k or 0.0, r.p50_ms or 0.0) for r in rows]
    return [r.model_copy(update={"pareto": flag})
            for r, flag in zip(rows, pareto_flags(points), strict=True)]


def _fmt(value: float | None, scale: float = 1.0, digits: int = 3) -> str:
    return "-" if value is None else f"{value * scale:.{digits}f}"


def render(rows: list[CompareRow]) -> list[str]:
    header = ["candidate", "n", "err", "acc6", "macroF1", "probF1", "probRecall", "$/1k",
              "p50 ms", "p90 ms", "pareto"]
    body = [[r.candidate, str(r.n_scored), str(r.n_errors), _fmt(r.accuracy),
             _fmt(r.macro_f1), _fmt(r.problem_f1), _fmt(r.problem_recall),
             _fmt(r.cost_per_1k, digits=2), _fmt(r.p50_ms, digits=0), _fmt(r.p90_ms, digits=0),
             "*" if r.pareto else ""] for r in rows]
    return table(header, body)


async def compare(args: argparse.Namespace) -> list[CompareRow]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rows: list[CompareRow] = []
    env_key = f"REFCHECK_{args.role.upper()}_EFFORT"
    for candidate in parse_candidates(args.candidates):
        os.environ.pop(env_key, None)  # an effort from the previous candidate must not leak
        cfg = EvalConfig(
            dataset=args.dataset, split=args.split, mode=args.role,
            models={args.role: candidate.model},
            efforts={args.role: candidate.effort} if candidate.effort else {},
            limit=args.limit, concurrency=args.concurrency, with_screen=False,
            skip_synthetic=args.skip_synthetic, max_cost=args.max_cost,
            run_name=f"compare-{stamp}-{args.role}-{candidate.label.replace(':', '-')}",
            reuse_cache=args.reuse_cache)
        logger.info("=== %s (%s) ===", candidate.label, args.role)
        rows.append(row_for(candidate, await run(cfg)))
    rows = mark_pareto(rows)
    out = RESULTS_DIR / f"compare-{stamp}-{args.role}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("[" + ",\n".join(r.model_dump_json() for r in rows) + "]", encoding="utf-8")
    for line in render(rows):
        logger.info("%s", line)
    logger.info("Wrote %s", out)
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--role", required=True, choices=["verifier", "judge", "confirm"])
    p.add_argument("--candidates", required=True, help="model[:effort],model[:effort],...")
    p.add_argument("--dataset", default="smoke")
    p.add_argument("--split", default="dev")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--skip-synthetic", action="store_true")
    p.add_argument("--max-cost", type=float, default=2.0, help="USD cap PER candidate")
    p.add_argument("--reuse-cache", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(compare(parse_args()))
