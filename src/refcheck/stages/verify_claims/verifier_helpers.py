"""Per-pair context, source resolution and small result helpers for verification."""

import logging
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.cocited import CoCitedRef, co_cited_documents
from refcheck.stages.verify_claims.credit import panel_claim, panel_of, without_panel
from refcheck.stages.verify_claims.retriever import EvidencePack, clean_query
from refcheck.stages.verify_claims.source_document import SourceDocument
from refcheck.stages.verify_claims.source_fallback import annotate_source_fallback
from refcheck.stages.verify_claims.source_resolve import (
    ResolvedSource,
    SourceCoverage,
    resolve_source,
)
from refcheck.stages.verify_claims.source_windows import split_sentences

__all__ = [
    "PairContext", "ResolvedSource", "annotate_source_fallback", "apply_claim_type_behavior",
    "build_pair_context", "cannot_verify", "dedupe_quotes", "local_paragraph",
    "previous_sentence", "resolve_source",
]

logger = logging.getLogger(__name__)

PARAGRAPH_MAX_CHARS = 1500
PREV_SENTENCE_MAX_WORDS = 60
_LOW_CONFIDENCE = 0.6
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:])")  # left behind by removed markers


class PairContext(BaseModel):
    """Everything the layers need about one claim-reference pair."""

    claim: Claim
    ref: Reference
    doc: SourceDocument
    pack: EvidencePack  # standard pack (<= 3,000 tokens)
    expanded: EvidencePack | None = None  # filled lazily (<= 8,000 tokens)
    recheck: EvidencePack | None = None  # standard + per-element passages (evidence re-check)
    claim_text: str  # citation markers removed
    prev_sentence: str = ""
    paragraph: str = ""
    co_cited: list[CoCitedRef] = Field(default_factory=list)  # same sentence, <= 3
    co_cited_docs: dict[int, SourceDocument] = Field(default_factory=dict)  # their sources
    use_embeddings: bool = True  # targeted re-retrieval may embed (eval: --no-embeddings)
    credit_panel: str | None = None  # V5.6: legend panel text a credit line closes (credit.py)

    @property
    def coverage(self) -> Literal["full_text", "abstract_only"]:
        return self.doc.coverage


def previous_sentence(claim: Claim) -> str:
    """Sentence before the citing sentence in its paragraph (<= 60 words)."""
    paragraph, sentence = claim.paragraph_text, claim.manuscript_text.strip()
    if not paragraph or not sentence:
        return ""
    pos = paragraph.find(sentence[:80])
    if pos <= 0:
        return ""
    before = split_sentences(paragraph[:pos].strip())
    if not before:
        return ""
    words = before[-1][1].split()
    return " ".join(words[-PREV_SENTENCE_MAX_WORDS:])


def local_paragraph(claim: Claim, max_chars: int = PARAGRAPH_MAX_CHARS) -> str:
    """Local paragraph context, capped to a window centred on the citing sentence."""
    paragraph = " ".join(claim.paragraph_text.split())
    if len(paragraph) <= max_chars:
        return paragraph
    sentence = " ".join(claim.manuscript_text.split())
    pos = paragraph.find(sentence[:80]) if sentence else -1
    centre = pos + len(sentence) // 2 if pos >= 0 else len(paragraph) // 2
    start = max(0, min(centre - max_chars // 2, len(paragraph) - max_chars))
    return "…" + paragraph[start:start + max_chars].strip() + "…"


def build_pair_context(
    claim: Claim, ref: Reference, doc: SourceDocument, pack: EvidencePack,
    co_cited: list[CoCitedRef] | None = None, sources: Mapping[int, ResolvedSource] | None = None,
) -> PairContext:
    """The pair's context; a figure credit is judged on its legend panel (credit.py),
    except on an abstract-only source, which cannot show one (provenance only)."""
    loaded = {k: s.doc for k, s in (sources or {}).items() if s.doc is not None}
    # panel_claim: a no-op for a claim verifier.with_credit_panels prepared
    claim = panel_claim(claim) if doc.coverage == "full_text" else without_panel(claim)
    return PairContext(
        claim=claim, ref=ref, doc=doc, pack=pack, co_cited=list(co_cited or []),
        co_cited_docs=co_cited_documents(co_cited or [], loaded),
        claim_text=_SPACE_BEFORE_PUNCT_RE.sub(
            r"\1", clean_query(claim.extracted_claim or claim.manuscript_text)),
        prev_sentence=previous_sentence(claim), paragraph=local_paragraph(claim),
        credit_panel=panel_of(claim),
    )


def apply_claim_type_behavior(
    result: VerificationResult, claim: Claim,
) -> VerificationResult:
    """Claim-type post-processing; never changes the verdict.

    Contrast claims are flagged for review only when the final verdict is
    negative or low-confidence (a well-supported contrast needs no review).
    """
    if claim.claim_type != "contrast" or result.verdict == "cannot_verify":
        return result
    negative = result.verdict in ("not_supported", "contradicted", "not_relevant")
    if negative or result.confidence < _LOW_CONFIDENCE:
        return result.model_copy(update={"needs_user_review": True})
    return result


def cannot_verify(
    claim: Claim,
    ref: Reference,
    reason: str,
    coverage: SourceCoverage = "no_source",
    *,
    cv_reason: str | None = None,
    tier: int = 1,
    text_quality_score: float | None = None,
) -> VerificationResult:
    """A cannot_verify result that keeps the real coverage and tier.

    Coverage distinguishes "no PDF available" (no_source) from "had source
    text but the check failed" (full_text / abstract_only).
    """
    return VerificationResult(
        claim_id=claim.id, reference_id=ref.id, verdict="cannot_verify",
        confidence=0.0, reasoning=reason, tier=tier, final_tier=tier,
        source_coverage=coverage, cannot_verify_reason=cv_reason,
        text_quality_score=1.0 if text_quality_score is None else text_quality_score,
        section_relevance="abstract" if coverage == "abstract_only" else "n/a",
    )


def dedupe_quotes(a: list[str], b: list[str]) -> list[str]:
    """Merge two quote lists, removing duplicates (case/whitespace-insensitive)."""
    seen: set[str] = set()
    result: list[str] = []
    for quote in a + b:
        normalized = " ".join(quote.lower().split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(quote)
    return result
