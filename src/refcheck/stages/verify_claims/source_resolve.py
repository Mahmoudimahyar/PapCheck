"""Resolve a reference's usable source once per run (re-exported by verifier_helpers).

A PDF of another paper (identity mismatch), a scan, a supplement or a metadata
page is never used as the article: the abstract stands in when one exists (its
quality_reason names the PDF problem, see source_fallback), otherwise the pair is
cannot_verify with that problem as the reason. V5.6 (E3): an abstract too short to
judge a claim on (a stub under 300 characters, the title, an editor's one-line
summary) does not stand in either, so no verdict can rest on the paper's title.
"""

from typing import Literal

from pydantic import BaseModel

from refcheck.models.cannot_verify import classify_cannot_verify, classify_quality_reason
from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.source_document import (
    SourceDocument,
    load_source_document_async,
)
from refcheck.stages.verify_claims.source_fallback import (
    fallback_note,
    fallback_reason,
    judgeable_abstract,
    mismatch_abstract_document,
    short_fallback_note,
    source_note,
)

SourceCoverage = Literal["full_text", "abstract_only", "relevant_sections", "no_source"]

_UNUSABLE_QUALITY = 0.3


class ResolvedSource(BaseModel):
    """The usable source for a reference, or why there is none."""

    doc: SourceDocument | None = None
    coverage: SourceCoverage = "no_source"
    cannot_verify_reason: str | None = None
    detail: str = ""
    quality_score: float = 0.0


async def resolve_source(ref: Reference) -> ResolvedSource:
    """Load the reference's source; classify why it is unusable when it is (module doc)."""
    if ref.identity_status == "mismatch":
        return _mismatch_source(ref)
    doc = await load_source_document_async(ref)
    if doc is None:
        reason = classify_cannot_verify(
            ref.source_status, ref.doi, ref.reference_type, 0.0, "n/a", "no_source", False)
        return ResolvedSource(cannot_verify_reason=str(reason), detail="No source text available")
    if doc.coverage == "full_text" and (not doc.chunks or doc.quality_score < _UNUSABLE_QUALITY):
        reason = classify_quality_reason(doc.quality_reason, doc.quality_score)
        return ResolvedSource(coverage="full_text", cannot_verify_reason=str(reason),
                              quality_score=doc.quality_score,
                              detail=f"PDF text unusable ({doc.quality_reason})")
    problem = fallback_reason(doc)
    if problem is not None and not judgeable_abstract(doc.full_text, ref.title):
        return ResolvedSource(cannot_verify_reason=problem, quality_score=doc.quality_score,
                              detail=short_fallback_note(doc.quality_reason))
    return ResolvedSource(doc=doc, coverage=doc.coverage, quality_score=doc.quality_score,
                          detail=source_note(doc))


def _mismatch_source(ref: Reference) -> ResolvedSource:
    """The reference's own API abstract when it can be judged on, else reference_mismatch."""
    fallback = mismatch_abstract_document(ref)
    if fallback is not None and judgeable_abstract(fallback.full_text, ref.title):
        return ResolvedSource(doc=fallback, coverage="abstract_only", quality_score=0.5,
                              detail=fallback_note(fallback))
    detail = "The attached PDF does not match this reference" if fallback is None \
        else short_fallback_note("reference_mismatch")
    return ResolvedSource(cannot_verify_reason="reference_mismatch", detail=detail)
