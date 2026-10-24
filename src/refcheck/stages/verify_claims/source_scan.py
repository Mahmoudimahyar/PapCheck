"""Page-level checks on a cited-source PDF: repository cover sheets and scanned pages.

A repository download (e.g. a university research portal) often starts with a
cover sheet that repeats the title and authors and then carries only image
pages. Verifying against such a PDF means verifying against the cover sheet.
These pure functions classify pages from their text length and image count.
"""

import re

from pydantic import BaseModel

# Phrases of repository cover sheets / "accepted manuscript" covers (lowercase).
COVER_MARKERS = (
    "citation for published version",
    "document version",
    "link to publication",
    "take-down policy",
    "take down policy",
    "takedown policy",
    "general rights",
    "download date",
    "university of groningen",
    "research portal",
    "research explorer",
    "this is a repository copy of",
    "copyright and moral rights",
    "if you believe that this document breaches copyright",
    "users may download and print one copy",
    "please cite this article as",
    "version of record",
    "author manuscript accepted for publication",
    "this article is protected by copyright",
    "terms & conditions of use",
    "terms and conditions of use",
)
_COVER_MIN_MARKERS = 3
# A publisher's accepted-manuscript first page can carry the whole disclaimer
# ("author manuscript accepted for publication ... Version of Record ... Please
# cite this article as ... protected by copyright") above the title and the
# abstract; that page is the article, not a cover. Real covers seen: 57-293 words.
_ARTICLE_START_RE = re.compile(r"^\s*(?:abstract|summary)\b", re.IGNORECASE | re.MULTILINE)
_COVER_MAX_WORDS = 500
_COVER_SHORT_PAGE_MARKERS = 2
_COVER_SHORT_PAGE_CHARS = 2500
BLANK_PAGE_CHARS = 50
# Below this an image page has no real text layer (a repository stamp such as
# "Downloaded from ... on <date>" can sit on every scanned page).
IMAGE_PAGE_MAX_CHARS = 200
SCANNED_PAGE_SHARE = 0.5
SCANNED_MAX_WORDS = 1500


class PageStats(BaseModel):
    """Text length and image count of one PDF page."""

    chars: int = 0
    words: int = 0
    images: int = 0

    @property
    def image_only(self) -> bool:
        """An image without a usable text layer (scanned page or full-page figure)."""
        return self.chars < IMAGE_PAGE_MAX_CHARS and self.images > 0

    @property
    def blank(self) -> bool:
        return self.chars < BLANK_PAGE_CHARS and self.images == 0


class ScanReport(BaseModel):
    """How much of a PDF has a text layer."""

    content_pages: int = 0
    image_only_pages: int = 0
    text_words: int = 0
    scanned: bool = False


def cover_markers(text: str) -> list[str]:
    """Cover-sheet phrases present in a page's text."""
    lower = " ".join(text.lower().split())
    return [marker for marker in COVER_MARKERS if marker in lower]


def is_cover_sheet(text: str) -> bool:
    """True for a repository / accepted-manuscript cover page.

    Needs several distinct cover phrases (one alone, e.g. a "This article is
    protected by copyright" footer on a real first page, is not enough).
    """
    if _ARTICLE_START_RE.search(text) or len(text.split()) > _COVER_MAX_WORDS:
        return False
    found = len(cover_markers(text))
    if found >= _COVER_MIN_MARKERS:
        return True
    return found >= _COVER_SHORT_PAGE_MARKERS and len(text.strip()) < _COVER_SHORT_PAGE_CHARS


def scan_report(pages: list[PageStats]) -> ScanReport:
    """Scanned = at least half of the non-blank pages are image-only and the
    pages that do have text carry too few words to stand for the article."""
    content = [p for p in pages if not p.blank]
    image_only = sum(1 for p in content if p.image_only)
    words = sum(p.words for p in content if not p.image_only)
    scanned = bool(content) and image_only > 0 \
        and image_only / len(content) >= SCANNED_PAGE_SHARE and words < SCANNED_MAX_WORDS
    return ScanReport(content_pages=len(content), image_only_pages=image_only,
                      text_words=words, scanned=scanned)
