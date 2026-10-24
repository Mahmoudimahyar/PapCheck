"""Eval rows -> production objects (Claim, Reference, SourceDocument, PairContext).

Sources are built in memory from the row's text with the SAME code the app
uses for PDFs (`build_source_document` / `build_abstract_document`) and
packs come from the production retriever (`retrieve`, BM25 + embeddings). Gold rows
(eval_gold) load the real PDF and use the production claim fields and query.
"""

import hashlib
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path

from eval_gold import (
    gold_claim,
    gold_co_cited,
    gold_item,
    gold_reference,
    is_gold_row,
    production_query,
)
from eval_models import EVAL_DIR, EvalItem, SourceMode
from eval_parity import ci_cited_for
from gold_models import GoldRow

import refcheck
from refcheck.llm.cost_tracker import CostTracker
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.cascade import focus_query
from refcheck.stages.verify_claims.retriever import bm25_pack, expanded_pack, retrieve
from refcheck.stages.verify_claims.screen import screen_questions
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import PairContext, build_pair_context

logger = logging.getLogger(__name__)
PROMPTS_DIR = Path(refcheck.__file__).resolve().parent / "prompts"
_OTHER_REF_RE = re.compile(r"(?<!\w)#(?!\w)")  # Citation-Integrity: other references
_MULTI_CIT = "<|multi_cit|>"  # the cited reference shares its bracket with others


def resolve_dataset(dataset: str, split: str) -> Path:
    """A JSONL path from a path, "smoke", or <dataset> + split (dev/test/dev.bal/...)."""
    direct = Path(dataset).expanduser()
    if direct.suffix == ".jsonl" and direct.is_file():
        return direct
    if dataset == "smoke":
        return EVAL_DIR / "smoke.jsonl"
    names = [f"{dataset}.jsonl"] if split in ("", "all") else \
        [f"{dataset}.{split}.jsonl", f"{dataset}_{split}.jsonl"]
    for name in names:
        if (EVAL_DIR / name).is_file():
            return EVAL_DIR / name
    raise FileNotFoundError(f"No eval file for dataset={dataset!r} split={split!r} in "
                            f"{EVAL_DIR} (tried {', '.join(names)})")


def load_items(path: Path, limit: int = 0, skip_synthetic: bool = False) -> list[EvalItem]:
    """Rows in file order (first `limit` after the synthetic filter).

    Gold manuscript rows are converted to EvalItems; excluded ones (no valid
    gold) are skipped.
    """
    items: list[EvalItem] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            if '"gold_source"' in line and is_gold_row(json.loads(line)):
                row = GoldRow.model_validate_json(line)
                if row.exclude:
                    continue
                item = gold_item(row)
            else:
                item = EvalItem.model_validate_json(line)
            if skip_synthetic and item.synthetic:
                continue
            items.append(item)
            if limit and len(items) >= limit:
                break
    return items


def co_cited_count(item: EvalItem) -> int:
    """References cited together with this one (from '#' placeholders / multi-cit marker)."""
    others = len(_OTHER_REF_RE.findall(item.claim))
    if _MULTI_CIT in item.claim_raw:
        others = max(others, 1)
    return 1 + others


def item_claim(item: EvalItem, claim_id: int, ref_id: int) -> Claim:
    """The row's claim as a manuscript Claim (context = citing paragraph)."""
    if item.gold_row is not None:
        return gold_claim(item.gold_row, claim_id)
    return Claim(id=claim_id, extracted_claim=item.claim, manuscript_text=item.claim,
                 paragraph_text=item.context, reference_ids=[ref_id],
                 co_cited_count=co_cited_count(item), cited_for=ci_cited_for(item))


def item_reference(item: EvalItem, ref_id: int) -> Reference:
    if item.gold_row is not None:
        return gold_reference(item.gold_row)
    abstract = item.source_abstract or (item.source_text if item.source_type == "abstract"
                                        else None)
    return Reference(id=ref_id, title=item.source_title, abstract_text=abstract,
                     abstract_source="eval" if abstract else None)


def build_document(item: EvalItem, ref_id: int, source: SourceMode) -> SourceDocument:
    """In-memory source document, built by the production source code.

    auto: abstract-only rows (SciFact) -> abstract-only document, full-text
    rows -> full text with the row's abstract as unit "A" (like a PubMed
    abstract on a reference with a PDF). retrieved: the dataset's BM25
    excerpt as the "full text". abstract: abstract only.
    """
    if source == "abstract" or (source == "auto" and item.source_type == "abstract"):
        text = item.source_abstract or item.source_text
        return build_abstract_document(ref_id, text)
    text = item.source_text
    if source == "retrieved" and item.source_retrieved:
        text = item.source_retrieved
    abstract = item.source_abstract if item.source_type != "abstract" else None
    return build_source_document(ref_id, text, abstract_text=abstract)


def build_documents(items: Iterable[EvalItem], source: SourceMode,
                    ) -> tuple[dict[str, SourceDocument], dict[str, int]]:
    """One document (and reference id) per distinct source_id."""
    docs: dict[str, SourceDocument] = {}
    ref_ids: dict[str, int] = {}
    for item in items:
        if item.source_id not in docs:
            ref_ids[item.source_id] = len(ref_ids) + 1
            docs[item.source_id] = build_document(item, ref_ids[item.source_id], source)
    return docs, ref_ids


async def build_context(item: EvalItem, claim_id: int, ref_id: int, doc: SourceDocument,
                        use_embeddings: bool, tracker: CostTracker | None) -> PairContext:
    """Standard pack + pair context, exactly as verifier._build_contexts does."""
    claim = item_claim(item, claim_id, ref_id)
    query = production_query(claim) if item.gold_row is not None \
        else claim.extracted_claim or claim.manuscript_text
    try:
        pack = await retrieve(query, doc, use_embeddings=use_embeddings, cost_tracker=tracker)
    except Exception:  # same fallback as production: deterministic BM25 pack
        logger.exception("Retrieval failed for %s; using the BM25 pack", item.id)
        pack = bm25_pack(query, doc)
    co_cited = gold_co_cited(item.gold_row) if item.gold_row is not None else []
    ctx = build_pair_context(claim, item_reference(item, ref_id), doc, pack, co_cited)
    ctx.use_embeddings = use_embeddings  # the evidence re-check retrieves like the pack
    if not use_embeddings and doc.coverage == "full_text":
        # cascade.ensure_expanded would embed; BM25-only runs pre-fill it (same query:
        # focus_query == claim_text when the claim has no narrower cited_for).
        ctx.expanded = await expanded_pack(focus_query(ctx.claim, ctx.claim_text), doc,
                                           use_embeddings=False)
    return ctx


def screen_template_hash() -> str:
    """Hash of the screen input template + the six predicate questions.

    A calibrated t_accept is only valid for the exact questions and input
    format it was measured with.
    """
    questions = [q.model_dump() for q in screen_questions()]
    digest = hashlib.sha256(json.dumps(questions, sort_keys=True).encode("utf-8"))
    digest.update((PROMPTS_DIR / "screen_claim.md").read_bytes())
    return digest.hexdigest()[:16]


# Files each prompt is rendered from: the verifier rubric includes the taxonomy partial built
# from partial_taxonomy.json, and the judge includes the verifier template. Strict clearance
# (REFCHECK_STRICT_CLEARANCE=on) renders the *_strict.md files under the same names.
def _prompt_parts(strict: bool) -> dict[str, tuple[str, ...]]:
    sfx = "_strict" if strict else ""
    taxonomy = (f"verify_taxonomy{sfx}.md", "partial_taxonomy.json")
    return {"screen_claim": ("screen_claim.md",),
            "verify_claim": (f"verify_claim{sfx}.md", *taxonomy),
            "judge_claim": (f"judge_claim{sfx}.md", f"verify_claim{sfx}.md", *taxonomy)}


def prompt_hashes(strict: bool = False) -> dict[str, str]:
    """One hash per prompt over every file it is rendered from (default: V5.5 files)."""
    out: dict[str, str] = {}
    for name, parts in _prompt_parts(strict).items():
        digest = hashlib.sha256()
        for part in parts:
            path = PROMPTS_DIR / part
            digest.update(path.read_bytes() if path.is_file() else b"")
        out[name] = digest.hexdigest()[:16]
    return out
