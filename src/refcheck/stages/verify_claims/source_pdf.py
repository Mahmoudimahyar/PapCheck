"""PDF text extraction for cited sources, cached per file (path + mtime + size).

Besides the text, extraction reports what it had to work around: a repository
cover sheet on page 1 is dropped (its title/author block would otherwise be
"verified" against), and a PDF whose pages are mostly images without a text
layer is flagged as scanned; such pages are OCR'd when OCR is available.
"""

import logging
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import fitz
from pydantic import BaseModel, ConfigDict

from refcheck.stages.verify_claims.source_ocr import ocr_available, ocr_page_text
from refcheck.stages.verify_claims.source_scan import (
    PageStats,
    ScanReport,
    is_cover_sheet,
    scan_report,
)

logger = logging.getLogger(__name__)

_REPEAT_MIN_PAGES = 3
_REPEAT_MIN_SHARE = 0.3
_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n")


class PdfText(BaseModel):
    """Extracted text of a PDF plus what extraction detected."""

    model_config = ConfigDict(frozen=True)

    text: str = ""  # blocks separated by blank lines, pages by form feeds
    n_pages: int = 0
    cover_sheet_removed: bool = False
    image_only_pages: int = 0
    scanned: bool = False  # mostly image pages without a text layer
    ocr_pages: int = 0  # pages whose text came from OCR


def extract_pdf_text(pdf_path: Path) -> str:
    """Return the PDF's text: blocks separated by blank lines, pages by form feeds.

    Running headers/footers (blocks repeated on many pages) and a repository
    cover sheet are removed. Returns "" when the file is missing or unreadable.
    """
    return extract_pdf_pages(pdf_path).text


def extract_pdf_pages(pdf_path: Path) -> PdfText:
    """Text plus cover-sheet / scanned-page findings (cached per file version)."""
    try:
        stat = pdf_path.stat()
    except OSError:
        logger.warning("PDF not accessible: %s", pdf_path)
        return PdfText()
    return _extract_cached(str(pdf_path.resolve()), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=64)
def _extract_cached(path: str, mtime_ns: int, size: int) -> PdfText:
    # mtime_ns and size only key the cache so an edited file is re-read.
    del mtime_ns, size
    try:
        with fitz.open(path) as doc:
            pages = [_page_blocks(page) for page in doc]
            stats = [_page_stats(page, blocks) for page, blocks in zip(doc, pages, strict=True)]
            cover = len(pages) > 1 and is_cover_sheet("\n".join(pages[0]))
            if cover:
                pages[0], stats[0] = [], PageStats()
            report = scan_report(stats)
            ocr_pages = _ocr_scanned_pages(doc, pages, stats, report, Path(path).name)
    except Exception as exc:  # PyMuPDF raises several unrelated types for broken files
        logger.warning("Could not extract text from PDF %s: %s", path, type(exc).__name__)
        return PdfText()
    pages = _drop_running_headers(pages)
    return PdfText(
        text="\f".join("\n\n".join(blocks) for blocks in pages).strip(" \n\t"),
        n_pages=len(pages), cover_sheet_removed=cover,
        image_only_pages=report.image_only_pages, scanned=report.scanned, ocr_pages=ocr_pages,
    )


def _page_blocks(page: fitz.Page) -> list[str]:
    blocks: list[str] = []
    for block in page.get_text("blocks"):
        if len(block) >= 7 and block[6] != 0:
            continue  # image block
        text = str(block[4]).strip()
        if text:
            blocks.append(text)
    return blocks


def _page_stats(page: fitz.Page, blocks: list[str]) -> PageStats:
    text = " ".join(blocks)
    return PageStats(chars=len(text), words=len(text.split()), images=len(page.get_images()))


def _ocr_scanned_pages(
    doc: fitz.Document, pages: list[list[str]], stats: list[PageStats],
    report: ScanReport, name: str,
) -> int:
    """OCR the image-only pages of a scanned PDF in place; returns pages OCR'd."""
    if not report.scanned:
        return 0
    if not ocr_available():
        logger.warning("PDF %s is scanned (%d/%d image-only pages) and OCR is unavailable",
                       name, report.image_only_pages, report.content_pages)
        return 0
    done = 0
    for i, page_stats in enumerate(stats):
        if not page_stats.image_only:
            continue
        text = ocr_page_text(doc[i])
        if len(text.strip()) > page_stats.chars:
            pages[i] = [b.strip() for b in _BLOCK_SPLIT_RE.split(text) if b.strip()]
            done += 1
    logger.info("PDF %s: OCR'd %d scanned pages", name, done)
    return done


def _block_key(text: str) -> str:
    """Page-independent key: digits and whitespace removed, lowercased."""
    return re.sub(r"[\d\s]+", "", text.lower())


def _drop_running_headers(pages: list[list[str]]) -> list[list[str]]:
    """Remove blocks that repeat on many pages (journal headers, footers, page numbers)."""
    n_pages = len(pages)
    counts: Counter[str] = Counter()
    for blocks in pages:
        counts.update({_block_key(b) for b in blocks})
    threshold = max(_REPEAT_MIN_PAGES, int(n_pages * _REPEAT_MIN_SHARE))
    repeated = {key for key, n in counts.items() if n >= threshold and len(key) < 200}
    # The first page with text (page 1, or page 2 after a dropped cover sheet) is
    # kept intact: its title area is where supplements identify themselves.
    first = next((i for i, blocks in enumerate(pages) if blocks), 0)
    return [
        blocks if i <= first
        else [b for b in blocks if _block_key(b) and _block_key(b) not in repeated]
        for i, blocks in enumerate(pages)
    ]


def clear_pdf_cache() -> None:
    """Forget cached extractions (tests, or after bulk PDF replacement)."""
    _extract_cached.cache_clear()
