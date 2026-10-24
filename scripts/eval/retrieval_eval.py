"""Gold-evidence retrieval eval: V5 packs (BM25 / hybrid) vs the old section_finder.

For every item with gold evidence, reports hit@3 / hit@5 (a gold sentence inside
one of the top-k ranked units; "A+" variants also count the always-included
abstract), recall of gold sentences inside the standard (3k) and expanded (8k)
packs, and pack size in estimated tokens (len/4).

Run: python scripts/eval/retrieval_eval.py [--limit N] [--no-hybrid] [--query claim+context]
"""

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from rapidfuzz import fuzz
from retrieval_eval_baseline import old_context, ranked_paragraphs

from refcheck.llm.cost_tracker import CostTracker
from refcheck.stages.verify_claims.retrieval_pack import assemble_pack
from refcheck.stages.verify_claims.retriever import (
    EXPANDED_PACK_TOKENS,
    EXPANDED_TOP_N,
    STANDARD_PACK_TOKENS,
    clean_query,
    rank_units,
)
from refcheck.stages.verify_claims.source_document import build_source_document
from refcheck.stages.verify_claims.source_models import SourceDocument, estimate_tokens

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = Path.home() / ".refcheck" / "eval" / "citation_integrity.dev.bal.jsonl"
logger = logging.getLogger("retrieval_eval")


class EvalItem(BaseModel):
    """The dataset fields this eval reads."""

    id: str
    claim: str
    context: str | None = None
    source_id: str
    source_text: str
    source_abstract: str | None = None
    gold_evidence: list[str]


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _found(gold: str, unit: str) -> bool:
    g, u = _norm(gold), _norm(unit)
    if not g or not u:
        return False
    return g in u or (len(g) <= len(u) and fuzz.partial_ratio(g, u) >= 90)


def _hit(golds: list[str], units: list[str]) -> float:
    return float(any(_found(g, u) for g in golds for u in units))


def _recall(golds: list[str], text: str) -> float:
    return sum(_found(g, text) for g in golds) / len(golds)


async def _eval_new(item: EvalItem, doc: SourceDocument, query: str,
                    hybrid: bool, tracker: CostTracker) -> dict[str, float]:
    golds = item.gold_evidence
    ranking = await rank_units(query, doc, 30, hybrid, tracker)
    units = [doc.chunks[i].text for i, _ in ranking.ranked]
    abstract = [doc.abstract_chunk.text] if doc.abstract_chunk else []
    pack = assemble_pack(doc, ranking.ranked, STANDARD_PACK_TOKENS, "eval")
    wide = await rank_units(query, doc, EXPANDED_TOP_N, hybrid, tracker)
    big = assemble_pack(doc, wide.ranked, EXPANDED_PACK_TOKENS, "eval")
    # Same token budget the old section_finder spent on this item (fair comparison).
    old_tokens = estimate_tokens("\n\n".join(old_context(query, item.source_text)))
    matched = assemble_pack(doc, ranking.ranked, max(old_tokens, 400), "eval")
    return {
        "hit@3": _hit(golds, units[:3]), "hit@5": _hit(golds, units[:5]),
        "A+hit@3": _hit(golds, abstract + units[:3]),
        "A+hit@5": _hit(golds, abstract + units[:5]),
        "hit@pack": _hit(golds, [pack.joined_text]),
        "recall@pack": _recall(golds, pack.joined_text), "pack_tokens": pack.total_tokens,
        "recall@old_budget": _recall(golds, matched.joined_text),
        "old_budget_tokens": matched.total_tokens,
        "recall@expanded": _recall(golds, big.joined_text), "expanded_tokens": big.total_tokens,
        "used_embeddings": float(ranking.used_embeddings),
    }


def _eval_old(item: EvalItem, query: str) -> dict[str, float]:
    golds = item.gold_evidence
    paragraphs = ranked_paragraphs(query, item.source_text)
    context = "\n\n".join(old_context(query, item.source_text))
    return {
        "hit@3": _hit(golds, paragraphs[:3]), "hit@5": _hit(golds, paragraphs[:5]),
        "top5_tokens": float(sum(estimate_tokens(p) for p in paragraphs[:5])),
        "hit@pack": _hit(golds, [context]), "recall@pack": _recall(golds, context),
        "pack_tokens": float(estimate_tokens(context)),
    }


def _mean(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = rows[0].keys() if rows else []
    return {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in keys}


def _query(item: EvalItem, mode: str) -> str:
    claim = clean_query(item.claim)
    return f"{claim} {clean_query(item.context or '')}" if mode == "claim+context" else claim


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-hybrid", action="store_true")
    parser.add_argument("--query", choices=["claim", "claim+context"], default="claim")
    parser.add_argument("--abstract-field", action="store_true",
                        help="pass the row's source_abstract as the reference abstract")
    parser.add_argument("--max-cost", type=float, default=0.5)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


async def main() -> None:
    args = _args()
    load_dotenv(REPO / ".env")
    lines = args.dataset.read_text(encoding="utf-8").splitlines()
    items = [EvalItem.model_validate_json(x) for x in lines if x.strip()]
    items = [it for it in items if it.gold_evidence][: args.limit or None]
    docs: dict[str, SourceDocument] = {}
    for i, item in enumerate(items):
        if item.source_id not in docs:
            abstract = item.source_abstract if args.abstract_field else None
            docs[item.source_id] = build_source_document(i, item.source_text, abstract)
    tracker = CostTracker(max_cost=args.max_cost)
    sem = asyncio.Semaphore(16)

    async def one(item: EvalItem, hybrid: bool) -> dict[str, float]:
        async with sem:
            return await _eval_new(item, docs[item.source_id], _query(item, args.query),
                                   hybrid, tracker)

    report: dict[str, object] = {"dataset": str(args.dataset), "n_items": len(items),
                                 "n_docs": len(docs), "query": args.query}
    report["old_section_finder"] = _mean([_eval_old(it, _query(it, args.query)) for it in items])
    report["bm25"] = _mean(await asyncio.gather(*(one(it, False) for it in items)))
    if not args.no_hybrid:
        report["hybrid"] = _mean(await asyncio.gather(*(one(it, True) for it in items)))
    report["embedding_cost_usd"] = round(tracker.total_cost, 4)
    text = json.dumps(report, indent=2)
    logger.info("%s", text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("LiteLLM", "litellm", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(main())
