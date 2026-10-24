"""Command-line parsing for run_eval.py (flags -> EvalConfig)."""

import argparse
import logging
from pathlib import Path

from eval_models import RESULTS_DIR, EvalConfig

ROLES = ("screen", "verifier", "judge", "confirm", "adjudicator", "utility", "embedding")
MODES = ("screen", "verifier", "judge", "confirm", "cascade")
LIVE_ROLES = ("verifier", "judge", "confirm", "adjudicator", "utility")  # chat roles only


def csv_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def live_roles(value: str) -> list[str]:
    """--live-roles: chat roles only (embeddings and the screen stay cache-only)."""
    roles = csv_list(value)
    bad = [r for r in roles if r not in LIVE_ROLES]
    if bad or not roles:
        raise SystemExit(f"--live-roles {value!r}: chat roles only ({', '.join(LIVE_ROLES)})")
    return roles


def parse_pairs(values: list[str], mode: str, flag: str) -> dict[str, str]:
    """"role=value" pairs; a bare value applies to the mode's own role."""
    pairs: dict[str, str] = {}
    for value in values:
        role, sep, rest = value.partition("=")
        if not sep:
            if mode == "cascade":
                raise SystemExit(f"{flag} {value}: use role=value in cascade mode")
            role, rest = mode, value
        if role not in ROLES:
            raise SystemExit(f"{flag} {value}: unknown role {role!r}")
        if not rest.strip():
            raise SystemExit(f"{flag} {value}: empty value")
        pairs[role] = rest.strip()
    return pairs


def parse_args(argv: list[str] | None = None, description: str | None = None) -> EvalConfig:
    p = argparse.ArgumentParser(description=description,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="smoke",
                   help="smoke | scifact | citation_integrity | refcheck_v49_gold "
                        "(manuscript gold: real PDFs, production loader) | path to a .jsonl")
    p.add_argument("--split", default="dev", help="dev | test | dev.bal | test.bal | all")
    p.add_argument("--mode", default="cascade", choices=MODES)
    p.add_argument("--model", action="append", default=[],
                   help="role=model_id (repeatable; bare model_id = the mode's role)")
    p.add_argument("--effort", action="append", default=[],
                   help="role=none|low|medium|high (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="first N items (0 = all)")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--run-name", default="")
    p.add_argument("--source", default="auto", choices=["auto", "full", "retrieved", "abstract"],
                   help="auto: abstract rows -> abstract-only doc, others -> full text")
    p.add_argument("--no-embeddings", action="store_true", help="BM25-only retrieval")
    p.add_argument("--no-screen", action="store_true", help="verifier mode: skip the screen")
    p.add_argument("--skip-synthetic", action="store_true")
    p.add_argument("--t-accept", type=float, default=None, help="override the screen threshold")
    p.add_argument("--max-cost", type=float, default=5.0, help="hard USD cap for the run")
    p.add_argument("--reuse-cache", action="store_true",
                   help="use the app's LLM cache (cheap re-runs; cost/latency understated)")
    p.add_argument("--adjudicate", choices=["on", "off"], default=None,
                   help="element adjudicator in cascade mode (default: REFCHECK_ADJUDICATE, on)")
    p.add_argument("--cocited-union", choices=["on", "off"], default=None,
                   help="co-cited full-text union check after the adjudicator "
                        "(default: REFCHECK_COCITED_UNION, on)")
    p.add_argument("--strict-clearance", choices=["on", "off"], default=None,
                   help="V5.6 strict clearance prompts/schema/audit (default: "
                        "REFCHECK_STRICT_CLEARANCE, off = V5.5 verifier behaviour)")
    p.add_argument("--session", default="",
                   help="DB session (read-only) for co-cited sources no gold row has "
                        "(default: each gold row's session_id)")
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    p.add_argument("--screen-from", default="",
                   help="reuse the screen answers recorded per item by this run (no call)")
    p.add_argument("--offline", action="store_true",
                   help="cache-only: keys blanked, no call is sent; pairs with an uncached "
                        "call are scored from --fallback-from (implies --reuse-cache)")
    p.add_argument("--fallback-from", default="",
                   help="--offline: run whose verdicts score needs_call pairs "
                        "(default: --screen-from)")
    p.add_argument("--live-roles", default="",
                   help="--offline: chat calls of these roles (comma list, e.g. adjudicator) "
                        "may be sent and are cached; everything else stays cache-only")
    p.add_argument("--live-keys", default="",
                   help="--live-roles: the only key env vars kept (comma list, default: all "
                        "of the live roles' providers), e.g. ANTHROPIC_API_KEY_BACKUP")
    p.add_argument("--live-check", action="store_true",
                   help="--live-roles dry check: keys blanked, each live call is recorded "
                        "(live-chat:<role>) and never sent")
    p.add_argument("--embedding-miss", choices=["miss", "bm25"], default="miss",
                   help="--offline: an uncached embedding makes the pair needs_call (miss) "
                        "or falls back to BM25-only retrieval (bm25, as without OpenAI)")
    a = p.parse_args(argv)
    if a.fallback_from and not a.offline:
        p.error("--fallback-from needs --offline")
    if a.live_roles and not a.offline:
        p.error("--live-roles needs --offline")
    if (a.live_keys or a.live_check) and not a.live_roles:
        p.error("--live-keys / --live-check need --live-roles")
    return EvalConfig(
        dataset=a.dataset, split=a.split, mode=a.mode,
        models=parse_pairs(a.model, a.mode, "--model"),
        efforts=parse_pairs(a.effort, a.mode, "--effort"), limit=a.limit,
        concurrency=a.concurrency, run_name=a.run_name, source=a.source,
        use_embeddings=not a.no_embeddings, with_screen=not a.no_screen,
        skip_synthetic=a.skip_synthetic, t_accept=a.t_accept, max_cost=a.max_cost,
        reuse_cache=a.reuse_cache or a.offline, results_dir=a.results_dir,
        adjudicate=a.adjudicate, cocited_union=a.cocited_union,
        strict_clearance=a.strict_clearance, session=a.session, screen_from=a.screen_from,
        offline=a.offline, fallback_from=a.fallback_from,
        live_roles=live_roles(a.live_roles) if a.live_roles else [],
        live_keys=csv_list(a.live_keys), live_check=a.live_check,
        embedding_miss=a.embedding_miss if a.offline else "miss",
    )


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("LiteLLM", "litellm", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
