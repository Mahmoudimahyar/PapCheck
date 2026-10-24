"""Source preparation for run_eval.py: in-memory documents for dataset rows, the production
loader for manuscript gold rows, and the co-cited sources of the union check."""

import logging
from pathlib import Path

from eval_cocited import resolve_cocited_sources
from eval_data import build_documents, resolve_dataset
from eval_gold import resolve_gold_sources, split_sources
from eval_models import EvalConfig, EvalItem

from refcheck.stages.verify_claims.adjudicate import adjudicate_enabled
from refcheck.stages.verify_claims.cocited_union import cocited_union_enabled
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import ResolvedSource

logger = logging.getLogger("run_eval")
Sources = tuple[dict[str, SourceDocument], dict[str, int], dict[str, ResolvedSource],
                dict[int, SourceDocument]]


def union_on(cfg: EvalConfig) -> bool:
    """The co-cited union check runs in this run (cascade, adjudicator and union on)."""
    return cfg.mode == "cascade" and adjudicate_enabled() and cocited_union_enabled()


def gold_pool_path(cfg: EvalConfig, path: Path) -> Path:
    """All splits of the dataset (co-cited references of other rows), else ``path``."""
    try:
        return resolve_dataset(cfg.dataset, "all")
    except FileNotFoundError:
        return path


async def prepare_sources(items: list[EvalItem], cfg: EvalConfig, path: Path) -> Sources:
    """Documents, reference ids, unsourced gold references and co-cited sources; gold
    rows (and their co-cited references) go through the production source loader."""
    docs, ref_ids = build_documents([i for i in items if i.gold_row is None], cfg.source)
    gold = [i for i in items if i.gold_row is not None]
    if not gold:
        return docs, ref_ids, {}, {}
    resolved = await resolve_gold_sources(gold, cfg.source)
    gold_docs, unsourced = split_sources(resolved)
    cocited = await resolve_cocited_sources(gold, resolved, cfg.source, gold_pool_path(
        cfg, path), cfg.session) if union_on(cfg) else {}
    docs.update(gold_docs)
    ref_ids.update({i.source_id: i.gold_row.ref for i in gold if i.gold_row is not None})
    if unsourced:
        logger.info("%d gold references without a usable source: %s", len(unsourced),
                    {k: v.cannot_verify_reason for k, v in unsourced.items()})
    return docs, ref_ids, unsourced, cocited
