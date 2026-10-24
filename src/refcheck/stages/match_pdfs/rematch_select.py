"""Pick one uploaded PDF per reference in the re-match pass, or none when ambiguous.

Several qualifying PDFs are fine only when they are copies of one paper (the
same uploaded article twice); two different papers make the choice ambiguous
and nothing is linked. A chosen PDF that also qualifies for another reference
(not a duplicate entry of the same work) is linked only when this reference
ranks strictly higher (printed DOI first, then first author + year).
"""

import logging

from pydantic import BaseModel
from rapidfuzz import fuzz

from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.pdf_profile import PdfProfile, normalize_text
from refcheck.stages.match_pdfs.rematch_evidence import (
    RematchEvidence,
    RematchMethod,
    assess,
    decide,
)
from refcheck.utils.doi import normalize_doi

logger = logging.getLogger(__name__)

_SAME_COPY_RATIO = 90.0
_COPY_PREFIX_CHARS = 1500


class Candidate(BaseModel):
    """An uploaded PDF that qualifies for a reference."""

    profile: PdfProfile
    evidence: RematchEvidence
    method: RematchMethod

    def sort_key(self) -> tuple[bool, float, int, str]:
        """Best copy first: DOI route, title alignment, more text, then file name."""
        chars = sum(len(p) for p in self.profile.pages)
        return (self.method != "rematch_doi", -self.evidence.title_alignment, -chars,
                self.profile.name.lower())


def same_reference_paper(a: Reference, b: Reference) -> bool:
    """Two reference entries for one work (duplicate entry, same DOI or same title + year)."""
    if a.id == b.id or a.duplicate_of == b.id or b.duplicate_of == a.id:
        return True
    doi_a, doi_b = normalize_doi(a.doi or ""), normalize_doi(b.doi or "")
    if doi_a and doi_b:
        return doi_a == doi_b
    title_a = normalize_text(a.title)
    return bool(title_a) and title_a == normalize_text(b.title) and a.year == b.year


def pick_candidate(ref: Reference, candidates: list[Candidate]) -> Candidate | None:
    """The best copy when all qualifying PDFs are one paper; None when they differ."""
    if not candidates:
        return None
    ordered = sorted(candidates, key=Candidate.sort_key)
    best = ordered[0]
    others = [c for c in ordered[1:] if not _same_pdf_paper(best, c)]
    if others:
        logger.info(
            "Re-match: ref %d is ambiguous between %s and %s; not linked",
            ref.id, best.profile.name, others[0].profile.name,
        )
        return None
    return best


def contested(ref: Reference, chosen: Candidate, references: list[Reference]) -> bool:
    """True when another reference claims the PDF at least as strongly."""
    for other in references:
        if same_reference_paper(ref, other):
            continue
        evidence = assess(other, chosen.profile)
        if decide(other, evidence) is None:
            continue
        if evidence.rank() >= chosen.evidence.rank():
            logger.info(
                "Re-match: %s fits ref %d and ref %d equally well; not linked",
                chosen.profile.name, ref.id, other.id,
            )
            return True
    return False


def _same_pdf_paper(a: Candidate, b: Candidate) -> bool:
    """Two uploaded files hold the same paper (both print the DOI, or same text)."""
    if a.method == "rematch_doi" and b.method == "rematch_doi":
        return True
    dois_a, dois_b = a.profile.page_dois(), b.profile.page_dois()
    if dois_a and dois_b:
        return dois_a[0] == dois_b[0]
    head_a = _head(a.profile)
    head_b = _head(b.profile)
    return bool(head_a) and fuzz.ratio(head_a, head_b) >= _SAME_COPY_RATIO


def _head(profile: PdfProfile) -> str:
    return normalize_text(profile.pages[0] if profile.pages else "")[:_COPY_PREFIX_CHARS]
