"""Gold manuscript rows (refcheck_v49_gold) -> the exact production inputs.

Unlike the text datasets, a gold row points at the reference's real PDF. The
source is loaded with the production code (`apply_identity_checks` of the
resolve stage, then `resolve_source`: cover-sheet removal, OCR, supplement /
scan detection, abstract fallback, identity mismatch -> abstract, an abstract
too short to judge -> cannot_verify), the claim carries the manuscript's
cited_for / co_cited_count / paragraph / section (a figure credit's cited_for
becomes the legend panel it closes, as in production: eval_credit), the
co-cited references of the sentence (co_cited_refs: number, title and, when
the gold has it, abstract) reach the verifier like in production, and the
retrieval query is the production `focus_query`. A reference without a usable
source short-circuits to cannot_verify with no LLM call, as in
verifier._verify_single.
"""

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path

from eval_credit import gold_panel_claim
from eval_models import EvalItem, ItemRecord, Mode, SourceMode
from eval_parity import gold_row_cited_for
from eval_records import item_record
from gold_models import GoldRow

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.identity_check import apply_identity_checks
from refcheck.stages.verify_claims.cascade import focus_query
from refcheck.stages.verify_claims.cocited import MAX_COCITED, CoCitedRef, co_cited_ref
from refcheck.stages.verify_claims.retriever import clean_query
from refcheck.stages.verify_claims.source_document import build_abstract_document
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import ResolvedSource, resolve_source

logger = logging.getLogger(__name__)


def is_gold_row(raw: dict[str, object]) -> bool:
    return "gold_source" in raw and "source_text" not in raw


def gold_item(row: GoldRow) -> EvalItem:
    """The gold row as an EvalItem (source loaded later from row.pdf_path)."""
    return EvalItem(
        id=row.id, claim=row.claim, context=row.paragraph, claim_raw=row.sentence,
        source_id=f"ref{row.ref}", source_title=row.ref_title, source_text="",
        source_type="reference", source_abstract=row.abstract,
        gold_label=row.gold_label,  # type: ignore[arg-type]  # excluded rows never load
        gold_binary=row.gold_binary, fine_label=row.gold_partial_type,
        dataset=row.dataset, split=row.split, gold_row=row,
        gold_partial_type=row.gold_partial_type, tool_misread_type=row.tool_misread_type,
        gold_secondary_types=list(row.secondary_types),
        gold_confidence=row.gold_confidence, gold_source=row.gold_source)


def gold_claim(row: GoldRow, claim_id: int) -> Claim:
    """The row's Claim; a figure credit is judged on its legend panel (eval_credit)."""
    return gold_panel_claim(row, Claim(
        id=claim_id, manuscript_text=row.sentence, extracted_claim=row.claim,
        paragraph_text=row.paragraph, claim_type=row.claim_type,  # type: ignore[arg-type]
        reference_ids=[row.ref], section_heading=row.section,
        co_cited_count=max(1, row.co_cited_count), cited_for=gold_row_cited_for(row),
        claim_quality="fragment" if row.claim_quality == "fragment" else "ok"))


def gold_co_cited(row: GoldRow) -> list[CoCitedRef]:
    """The other references of the row's sentence (abstract when the gold row has one)."""
    refs = [co_cited_ref(c.ref, c.title, c.abstract)
            for c in row.co_cited_refs if c.ref != row.ref]
    return refs[:MAX_COCITED]


def gold_reference(row: GoldRow) -> Reference:
    status = row.identity_status if row.identity_status in ("verified", "unverified",
                                                             "mismatch") else "unverified"
    return Reference(
        id=row.ref, title=row.ref_title, authors=row.ref_authors, year=row.ref_year,
        doi=row.doi, pdf_path=Path(row.pdf_path) if row.pdf_path else None,
        source_status="found" if row.pdf_path or row.abstract else "not_found",
        abstract_text=row.abstract, abstract_source=row.abstract_source,
        identity_status=status)  # type: ignore[arg-type]


def production_query(claim: Claim) -> str:
    """verifier._build_contexts: the cited-for clause first, then the whole sentence."""
    return focus_query(claim, clean_query(claim.extracted_claim or claim.manuscript_text))


async def _resolve(ref: Reference, source: SourceMode) -> ResolvedSource:
    if source == "abstract":  # ablation: abstract only, like a reference without a PDF
        doc = build_abstract_document(ref.id, ref.abstract_text or "")
        return ResolvedSource(doc=doc, coverage="abstract_only", quality_score=0.5) \
            if doc.chunks else ResolvedSource(cannot_verify_reason="no_abstract",
                                              detail="No abstract available")
    try:
        return await resolve_source(ref)
    except Exception as exc:  # same guard as verifier._resolve_sources
        logger.exception("Could not load source for ref %d", ref.id)
        return ResolvedSource(coverage="full_text", cannot_verify_reason="pdf_scanned",
                              detail=f"PDF could not be read ({type(exc).__name__})")


async def resolve_gold_sources(items: Iterable[EvalItem], source: SourceMode,
                               recheck_identity: bool = True,
                               ) -> dict[str, ResolvedSource]:
    """source_id -> the production ResolvedSource of each gold reference."""
    refs: dict[str, Reference] = {}
    for item in items:
        if item.gold_row is not None and item.source_id not in refs:
            refs[item.source_id] = gold_reference(item.gold_row)
    return await resolve_references(refs, source, recheck_identity)


async def resolve_references(refs: dict[str, Reference], source: SourceMode,
                             recheck_identity: bool = True) -> dict[str, ResolvedSource]:
    """key -> the production ResolvedSource of each reference (identity re-checked first)."""
    if recheck_identity and source != "abstract":
        checked = await asyncio.to_thread(apply_identity_checks, list(refs.values()))
        for key, ref in zip(list(refs), checked, strict=True):
            if ref.identity_status != refs[key].identity_status:
                logger.info("ref %d: identity %s (recorded %s)", ref.id, ref.identity_status,
                            refs[key].identity_status)
            refs[key] = ref
    keys = list(refs)
    resolved = await asyncio.gather(*(_resolve(refs[k], source) for k in keys))
    return dict(zip(keys, resolved, strict=True))


def split_sources(resolved: dict[str, ResolvedSource],
                  ) -> tuple[dict[str, SourceDocument], dict[str, ResolvedSource]]:
    """(usable documents, references without a usable source)."""
    docs = {k: r.doc for k, r in resolved.items() if r.doc is not None}
    return docs, {k: r for k, r in resolved.items() if r.doc is None}


def unsourced_record(item: EvalItem, src: ResolvedSource, mode: Mode) -> ItemRecord:
    """cannot_verify without any LLM call (verifier._verify_single short-circuit)."""
    return item_record(item, mode, coverage=src.coverage, verdict="cannot_verify",
                       cannot_verify_reason=src.cannot_verify_reason, decided_by="none")
