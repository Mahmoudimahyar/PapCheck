"""Check that a PDF attached to a reference really is that paper.

Hard signals first: a DOI printed in the PDF that is not the reference's
(while the reference's DOI is absent), or the reference title appearing with
a different number in it ("2020 Annual Data Report" for a "2017 Annual Data
Report" reference) flag a mismatch on their own. Soft signals otherwise:
coverage of the title's content words, the first author's surname and a year
within +/-1; only a *clear* soft mismatch (two independent negative signals)
is flagged, because a false "mismatch" blocks verification of every claim
citing the reference.
"""

import logging
import re
from pathlib import Path
from typing import Literal

import fitz
from pydantic import BaseModel, Field

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.identity_signals import (
    doi_conflict,
    dois_related,
    find_dois,
    title_number_conflict,
)
from refcheck.stages.resolve_gaps.title_guard import normalize_title

logger = logging.getLogger(__name__)

IdentityStatus = Literal["verified", "unverified", "mismatch"]

VERIFIED_COVERAGE = 0.85
MISMATCH_COVERAGE = 0.5
MISMATCH_COVERAGE_NO_AUTHOR = 0.3
_PAGES = 2
_MAX_CHARS = 10000
_MIN_TEXT_CHARS = 200
_META_FIELDS = ("title", "subject", "keywords")
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "via", "its", "their",
    "are", "was", "were", "has", "have", "this", "that", "between", "among",
    "after", "during", "under", "over", "than", "not", "but", "can", "use",
})
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\s*\n\s*(\w)")


class IdentityCheck(BaseModel):
    """Outcome of comparing a PDF's first pages with reference metadata."""

    status: IdentityStatus = "unverified"
    title_coverage: float = 0.0
    author_found: bool | None = None
    year_found: bool | None = None
    pdf_dois: list[str] = Field(default_factory=list)  # DOIs printed on the first page(s)
    reason: str = ""


def read_first_pages_text(pdf_path: Path, pages: int = _PAGES) -> str:
    """PDF metadata (title/subject/keywords) + text of the first pages, pages
    separated by form feeds ("" if the PDF cannot be read)."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:  # PyMuPDF raises several unrelated types
        logger.info("Identity check: cannot open %s: %s", pdf_path, exc)
        return ""
    try:
        meta = doc.metadata or {}
        header = [str(meta.get(key) or "").strip() for key in _META_FIELDS]
        parts = [str(doc[i].get_text("text")) for i in range(min(pages, len(doc)))]
    except Exception as exc:  # corrupt page streams
        logger.info("Identity check: cannot read %s: %s", pdf_path, exc)
        return ""
    finally:
        doc.close()
    head = "\n".join(h for h in header if h)
    return ((head + "\n" if head else "") + "\f".join(parts))[:_MAX_CHARS]


def printed_dois(page_text: str) -> list[str]:
    """DOIs on the first page (with the metadata header), else on the next page."""
    for segment in page_text.split("\f"):
        dois = find_dois(segment)
        if dois:
            return dois
    return []


def _page_words(text: str) -> set[str]:
    """Words on the page; hyphenated line breaks are read both ways."""
    joined = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    return set(normalize_title(joined).split()) | set(normalize_title(text).split())


def title_coverage(title: str, page_words: set[str]) -> float | None:
    """Share of the title's content words found on the page (None: no title)."""
    words = [
        w for w in normalize_title(title).split()
        if len(w) > 2 and w not in _STOPWORDS
    ]
    if len(words) < 2:
        return None
    return sum(1 for w in words if w in page_words) / len(words)


def first_author_surname(authors: list[str]) -> str:
    """Best-guess surname of the first author ("" if unknown)."""
    if not authors:
        return ""
    tokens = [t for t in re.split(r"[\s,]+", authors[0]) if t]
    names = [t for t in tokens if len(t.strip(".")) > 2 and not t.isupper()]
    candidates = names or [t for t in tokens if len(t.strip(".")) > 2]
    if not candidates:
        return ""
    return normalize_title(max(candidates, key=len))


def check_identity(ref: Reference, page_text: str) -> IdentityCheck:
    """Compare a reference with the text of its PDF's first pages."""
    if len(page_text.strip()) < _MIN_TEXT_CHARS:
        return IdentityCheck(reason="no extractable text on first pages")
    words = _page_words(page_text)
    coverage = title_coverage(ref.title, words)
    surname = first_author_surname(ref.authors)
    author_found = all(p in words for p in surname.split()) if surname else None
    year_found: bool | None = None
    if ref.year:
        years = {int(y) for y in _YEAR_RE.findall(page_text)}
        year_found = any(abs(y - ref.year) <= 1 for y in years)

    check = IdentityCheck(
        title_coverage=round(coverage or 0.0, 3),
        author_found=author_found,
        year_found=year_found,
        pdf_dois=printed_dois(page_text),
    )
    hard = _hard_signals(ref, page_text, check)
    if hard is not None:
        return hard
    if coverage is None:
        return check.model_copy(update={"reason": "reference title unusable"})
    if coverage >= VERIFIED_COVERAGE and author_found is not False:
        return check.model_copy(update={"status": "verified", "reason": "title matches"})
    if ref.doi and coverage >= MISMATCH_COVERAGE and author_found is not False \
            and any(dois_related(ref.doi, d) for d in check.pdf_dois):
        return check.model_copy(update={"status": "verified", "reason": "reference DOI printed"})
    if coverage < MISMATCH_COVERAGE and author_found is False:
        return check.model_copy(update={
            "status": "mismatch", "reason": "title and first author not found",
        })
    if coverage < MISMATCH_COVERAGE_NO_AUTHOR and author_found is None and year_found is False:
        return check.model_copy(update={
            "status": "mismatch", "reason": "title and year not found",
        })
    return check.model_copy(update={"reason": "inconclusive"})


def _hard_signals(ref: Reference, page_text: str, check: IdentityCheck) -> IdentityCheck | None:
    """Mismatch from a conflicting title number or printed DOI (None: no hard signal)."""
    numbers = title_number_conflict(ref.title, page_text)
    if numbers is not None:
        return check.model_copy(update={
            "status": "mismatch",
            "reason": f"title number differs (reference {numbers[0]}, PDF {numbers[1]})",
        })
    other = doi_conflict(ref.doi, check.pdf_dois, page_text)
    if other is None:
        return None
    if check.title_coverage >= VERIFIED_COVERAGE and check.author_found is True \
            and check.year_found is not False:
        # Same title, author and year: far more likely a wrong DOI in the reference
        # list (or another version of the same work) than a different paper.
        return check.model_copy(update={
            "reason": f"PDF DOI {other} differs from the reference DOI, but title, "
                      "author and year match (check the reference DOI)",
        })
    return check.model_copy(update={
        "status": "mismatch", "reason": f"PDF DOI {other} differs from the reference DOI",
    })


def apply_identity_checks(refs: list[Reference]) -> list[Reference]:
    """Set identity_status on every reference that has a PDF (sync, fast)."""
    checked: list[Reference] = []
    for ref in refs:
        if ref.pdf_path is None:
            checked.append(ref)
            continue
        result = check_identity(ref, read_first_pages_text(Path(ref.pdf_path)))
        if result.status == "mismatch":
            logger.warning(
                "Ref %d: PDF %s does not look like the cited paper (%s, "
                "title coverage %.2f)",
                ref.id, Path(ref.pdf_path).name, result.reason, result.title_coverage,
            )
        checked.append(ref.model_copy(update={"identity_status": result.status}))
    return checked
