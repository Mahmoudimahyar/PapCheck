"""Data models for cited-source documents (re-exported by source_document)."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from refcheck.stages.verify_claims.source_cleaning import SectionLabel

ChunkKind = Literal["abstract", "window", "caption"]
Coverage = Literal["full_text", "abstract_only"]
AbstractSource = Literal["reference", "document", "none"]  # metadata vs detected in text
# For an abstract-only fallback document the reason says why the PDF was not
# used: likely_supplement / pdf_scanned / pdf_unreadable / metadata_only /
# reference_mismatch (the PDF is another paper), or abstract_only (no PDF).
QualityReason = Literal[
    "ok", "metadata_only", "likely_supplement", "short_text", "no_sections",
    "abstract_only", "pdf_unreadable", "pdf_scanned", "reference_mismatch",
]


def estimate_tokens(text: str) -> int:
    """Cheap provider-neutral token estimate (≈4 characters per token)."""
    return math.ceil(len(text) / 4)


class Chunk(BaseModel):
    """One retrieval unit: the abstract, a 3-sentence window or a caption window."""

    model_config = ConfigDict(frozen=True)

    idx: int
    heading: SectionLabel  # Abstract/Introduction/Methods/Results/Discussion/Conclusion/other
    text: str
    n_tokens: int
    page: int | None = None
    kind: ChunkKind = "window"
    run: int = -1  # contiguous prose run; only windows of one run may merge
    sent_start: int = 0  # global sentence index range [sent_start, sent_end)
    sent_end: int = 0


class SourceDocument(BaseModel):
    """A cited source prepared for retrieval; treat as read-only (it is cached)."""

    model_config = ConfigDict(frozen=True)

    ref_id: int
    full_text: str  # sanitized, back matter removed
    chunks: list[Chunk]
    sentences: list[str]  # global sentence list that windows index into
    quality_score: float
    quality_reason: QualityReason
    has_abstract_chunk: bool
    coverage: Coverage
    abstract_source: AbstractSource = "none"
    fingerprint: str = ""  # sha256 of the chunk texts; keys retrieval caches
    n_pages: int | None = None
    cover_sheet_removed: bool = False  # a repository cover page was dropped
    ocr_pages: int = 0  # pages whose text came from OCR (scanned PDF)

    @property
    def abstract_chunk(self) -> Chunk | None:
        """The abstract unit ("A"), when one exists."""
        if self.has_abstract_chunk and self.chunks and self.chunks[0].kind == "abstract":
            return self.chunks[0]
        return None

    @property
    def windows(self) -> list[Chunk]:
        """All rankable units (windows and captions), in document order."""
        return [c for c in self.chunks if c.kind != "abstract"]
