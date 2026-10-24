"""Run the V5 verification cascade (or one of its layers) on a labelled eval set.

  python scripts/eval/run_eval.py --dataset smoke --mode cascade
  python scripts/eval/run_eval.py --dataset citation_integrity --split dev --mode screen
  python scripts/eval/run_eval.py --dataset scifact --split dev.bal --mode verifier \
      --model verifier=claude-haiku-5-5 --effort verifier=low --limit 100
  python scripts/eval/run_eval.py --dataset refcheck_v49_gold --split dev --mode cascade
  python scripts/eval/run_eval.py --dataset refcheck_v49_gold --limit 5 --dry-run

Modes: screen | verifier | judge | confirm | cascade. Writes
~/.refcheck/eval/results/<run_name>/items.jsonl (one ItemRecord per pair) and
summary.json (RunSummary). LLM responses use a throw-away cache unless
--reuse-cache, so cost and latency are real. Manuscript gold rows
(refcheck_v49_gold) load each reference's real PDF with the production loader
(eval_gold); a reference without a usable source makes no LLM call.
--dry-run: no API call at all (canned layer answers, BM25 only, no screen;
eval_dry_run) to smoke-test the whole path; its verdicts are meaningless.
Element adjudicator (cascade): --adjudicate on|off (default REFCHECK_ADJUDICATE, on);
its model / effort: --model adjudicator=gpt-6-luna --effort adjudicator=low. The co-cited
full-text union check after it: --cocited-union on|off (default REFCHECK_COCITED_UNION,
on); co-cited sources come from other gold rows, else the DB read-only (--session,
default each row's session_id; eval_cocited). Verifier clearance: --strict-clearance on|off
(default REFCHECK_STRICT_CLEARANCE, off = the V5.5 prompts/schema; on = V5.6 strict).
Replays: --screen-from <run> reuses that run's recorded screen answer per item (no
Decisions call). --offline is cache-only (eval_cache): keys are blanked, nothing is sent;
a pair with an uncached call is marked needs_call and scored with its verdict from
--fallback-from <run> (default: the --screen-from run); summary.json reports the calls and
estimated $ a live run would need. --live-roles adjudicator (with --offline) sends that
role's uncached chat calls (cached afterwards; eval_live), keeping only --live-keys and
capping the spend at --max-cost; --live-check records those calls instead of sending them.
--embedding-miss bm25 (offline): an uncached embedding means BM25-only retrieval, not needs_call.
REFCHECK_V57_DISABLE / REFCHECK_V57_ENABLE are recorded in the meta.
  python scripts/eval/run_eval.py --dataset refcheck_v49_gold --split all --offline \
      --screen-from gold-v56-off-all --run-name gold-v57-offline
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from eval_cache import SETUP_MISSES, cache_scope, check_offline, item_misses, offline_scope
from eval_cli import setup_logging
from eval_data import load_items, prompt_hashes, resolve_dataset
from eval_data import screen_template_hash as screen_hash
from eval_dry_run import dry_run_roles, dry_run_scope, parse_cli
from eval_gold import unsourced_record
from eval_live import chat_stand_in, live_plan, preflight_live, tracker_cap
from eval_metrics import RunSummary, summarize
from eval_models import EvalConfig, EvalItem, ItemRecord, RunMeta, ScreenRecord
from eval_parity import fresh_screens
from eval_recorded import fallback_record, load_run, offline_report, recorded_screens
from eval_report import summary_lines
from eval_roles import apply_overrides, check_roles, offline_roles
from eval_runner import evaluate_item, wants_screen
from eval_sources import prepare_sources, union_on

from refcheck.llm.cost_tracker import CostTracker
from refcheck.stages.verify_claims.adjudicate import adjudicate_enabled
from refcheck.stages.verify_claims.calibration import ScreenThresholds, load_thresholds
from refcheck.stages.verify_claims.clearance_mode import strict_clearance
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import ResolvedSource

__all__ = ["cache_scope", "prepare_sources", "run", "run_items", "union_on"]
REPO = Path(__file__).resolve().parents[2]
logger = logging.getLogger("run_eval")


async def run_items(items: list[EvalItem], docs: dict[str, SourceDocument],
                    ref_ids: dict[str, int], cfg: EvalConfig, thresholds: ScreenThresholds,
                    tracker: CostTracker, out_path: Path,
                    unsourced: dict[str, ResolvedSource] | None = None,
                    cocited: dict[int, SourceDocument] | None = None,
                    screens: dict[str, ScreenRecord] | None = None,
                    fallback: dict[str, ItemRecord] | None = None) -> list[ItemRecord]:
    """Evaluate all items concurrently; each record is appended to items.jsonl as it ends.
    A pair whose calls missed the cache (--offline) takes its ``fallback`` record."""
    semaphore = asyncio.Semaphore(max(1, cfg.concurrency))
    no_source = unsourced or {}
    done = 0
    with out_path.open("w", encoding="utf-8") as handle:
        async def one(idx: int, item: EvalItem) -> ItemRecord:
            nonlocal done
            async with semaphore:
                misses = item_misses()  # this task's own list (offline_scope fills it)
                if item.source_id in no_source:  # production short-circuit: no LLM call
                    rec = unsourced_record(item, no_source[item.source_id], cfg.mode)
                else:
                    rec = await evaluate_item(item, idx + 1, ref_ids[item.source_id],
                                              docs[item.source_id], cfg, thresholds, tracker,
                                              cocited, screens)
                if misses:
                    rec = fallback_record(rec, (fallback or {}).get(item.id), misses)
            handle.write(rec.model_dump_json() + "\n")
            handle.flush()
            done += 1
            if done % 10 == 0 or done == len(items):
                logger.info("%d/%d items done, $%.4f spent", done, len(items),
                            tracker.total_cost)
            return rec

        return list(await asyncio.gather(*(one(i, it) for i, it in enumerate(items))))


def recorded(cfg: EvalConfig) -> tuple[dict[str, ScreenRecord], dict[str, ItemRecord]]:
    """Recorded screens (--screen-from) and the offline fallback records."""
    screens = recorded_screens(load_run(cfg.results_dir, cfg.screen_from)) \
        if cfg.screen_from else {}
    source = cfg.fallback_from or cfg.screen_from
    fallback = load_run(cfg.results_dir, source) if cfg.offline and source else {}
    return screens, fallback


def run_meta(cfg: EvalConfig, name: str, path: Path, n_items: int, started: str,
             roles: tuple[ScreenThresholds, dict[str, str | None], dict[str, str | None]],
             records: list[ItemRecord], tracker: CostTracker) -> RunMeta:
    thresholds, models, efforts = roles
    costs = tracker.summary()
    return RunMeta(
        run_name=name, mode=cfg.mode, dataset=cfg.dataset, split=cfg.split,
        dataset_path=str(path), n_items=n_items, source=cfg.source,
        use_embeddings=cfg.use_embeddings, concurrency=cfg.concurrency, started_at=started,
        finished_at=datetime.now().isoformat(timespec="seconds"), roles=models,
        efforts=efforts, thresholds={
            "t_accept": thresholds.t_accept, "injection_max": thresholds.injection_max,
            "t_contra": thresholds.t_contra, "t_topic": thresholds.t_topic,
            "enabled": thresholds.enabled, "auto_clear": thresholds.auto_clear,
            "source": thresholds.source},
        screen_template_hash=screen_hash(), prompt_hashes=prompt_hashes(strict_clearance()),
        retrieval_versions=sorted({r.retrieval_version for r in records if r.retrieval_version}),
        reuse_cache=cfg.reuse_cache, dry_run=cfg.dry_run, max_cost=cfg.max_cost,
        adjudicate=cfg.mode == "cascade" and adjudicate_enabled(), cocited_union=union_on(cfg),
        strict_clearance=strict_clearance(), total_cost_usd=costs.total_usd,
        cost_by_role=costs.by_role, cost_by_task=costs.by_task, screen_from=cfg.screen_from,
        offline=cfg.offline, fallback_from=(cfg.fallback_from or cfg.screen_from)
        if cfg.offline else "", v57_disable=os.environ.get("REFCHECK_V57_DISABLE", ""),
        v57_enable=os.environ.get("REFCHECK_V57_ENABLE", ""),
        live_roles=cfg.live_roles, live_check=cfg.live_check, embedding_miss=cfg.embedding_miss)


async def run(cfg: EvalConfig) -> RunSummary:
    """One eval run end to end; returns (and writes) the summary."""
    load_dotenv(REPO / ".env")
    apply_overrides(cfg)
    path = resolve_dataset(cfg.dataset, cfg.split)
    items = load_items(path, cfg.limit, cfg.skip_synthetic)
    name = cfg.run_name or f"{path.stem}-{cfg.mode}-{datetime.now():%Y%m%d-%H%M%S}"
    thresholds = load_thresholds()
    if cfg.t_accept is not None:
        thresholds = thresholds.model_copy(update={"t_accept": cfg.t_accept, "source": "cli"})
    plan = live_plan(cfg)
    if cfg.offline:
        check_offline(cfg, wants_screen(cfg) and thresholds.enabled, plan.keep if plan else ())
    screens, fallback = recorded(cfg)
    screens = fresh_screens(items, screens)  # V5.7 #10/#14 changed cited_for -> re-screen
    out_dir = cfg.results_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)
    tracker = CostTracker(max_cost=tracker_cap(cfg))
    started = datetime.now().isoformat(timespec="seconds")
    with (cache_scope(cfg.reuse_cache or cfg.offline), dry_run_scope(cfg.dry_run),
          offline_scope(cfg.offline, chat_stand_in(plan), cfg.embedding_miss)):
        roles = dry_run_roles(cfg, thresholds) if cfg.dry_run else offline_roles(
            cfg, thresholds) if cfg.offline else await check_roles(cfg, thresholds, tracker)
        await preflight_live(plan, tracker)
        docs, ref_ids, unsourced, cocited = await prepare_sources(items, cfg, path)
        logger.info("%d items, %d sources from %s; mode=%s roles=%s", len(items), len(docs),
                    path, cfg.mode, roles[1])
        records = await run_items(items, docs, ref_ids, cfg, roles[0], tracker,
                                  out_dir / "items.jsonl", unsourced, cocited, screens,
                                  fallback)
    meta = run_meta(cfg, name, path, len(items), started, roles, records, tracker)
    summary = summarize(records, meta)
    if cfg.offline:
        summary.offline = offline_report(records, SETUP_MISSES)
    (out_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    for line in summary_lines(summary):
        logger.info("%s", line)
    logger.info("Results: %s", out_dir)
    return summary


if __name__ == "__main__":
    setup_logging()
    asyncio.run(run(parse_cli(sys.argv[1:], description=__doc__)))
