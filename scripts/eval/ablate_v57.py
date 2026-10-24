"""V5.7 proposal ablation: --offline replays with one proposal switched off at a time.

  python scripts/eval/ablate_v57.py --screen-from gold-v56-off-all
  python scripts/eval/ablate_v57.py --screen-from gold-v56-off-all --proposals 3,5 \
      --jobs 2 -- --concurrency 4

Runs run_eval.py --offline (cache-only, keys blanked, $0) once with every proposal on
(REFCHECK_V57_DISABLE="") and once per proposal with REFCHECK_V57_DISABLE=<n>, as
<prefix>-all-on / <prefix>-no<n> in --results-dir, then prints per split (dev, test, all)
the delta table of eval_ablation (missed partial, over-harsh, 3-way, type acc, review-tier
recall, needs_call) against all-on and writes <prefix>.json next to the runs. Arguments
after "--" go to run_eval.py unchanged. --reuse-runs rescores runs that already exist.
Pairs whose new calls miss the cache (proposals that add a call or change a request) are
scored from --fallback-from (default --screen-from) and counted in needs_call.
V5.8 experimental proposals (v57.OPT_IN, off by default) are measured the other way round:
--opt-in 20,24 adds a with<n> run per number with REFCHECK_V57_ENABLE=<n>.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eval_ablation import SplitMetrics, delta_table, metrics_by_split
from eval_cache import key_env_names
from eval_cli import setup_logging
from eval_models import RESULTS_DIR
from eval_recorded import load_run

logger = logging.getLogger("ablate_v57")
RUN_EVAL = Path(__file__).resolve().with_name("run_eval.py")
DISABLE_ENV = "REFCHECK_V57_DISABLE"
ENABLE_ENV = "REFCHECK_V57_ENABLE"
# Default-on proposals (#12 is eval-only; #14 / #15 are experimental, default off);
# 21-23, 26-28, 30: the default-on V5.8 round-2 fixes (v57.py; #30 adds adjudicator calls).
DEFAULT_PROPOSALS = "1,2,3,4,5,6,7,8,9,10,11,13,16,21,22,23,26,27,28,30"
# The off-by-default V5.8 proposals (v57.OPT_IN; 29 / 31 add adjudicator calls).
DEFAULT_OPT_IN = "20,24,25,29,31,32,33"
BASE = "all-on"


def _numbers(text: str) -> list[int]:
    return [int(p) for p in text.split(",") if p.strip()]


def configs(proposals: str, opt_in: str = "") -> dict[str, tuple[str, str]]:
    """Config name -> (REFCHECK_V57_DISABLE, REFCHECK_V57_ENABLE) (all-on first)."""
    return {BASE: ("", ""), **{f"no{n}": (str(n), "") for n in _numbers(proposals)},
            **{f"with{n}": ("", str(n)) for n in _numbers(opt_in)}}


def child_env(disable: str, enable: str = "") -> dict[str, str]:
    """The run's environment: every API key blanked, the ablation switches set."""
    env = dict(os.environ)
    env.update({name: "" for name in key_env_names()})
    env[DISABLE_ENV] = disable
    env[ENABLE_ENV] = enable
    return env


def command(args: argparse.Namespace, name: str, extra: list[str]) -> list[str]:
    cmd = [sys.executable, str(RUN_EVAL), "--dataset", args.dataset, "--split", args.split,
           "--mode", "cascade", "--offline", "--screen-from", args.screen_from,
           "--run-name", name, "--results-dir", str(args.results_dir)]
    if args.fallback_from:
        cmd += ["--fallback-from", args.fallback_from]
    return cmd + extra


def run_one(args: argparse.Namespace, name: str, switches: tuple[str, str],
            extra: list[str]) -> None:
    """One offline replay (skipped with --reuse-runs when its records exist)."""
    if args.reuse_runs and (args.results_dir / name / "summary.json").is_file():
        logger.info("%s: reusing the existing run", name)
        return
    disable, enable = switches
    logger.info("%s: %s=%r %s=%r", name, DISABLE_ENV, disable, ENABLE_ENV, enable)
    log = args.results_dir / f"{name}.log"
    args.results_dir.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        done = subprocess.run(command(args, name, extra), env=child_env(disable, enable),
                              stdout=handle, stderr=subprocess.STDOUT, check=False)
    if done.returncode != 0:
        raise SystemExit(f"{name} failed (exit {done.returncode}); see {log}")


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Own flags, and the run_eval.py flags after "--"."""
    cut = argv.index("--") if "--" in argv else len(argv)
    own, extra = argv[:cut], argv[cut + 1:]
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--screen-from", required=True, help="run with the recorded screens")
    p.add_argument("--fallback-from", default="", help="default: --screen-from")
    p.add_argument("--dataset", default="refcheck_v49_gold")
    p.add_argument("--split", default="all")
    p.add_argument("--proposals", default=DEFAULT_PROPOSALS)
    p.add_argument("--opt-in", default=DEFAULT_OPT_IN, help="off-by-default proposals")
    p.add_argument("--prefix", default="ablate-v57")
    p.add_argument("--jobs", type=int, default=1, help="replays run in parallel")
    p.add_argument("--reuse-runs", action="store_true")
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return p.parse_args(own), extra


def main(argv: list[str] | None = None) -> dict[str, dict[str, SplitMetrics]]:
    args, extra = parse_args(list(sys.argv[1:] if argv is None else argv))
    names = {f"{args.prefix}-{k}": v for k, v in configs(args.proposals, args.opt_in).items()}
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(lambda kv: run_one(args, kv[0], kv[1], extra), names.items()))
    results = {name.removeprefix(f"{args.prefix}-"): metrics_by_split(
        list(load_run(args.results_dir, name).values())) for name in names}
    for line in delta_table(results, BASE):
        logger.info("%s", line)
    out = args.results_dir / f"{args.prefix}.json"
    out.write_text(json.dumps({k: {s: m.model_dump() for s, m in v.items()}
                               for k, v in results.items()}, indent=2), encoding="utf-8")
    logger.info("Ablation table: %s", out)
    return results


if __name__ == "__main__":
    setup_logging()
    main()
