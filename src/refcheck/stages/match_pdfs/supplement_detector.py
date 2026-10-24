"""Recognise Supporting-Information PDFs among uploaded files.

A Supporting-Information file often opens with the article's own title page,
so title/DOI matching happily attaches it to the reference. It is recognised
by its file name (ACS "nn5c00001_si_001.pdf", Springer "MOESM1_ESM.pdf",
Elsevier "mmc1.pdf", Frontiers "Data_Sheet_1.pdf"), a supplement heading in
the first-page title area, or "Figure S1." caption lines outnumbering ordinary
ones. (The verify stage applies the same rules to the extracted text; stages
do not import each other.)
"""

import logging
import re
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

_MAX_PAGES = 12
_TITLE_AREA_LINES = 8
_MIN_S_CAPTIONS = 3
_FILE_RE = re.compile(
    r"(?:^|[^a-z])(?:si|esi|esm|sapp|supp|suppl|supplement(?:ary|al)?|supporting"
    r"|moesm\d+|mmc\d+|data[\s_-]?sheet[\s_-]?\d+)(?:[^a-z]|$)",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(
    r"^(?:supporting information|supplementa(?:ry|l)(?: online)? (?:materials?|information"
    r"|data|figures|tables|appendix)|electronic supplementary material)\b",
    re.IGNORECASE,
)
_S_CAPTION_RE = re.compile(
    r"^(?i:(?:supplementa(?:ry|l)\s+)?(?:fig(?:ure)?s?\.?|table))\s*[Ss](\d+)[a-z]?"
    r"\s*(?:[.:|]|\s+\(?[A-Z])"
)
_MAIN_CAPTION_RE = re.compile(r"^(?i:fig(?:ure)?\.?|table)\s*(\d+)[a-z]?\s*(?:[.:|]|\s+\(?[A-Z])")
_MAIN_HEADING_RE = re.compile(r"^(?:#+\s*)?(?:\d+\.?\s*)?(?:abstract|introduction|discussion)$")


def supplement_file_name(path: Path) -> bool:
    """True when the file name looks like a supplementary-material file."""
    return _FILE_RE.search(path.stem) is not None


def looks_like_supplement(first_page: str, text: str, name_hint: bool) -> bool:
    """Decide from the first page, the text of the first pages and the file-name hint."""
    title_area = [ln.strip() for ln in first_page.splitlines() if ln.strip()][:_TITLE_AREA_LINES]
    if any(_HEADING_RE.match(ln) and len(ln.split()) <= 12 for ln in title_area):
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    s_numbers = [m.group(1) for ln in lines if (m := _S_CAPTION_RE.match(ln))]
    main = sum(1 for ln in lines if _MAIN_CAPTION_RE.match(ln))
    structured = any(_MAIN_HEADING_RE.match(ln.lower()) for ln in lines)
    if len(set(s_numbers)) >= _MIN_S_CAPTIONS and len(s_numbers) >= 2 * main and not structured:
        return True
    return name_hint and (bool(s_numbers) or "abstract" not in text.lower())


def is_supplement_pdf(path: Path) -> bool:
    """True when the PDF is most likely supplementary material, not the article."""
    try:
        with fitz.open(str(path)) as doc:
            pages = [str(doc[i].get_text("text")) for i in range(min(_MAX_PAGES, len(doc)))]
    except Exception as exc:  # PyMuPDF raises several unrelated types for broken files
        logger.info("Supplement check: cannot read %s: %s", path.name, type(exc).__name__)
        return supplement_file_name(path)
    first = pages[0] if pages else ""
    return looks_like_supplement(first, "\n".join(pages), supplement_file_name(path))
