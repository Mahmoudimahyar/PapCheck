"""Compatibility wrapper: relevant PDF passages for a claim (V5 retrieval).

Superseded by `source_document` + `retriever` (hybrid BM25/embedding packs).
Kept so callers of the V2 API keep working: it now returns the passages of a
BM25-only standard evidence pack instead of keyword-scored paragraphs, and
never returns the whole paper.
"""

import logging
import re
import unicodedata
from pathlib import Path

from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.retrieval_models import passage_label
from refcheck.stages.verify_claims.retriever import STANDARD_PACK_TOKENS, bm25_pack
from refcheck.stages.verify_claims.source_document import load_pdf_document

logger = logging.getLogger(__name__)

_MAX_SECTION_WORDS = 2000


def find_relevant_sections(
    claim: Claim,
    pdf_path: Path,
    max_sections: int = 5,
) -> list[str]:
    """Passage texts most relevant to the claim; [] if the PDF cannot be read."""
    pairs = find_relevant_sections_with_headings(claim, pdf_path, max_sections)
    return [text for _, text in pairs]


def find_relevant_sections_with_headings(
    claim: Claim,
    pdf_path: Path,
    max_sections: int = 5,
    max_tokens: int = STANDARD_PACK_TOKENS,
) -> list[tuple[str, str]]:
    """(label, text) pairs: the abstract plus best BM25 passages within max_tokens.

    `max_sections` is kept for signature compatibility; the token budget bounds
    the result. Labels look like "Abstract" or "Results, p.4".
    """
    del max_sections
    if not pdf_path.exists():
        return []
    try:
        doc = load_pdf_document(pdf_path)
    except OSError:
        logger.warning("Could not read PDF: %s", pdf_path)
        return []
    if not doc.chunks:
        return []
    pack = bm25_pack(claim.extracted_claim, doc, max_tokens=max_tokens)
    return [(passage_label(p), p.text) for p in pack.passages]


def sanitize_text(text: str) -> str:
    """Clean text for LLM consumption: remove nulls, normalize unicode."""
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    words = text.split()
    if len(words) > _MAX_SECTION_WORDS:
        text = " ".join(words[:_MAX_SECTION_WORDS]) + "\n[truncated]"
    return text.strip()
