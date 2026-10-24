"""Does an uploaded PDF print this reference's DOI or title? (re-match evidence)

Two routes link a reference to an uploaded PDF the first pass missed:
- rematch_doi: the reference DOI is printed as the PDF's OWN DOI (doi_placement:
  not after a "References" heading, not on a numbered citation entry, and no
  other DOI printed before it) on page 1, corroborated by the title or the first
  author; or on page 2 when page 1 prints no other DOI and the title aligns
  with page 1 (a page-2 DOI alone is often a reference-list citation);
- rematch_title: the whole reference title aligns with a stretch of page 1
  (best-window similarity, so title words scattered over an abstract do not
  count), every key word of the title is in that stretch (a companion paper
  "... in swine" is not "... in rats"; title_window.py), and the first author's
  surname and the year (+/-1) are printed there.
A different DOI printed as the PDF's own blocks both. A truncated reference
DOI (too short, a bare journal stem) is ignored: it would match any longer DOI.
"""

import re
from typing import Literal

from pydantic import BaseModel

from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.doi_placement import (
    DoiPlacement,
    doi_placement,
    related_dois,
    rematch_doi,
)
from refcheck.stages.match_pdfs.pdf_profile import PdfProfile, normalize_text
from refcheck.stages.match_pdfs.title_window import (
    TITLE_ALIGNMENT_MIN,
    TITLE_STOPWORDS,
    title_match,
)

RematchMethod = Literal["rematch_doi", "rematch_title"]

TITLE_ALIGNMENT_NO_AUTHOR = 95.0
DOI_CORROBORATION_ALIGNMENT = 75.0
DOI_CORROBORATION_COVERAGE = 0.6
_PREFILTER_COVERAGE = 0.6
_MIN_TITLE_WORDS = 4
_MIN_TITLE_CHARS = 25


class RematchEvidence(BaseModel):
    """Signals linking one reference to one uploaded PDF."""

    doi_page: int = 0  # page printing the reference DOI as the PDF's own (0 = none)
    doi_primary: bool = False  # reference DOI printed where the PDF's own DOI belongs
    doi_conflict: bool = False  # the PDF prints another DOI as its own
    title_words: int = 0
    title_coverage: float = 0.0  # share of title content words on page 1
    title_alignment: float = 0.0  # best-window similarity of the title on page 1 (0-100)
    title_words_aligned: bool = False  # every title key word is in that window
    author_found: bool | None = None
    year_found: bool | None = None

    @property
    def author_and_year(self) -> bool:
        return bool(self.author_found) and bool(self.year_found)

    def rank(self) -> tuple[bool, bool]:
        """Tiebreak between references claiming the same PDF: DOI, then author + year."""
        return self.doi_primary, self.author_and_year


def content_words(title: str) -> list[str]:
    """Title words that carry meaning (length > 2, not a stopword)."""
    return [w for w in normalize_text(title).split() if len(w) > 2 and w not in TITLE_STOPWORDS]


def first_author_surname(authors: list[str]) -> str:
    """Normalized surname of the first author ("Roe, W." / "W. Roe" -> "roe")."""
    if not authors or not authors[0].strip():
        return ""
    first = authors[0].strip()
    if "," in first:
        return normalize_text(first.split(",", 1)[0])
    tokens = [t for t in re.split(r"\s+", first) if len(t.strip(".")) > 2]
    return normalize_text(tokens[-1]) if tokens else ""


def assess(ref: Reference, profile: PdfProfile) -> RematchEvidence:
    """Compare a reference with the first pages of an uploaded PDF."""
    words = content_words(ref.title)
    coverage = sum(1 for w in words if w in profile.page1_words) / len(words) if words else 0.0
    doi = rematch_doi(ref.doi)
    placement = doi_placement(doi, profile)
    page1_others = _other_dois(doi, profile.page_dois(1))
    evidence = RematchEvidence(
        doi_page=placement.page,
        doi_primary=(placement.page == 1 and not placement.other_first)
        or (placement.page == 2 and not page1_others),
        doi_conflict=_doi_conflict(doi, profile, placement, page1_others),
        title_words=len(words),
        title_coverage=round(coverage, 3),
        author_found=_author_found(ref, profile.page1_words),
        year_found=_year_found(ref, profile.page1_years),
    )
    if coverage >= _PREFILTER_COVERAGE or evidence.doi_primary:
        evidence.title_alignment, evidence.title_words_aligned = title_match(
            ref.title, profile.page1_variants)
    return evidence


def decide(ref: Reference, ev: RematchEvidence) -> RematchMethod | None:
    """The re-match route the evidence supports, or None."""
    if ev.doi_conflict:
        return None
    if ev.doi_primary and _doi_corroborated(ev):
        return "rematch_doi"
    if ev.title_words < _MIN_TITLE_WORDS or len(normalize_text(ref.title)) < _MIN_TITLE_CHARS:
        return None
    if ev.author_found is False or ev.year_found is False or not ev.title_words_aligned:
        return None
    if ev.author_found and ev.title_alignment >= TITLE_ALIGNMENT_MIN:
        return "rematch_title"
    no_author = ev.author_found is None and bool(ev.year_found)
    if no_author and ev.title_alignment >= TITLE_ALIGNMENT_NO_AUTHOR:
        return "rematch_title"
    return None


def _doi_corroborated(ev: RematchEvidence) -> bool:
    """Page 1: title, title words or first author; page 2: the title on page 1."""
    if ev.doi_page != 1:
        return ev.title_alignment >= TITLE_ALIGNMENT_MIN
    return (ev.title_alignment >= DOI_CORROBORATION_ALIGNMENT
            or ev.title_coverage >= DOI_CORROBORATION_COVERAGE or bool(ev.author_found))


def _author_found(ref: Reference, page_words: set[str]) -> bool | None:
    surname = first_author_surname(ref.authors)
    if not surname:
        return None
    return all(part in page_words for part in surname.split())


def _year_found(ref: Reference, page_years: set[int]) -> bool | None:
    if not ref.year:
        return None
    return any(abs(year - ref.year) <= 1 for year in page_years)


def _doi_conflict(
    doi: str, profile: PdfProfile, placement: DoiPlacement, page1_others: list[str],
) -> bool:
    """The PDF's own DOI (page 1, else page 2) is another one than the reference's."""
    if not doi:
        return False
    if placement.page == 1:
        return placement.other_first  # another DOI printed first is the PDF's own
    if placement.page == 2:
        return bool(page1_others)  # page 2 is then most likely a reference list
    return bool(_other_dois(doi, profile.page_dois()))


def _other_dois(doi: str, dois: list[str]) -> list[str]:
    """DOIs that are neither the reference's nor an SI extension / cut print of it."""
    return [d for d in dois if not related_dois(doi, d)]
