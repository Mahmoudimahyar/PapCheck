"""Is a reference's DOI printed as an uploaded PDF's OWN DOI, or only cited by it?

A paper prints its own DOI in its header, footer or metadata, before anything it
cites. A commentary or a short letter can carry its reference list on page 1 or
2, so the same DOI after a "References" heading, or on a numbered citation entry
("12. Smith A, Jones B. ... doi:10..."), cites another paper and is not evidence
that the PDF is that paper. A page whose first printed DOI is another one
belongs to that other DOI, even when the reference's DOI follows later.

Publishers break printed DOIs ("10.5555/SYNTH\\n.01234-56") or replace the slash
("10.5555=synth.2009.0001" in some older PDFs), so a DOI is searched
whitespace-tolerantly. Only a complete reference DOI is searched: a truncated one
("10.5555/synth", a bare journal stem) is a prefix of every DOI of that journal,
and a printed DOI that goes on past the reference's ("...-56.2") is another work
unless the rest is an SI / figure extension (".s001", ".g001", "/suppl...").
"""

import re

from pydantic import BaseModel

from refcheck.stages.match_pdfs.pdf_profile import (
    PREPRINT_PREFIXES,
    PdfProfile,
    find_dois_at,
    references_start,
)
from refcheck.utils.doi import normalize_doi

# "[12] Smith A", "(3) Smith, A.", "12. Smith AB," at a line start: a numbered citation entry.
_CITATION_START_RE = re.compile(
    r"(?m)^[ \t]*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)[ \t]*"
    r"[A-Z][A-Za-z'’\-]+,?[ \t]+[A-Z]{1,3}\b"
)
_ENTRY_CHARS = 400  # a citation entry from its number to its DOI
_ENTRY_LINES = 4
_MIN_DOI_SUFFIX = 5
# Extensions naming a part of the same work: SI / figure / table DOIs, "/suppl..." files.
_SI_SUFFIX = r"(?:\.(?:s|g|t|e|sd)\d{3,4}(?![A-Za-z0-9])|[./]suppl)"
_SI_SUFFIX_RE = re.compile(_SI_SUFFIX, re.IGNORECASE)
# A printed DOI ends at an SI extension, or where no word char nor ".x" "-x" "/x" follows.
_DOI_END = rf"(?=\s*{_SI_SUFFIX}|(?![A-Za-z0-9])(?!\s*[./-][A-Za-z0-9]))"


class DoiPlacement(BaseModel):
    """Where the reference DOI is printed as the PDF's own DOI."""

    page: int = 0  # 1-based page (metadata counts as page 1); 0 = not printed as its own
    other_first: bool = False  # another (non-preprint) DOI is printed before it on that page


def complete_doi(doi: str | None) -> bool:
    """A DOI suffix that can name one work: >= 5 chars, a digit, ends alphanumeric.

    "10.5555/ab12" or a bare journal stem ("10.5555/j.synth", "10.5555/synth-")
    is a truncated DOI: a prefix of every DOI of that journal.
    """
    _, slash, suffix = normalize_doi(doi or "").partition("/")
    return bool(slash) and len(suffix) >= _MIN_DOI_SUFFIX \
        and any(ch.isdigit() for ch in suffix) and suffix[-1].isalnum()


def rematch_doi(doi: str | None) -> str:
    """The normalized reference DOI when complete enough for the re-match, else ""."""
    return normalize_doi(doi) if doi and complete_doi(doi) else ""


def doi_pattern(doi: str) -> re.Pattern[str] | None:
    """Whitespace-tolerant pattern for one complete DOI ("/" may be printed as "=")."""
    wanted = rematch_doi(doi)
    if not wanted:
        return None
    parts = [r"[/=]" if ch == "/" else re.escape(ch) for ch in wanted if not ch.isspace()]
    return re.compile(r"(?<![\w.])" + r"\s*".join(parts) + _DOI_END, re.IGNORECASE)


def doi_page(doi: str | None, profile: PdfProfile) -> int:
    """1-based page on which the DOI is printed (metadata counts as page 1); 0 if absent."""
    pattern = doi_pattern(doi or "")
    if pattern is None:
        return 0
    for number, page in enumerate(profile.pages, start=1):
        if pattern.search(page):
            return number
    return 0


def in_citation_entry(text: str, pos: int) -> bool:
    """The DOI at ``pos`` sits on a numbered citation entry that starts shortly before."""
    line_start = text.rfind("\n", 0, max(0, pos - _ENTRY_CHARS)) + 1
    starts = list(_CITATION_START_RE.finditer(text, line_start, pos))
    return bool(starts) and text[starts[-1].start():pos].count("\n") <= _ENTRY_LINES


def own_doi_offset(doi: str, text: str) -> int | None:
    """Offset of the DOI where it is printed as the page's own DOI, else None."""
    pattern = doi_pattern(doi)
    if pattern is None:
        return None
    cut = references_start(text)
    for match in pattern.finditer(text, 0, cut):
        if not in_citation_entry(text, match.start()):
            return match.start()
    return None


def other_doi_before(doi: str, text: str, offset: int) -> bool:
    """Another non-preprint DOI (not the reference's or an extension of it) comes first."""
    wanted = normalize_doi(doi)
    return any(not found.startswith(PREPRINT_PREFIXES) and not related_dois(wanted, found)
               for start, found in find_dois_at(text) if start < offset)


def doi_placement(doi: str | None, profile: PdfProfile) -> DoiPlacement:
    """First page printing the reference DOI as the PDF's own DOI (see module doc)."""
    if not rematch_doi(doi):
        return DoiPlacement()
    for number, page in enumerate(profile.pages, start=1):
        offset = own_doi_offset(doi or "", page)
        if offset is not None:
            return DoiPlacement(page=number, other_first=other_doi_before(doi or "", page, offset))
    return DoiPlacement()


def related_dois(wanted: str, found: str) -> bool:
    """The printed DOI `found` is the reference DOI `wanted` or a part of that work.

    Accepted: the same DOI, an SI / figure DOI of it (".s001", ".g001",
    "/suppl..."), or a truncated print of it cut at a line break ("10.5555/synth",
    incomplete itself, so it names no other work). A longer DOI going on past
    `wanted` otherwise ("...-56.2") is another work.
    """
    if not wanted or not found:
        return False
    if found == wanted:
        return True
    if found.startswith(wanted):
        return bool(_SI_SUFFIX_RE.match(found, len(wanted)))
    if not wanted.startswith(found) or complete_doi(found):
        return False
    return not (found[-1].isalnum() and wanted[len(found)].isalnum())  # cut at a boundary
