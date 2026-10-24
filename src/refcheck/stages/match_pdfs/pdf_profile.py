"""What an uploaded PDF prints on its first pages, read once for the re-match pass.

The re-match compares a reference with the DOI, title block and author/year
line of an uploaded PDF. Only the first pages are read: later pages hold a
reference list that cites other papers' DOIs and titles. Where a DOI counts
as the PDF's own is decided in `doi_placement`.
"""

import logging
import re
import unicodedata
from pathlib import Path

import fitz
from pydantic import BaseModel, Field

from refcheck.utils.doi import normalize_doi

logger = logging.getLogger(__name__)

_PAGES = 2
_MAX_PAGE_CHARS = 20000  # bounds alignment cost; real pages stay far below
_SCAN_PROBE_PAGES = 5
_MIN_PAGE_CHARS = 50
MIN_TEXT_CHARS = 200
_META_FIELDS = ("title", "subject", "keywords")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\s*\n\s*(\w)")
_NON_WORD_RE = re.compile(r"[\W_]+")
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>\[\]{}]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Preprint servers: a preprint is another version of the same work, not another paper.
PREPRINT_PREFIXES = ("10.1101/", "10.21203/", "10.20944/", "10.2139/", "10.48550/")
# A reference-list heading: what follows cites other papers (their DOIs, titles, authors).
_REFS_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:\d{1,2}\.?[ \t]+)?(?:references(?:[ \t]+and[ \t]+notes)?|bibliography"
    r"|literature[ \t]+cited|works[ \t]+cited|cited[ \t]+literature)[ \t]*:?[ \t]*$"
)


class PdfProfile(BaseModel):
    """First-page signals of one uploaded PDF (pages = metadata + page 1, page 2)."""

    path: str
    pages: list[str] = Field(default_factory=list)
    page_count: int = 0
    scanned: bool = False  # later pages have no text layer
    # Page 1 (with metadata) prepared once: every reference is compared with it.
    page1_variants: list[str] = Field(default_factory=list)
    page1_words: set[str] = Field(default_factory=set)
    page1_years: set[int] = Field(default_factory=set)
    dois_by_page: list[list[str]] = Field(default_factory=list)  # preprints dropped

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def has_text(self) -> bool:
        return sum(len(p.strip()) for p in self.pages) >= MIN_TEXT_CHARS

    @property
    def usable(self) -> bool:
        """Enough text on the first pages and a text layer on the following ones."""
        return self.has_text and not self.scanned

    def page_dois(self, page: int = 0) -> list[str]:
        """DOIs printed on `page` (1 = with metadata); page 0: page 1, else page 2.

        Preprint DOIs are dropped (another version of the same work).
        """
        per_page = self.dois_by_page[page - 1:page] if page else self.dois_by_page
        return next((dois for dois in per_page if dois), [])


def normalize_text(text: str) -> str:
    """Lowercase, accents and punctuation removed, whitespace collapsed."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(_NON_WORD_RE.sub(" ", text.lower()).split())


def normalized_variants(text: str) -> list[str]:
    """The normalized text, and the same with hyphenated line breaks joined."""
    plain = normalize_text(text)
    joined = normalize_text(_HYPHEN_BREAK_RE.sub(r"\1\2", text or ""))
    return [plain] if joined == plain else [plain, joined]


def text_words(text: str) -> set[str]:
    """Words of the text, hyphenated line breaks read both ways."""
    return {w for variant in normalized_variants(text) for w in variant.split()}


def text_years(text: str) -> set[int]:
    """Four-digit years (1900-2099) printed in the text."""
    return {int(y) for y in _YEAR_RE.findall(text or "")}


def find_dois(text: str) -> list[str]:
    """Normalized DOIs found by the standard pattern, in order, without duplicates."""
    found: list[str] = []
    for _, doi in find_dois_at(text):
        if doi not in found:
            found.append(doi)
    return found


def find_dois_at(text: str) -> list[tuple[int, str]]:
    """(offset, normalized DOI) of every DOI the standard pattern finds, in order."""
    found: list[tuple[int, str]] = []
    for match in _DOI_RE.finditer(text or ""):
        doi = normalize_doi(match.group(0).rstrip(".,;:)"))
        if doi:
            found.append((match.start(), doi))
    return found


def read_pdf_profile(path: Path) -> PdfProfile | None:
    """Read metadata + the first pages of a PDF (None when it cannot be opened)."""
    try:
        with fitz.open(str(path)) as doc:
            meta = doc.metadata or {}
            header = "\n".join(str(meta.get(k) or "").strip() for k in _META_FIELDS)
            texts = [str(doc[i].get_text("text")) for i in range(min(_SCAN_PROBE_PAGES, len(doc)))]
            count = len(doc)
    except Exception as exc:  # PyMuPDF raises several unrelated types for broken files
        logger.info("Re-match: cannot read %s: %s", path.name, type(exc).__name__)
        return None
    pages = [p[:_MAX_PAGE_CHARS] for p in texts[:_PAGES]]
    if pages and header.strip():
        pages[0] = f"{header.strip()}\n{pages[0]}"
    return build_profile(path, pages, page_count=count, scanned=_scanned(texts))


def references_start(text: str) -> int:
    """Offset of a "References" / "Bibliography" heading (len(text) when there is none)."""
    match = _REFS_HEADING_RE.search(text)
    return match.start() if match else len(text)


def build_profile(
    path: Path, pages: list[str], page_count: int = 0, scanned: bool = False,
) -> PdfProfile:
    """Profile from already extracted page texts (page 1 first, metadata included).

    The page-1 title / author / year signals stop at a reference-list heading: a
    bibliography entry on page 1 (a commentary, a letter) names another paper.
    """
    page1 = pages[0] if pages else ""
    head = page1[:references_start(page1)]
    return PdfProfile(
        path=str(path), pages=pages, page_count=page_count or len(pages), scanned=scanned,
        page1_variants=normalized_variants(head), page1_words=text_words(head),
        page1_years=text_years(head),
        dois_by_page=[[d for d in find_dois(t) if not d.startswith(PREPRINT_PREFIXES)]
                      for t in pages],
    )


def _scanned(texts: list[str]) -> bool:
    """Pages after the first carry (almost) no text: a scan behind a text cover page."""
    later = texts[1:]
    if len(later) < 2:
        return False
    empty = sum(1 for t in later if len(t.strip()) < _MIN_PAGE_CHARS)
    return empty * 2 > len(later)
