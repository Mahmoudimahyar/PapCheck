"""Cited-source documents: sanitized text split into retrieval units.

`load_source_document(ref)` extracts the PDF text once per file version,
drops back matter (references, acknowledgements, funding, contributions),
splits the prose into 3-sentence windows (stride 2) tagged with section and
page, and adds the abstract (reference metadata first, else detected in the
text) as its own unit "A". Without a PDF, a reference with an abstract yields
an abstract-only document; with neither, None. A scanned PDF (no OCR) or a
supplement is unusable and falls back to the abstract (quality_reason says why).
"""

import asyncio
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.source_cleaning import sanitize_source_text
from refcheck.stages.verify_claims.source_models import (
    AbstractSource,
    Chunk,
    ChunkKind,
    Coverage,
    QualityReason,
    SourceDocument,
    estimate_tokens,
)
from refcheck.stages.verify_claims.source_parse import parse_runs
from refcheck.stages.verify_claims.source_pdf import extract_pdf_pages
from refcheck.stages.verify_claims.source_runs import TextRun
from refcheck.stages.verify_claims.source_windows import build_windows
from refcheck.stages.verify_claims.text_quality import describe_quality

__all__ = [
    "Chunk", "ChunkKind", "Coverage", "SourceDocument", "build_abstract_document",
    "build_source_document", "estimate_tokens", "load_pdf_document", "load_source_document",
    "load_source_document_async",
]

_MIN_ABSTRACT_WORDS = 20
_ABSTRACT_ONLY_QUALITY = 0.5
_UNUSABLE_PDF_QUALITY = 0.3


def build_source_document(
    ref_id: int,
    text: str,
    abstract_text: str | None = None,
    n_pages: int | None = None,
    source_name: str = "",
) -> SourceDocument:
    """Build a full-text document from raw text (PDF text, markdown or plain text).

    Blank lines separate blocks and form feeds separate pages. `abstract_text`
    (e.g. from PubMed) wins over an abstract detected in the text. `source_name`
    (the PDF file name) feeds the supplement check ("…_si_001.pdf").
    """
    clean = sanitize_source_text(text)
    quality_score, reason = describe_quality(clean, source_name)
    runs = parse_runs(clean)
    abstract, source, page = _pick_abstract(abstract_text, runs)
    chunks: list[Chunk] = []
    if abstract:
        chunks.append(Chunk(
            idx=0, heading="Abstract", text=abstract, n_tokens=estimate_tokens(abstract),
            page=page, kind="abstract",
        ))
    windows, sentences = build_windows(runs, start_idx=len(chunks))
    chunks.extend(windows)
    return SourceDocument(
        ref_id=ref_id,
        full_text="\n\n".join(run.text for run in runs),
        chunks=chunks,
        sentences=sentences,
        quality_score=quality_score,
        quality_reason=_as_reason(reason),
        has_abstract_chunk=bool(abstract),
        coverage="full_text",
        abstract_source=source,
        fingerprint=_fingerprint(chunks),
        n_pages=n_pages,
    )


def build_abstract_document(
    ref_id: int, abstract_text: str, reason: QualityReason = "abstract_only",
) -> SourceDocument:
    """Abstract-only document: a single unit "A"."""
    abstract = clean_abstract(abstract_text)
    chunks = [Chunk(
        idx=0, heading="Abstract", text=abstract, n_tokens=estimate_tokens(abstract),
        kind="abstract",
    )] if abstract else []
    return SourceDocument(
        ref_id=ref_id, full_text=abstract, chunks=chunks, sentences=[],
        quality_score=_ABSTRACT_ONLY_QUALITY, quality_reason=reason,
        has_abstract_chunk=bool(abstract), coverage="abstract_only",
        abstract_source="reference" if abstract else "none", fingerprint=_fingerprint(chunks),
    )


def load_source_document(ref: Reference) -> SourceDocument | None:
    """Best available source for a reference; None only when there is nothing at all.

    An unreadable or unusable PDF (no text, metadata page, supplement) falls back
    to the abstract when one exists (coverage "abstract_only", quality_reason says
    why); without an abstract it is returned as-is so callers can report low quality.
    """
    if ref.pdf_path is not None and Path(ref.pdf_path).exists():
        doc = load_pdf_document(Path(ref.pdf_path), ref.id, ref.abstract_text)
        if doc.quality_score >= _UNUSABLE_PDF_QUALITY or not _has_abstract(ref.abstract_text):
            return doc
        return build_abstract_document(ref.id, ref.abstract_text or "", doc.quality_reason)
    if _has_abstract(ref.abstract_text):
        return build_abstract_document(ref.id, ref.abstract_text or "")
    return None


async def load_source_document_async(ref: Reference) -> SourceDocument | None:
    """`load_source_document` off the event loop (PDF parsing is CPU/IO bound)."""
    return await asyncio.to_thread(load_source_document, ref)


def load_pdf_document(
    pdf_path: Path, ref_id: int = 0, abstract_text: str | None = None,
) -> SourceDocument:
    """Full-text document for a PDF, cached per (file version, ref, abstract)."""
    stat = pdf_path.stat()
    return _cached_pdf_document(
        str(pdf_path.resolve()), stat.st_mtime_ns, stat.st_size, ref_id, abstract_text or "",
    )


@lru_cache(maxsize=128)
def _cached_pdf_document(
    path: str, mtime_ns: int, size: int, ref_id: int, abstract_text: str,
) -> SourceDocument:
    del mtime_ns, size  # cache key only
    pdf = extract_pdf_pages(Path(path))
    unusable: QualityReason | None = None
    if pdf.scanned and not pdf.ocr_pages:
        unusable = "pdf_scanned"  # mostly image pages, no OCR: the text is not the paper
    elif not pdf.text.strip():
        unusable = "pdf_unreadable"
    if unusable is not None:
        return SourceDocument(
            ref_id=ref_id, full_text="", chunks=[], sentences=[], quality_score=0.0,
            quality_reason=unusable, has_abstract_chunk=False, coverage="full_text",
            n_pages=pdf.n_pages or None, cover_sheet_removed=pdf.cover_sheet_removed,
        )
    doc = build_source_document(ref_id, pdf.text, abstract_text or None,
                                pdf.text.count("\f") + 1, Path(path).name)
    return doc.model_copy(update={"cover_sheet_removed": pdf.cover_sheet_removed,
                                  "ocr_pages": pdf.ocr_pages})


def clean_abstract(text: str | None) -> str:
    """Single-paragraph abstract text with markup remnants removed."""
    if not text:
        return ""
    text = re.sub(r"<[^>]{1,40}>", " ", text)  # stray JATS/HTML tags
    return " ".join(sanitize_source_text(text).split())


def _has_abstract(text: str | None) -> bool:
    return len(clean_abstract(text).split()) >= _MIN_ABSTRACT_WORDS


def _pick_abstract(
    abstract_text: str | None, runs: list[TextRun],
) -> tuple[str, AbstractSource, int | None]:
    if _has_abstract(abstract_text):
        return clean_abstract(abstract_text), "reference", None
    found = [r for r in runs if r.section == "Abstract" and r.kind == "body"]
    if not found:
        return "", "none", None
    text = " ".join(r.text for r in found)
    page = found[0].page_marks[0][1] if found[0].page_marks else None
    return text, "document", page


def _as_reason(reason: str) -> QualityReason:
    allowed: dict[str, QualityReason] = {
        "ok": "ok", "metadata_only": "metadata_only", "likely_supplement": "likely_supplement",
        "short_text": "short_text", "no_sections": "no_sections", "pdf_scanned": "pdf_scanned",
    }
    return allowed.get(reason, "ok")


def _fingerprint(chunks: list[Chunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.text.encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()
