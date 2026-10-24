"""Full text of a cited paper for manual review: local PDFs only (PyMuPDF), no API.

A text file already extracted for an earlier review (review_partial/, review/)
is reused when it is non-empty and its head contains the reference's title, so
reviewers see the same text as before; otherwise the session's PDF is extracted
with the production extractor. Scanned, empty or supplementary PDFs are noted.
"""

import logging
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.source_pdf import PdfText, extract_pdf_pages

logger = logging.getLogger(__name__)
MIN_TEXT_CHARS = 2000
TITLE_HEAD_CHARS = 12000
TITLE_MIN_SHARE = 0.6
_SUPPLEMENT_RE = re.compile(r"_si_\d|supplement|suppl[._ -]|supporting[ _-]info", re.I)
_WORD_RE = re.compile(r"[a-z]{4,}")


class PaperText(BaseModel):
    """Where a reference's review text is and what was noticed while getting it."""

    ref: int
    text_file: str = ""
    chars: int = 0
    origin: str = "none"  # "reused review_partial" | "reused review" | "extracted" | "none"
    notes: list[str] = Field(default_factory=list)


def title_found(title: str, text: str) -> bool:
    """Most of the title's words occur near the start of the text (same paper)."""
    words = set(_WORD_RE.findall(title.lower()))
    if not words:
        return True
    head = " ".join(re.sub(r"-\s*\n\s*", "", text[:TITLE_HEAD_CHARS].lower()).split())
    return sum(1 for w in words if w in head) / len(words) >= TITLE_MIN_SHARE


def _reusable(ref: int, title: str, reuse_dirs: list[Path]) -> Path | None:
    for folder in reuse_dirs:
        path = folder / f"ref{ref}.txt"
        if not path.is_file() or path.stat().st_size == 0:
            continue
        if title_found(title, path.read_text(encoding="utf-8", errors="replace")):
            return path
        logger.warning("ref %d: %s does not look like '%s'; not reused", ref, path, title[:60])
    return None


def _scan_notes(pdf: PdfText) -> list[str]:
    notes: list[str] = []
    if pdf.scanned:
        notes.append(f"scanned PDF: {pdf.image_only_pages}/{pdf.n_pages} image-only pages, "
                     f"{pdf.ocr_pages} OCR'd")
    if pdf.cover_sheet_removed:
        notes.append("repository cover sheet removed")
    return notes


def paper_text(ref: int, pdf_path: str | None, title: str, out_dir: Path,
               reuse_dirs: list[Path]) -> PaperText:
    """Write out_dir/ref<N>.txt for one reference (when any text exists) and describe it."""
    if not pdf_path:
        return PaperText(ref=ref, notes=["no PDF linked: abstract only"])
    pdf = Path(pdf_path)
    if not pdf.is_file():
        return PaperText(ref=ref, notes=[f"linked PDF missing on disk: {pdf.name}"])
    notes = ["linked PDF looks like supplementary material, not the article"] \
        if _SUPPLEMENT_RE.search(pdf.name) else []
    extracted = extract_pdf_pages(pdf)
    notes.extend(_scan_notes(extracted))
    target = out_dir / f"ref{ref}.txt"
    source = _reusable(ref, title, reuse_dirs)
    if source is not None:
        shutil.copyfile(source, target)
        origin, chars = f"reused {source.parent.name}", len(target.read_text(encoding="utf-8"))
    elif extracted.text.strip():
        target.write_text(extracted.text, encoding="utf-8")
        origin, chars = "extracted", len(extracted.text)
        if not title_found(title, extracted.text):
            notes.append("reference title not found near the start: PDF may be another paper")
    else:
        notes.append("no extractable text (scanned or empty PDF)")
        return PaperText(ref=ref, notes=notes)
    if chars < MIN_TEXT_CHARS:
        notes.append(f"very little text ({chars} chars): scanned, truncated or not the article")
    return PaperText(ref=ref, text_file=str(target), chars=chars, origin=origin, notes=notes)
