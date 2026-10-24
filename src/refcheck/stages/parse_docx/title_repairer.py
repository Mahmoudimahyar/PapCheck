"""Second-pass title repair: detect and fix malformed reference titles.

Handles titles that are journal abbreviations, DOI strings, year fragments,
or otherwise too short to be real paper titles (< 25 chars).
"""

import logging
import re

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.apa_parser import parse_apa_reference

logger = logging.getLogger(__name__)

KNOWN_JOURNAL_ABBREVS = frozenset({
    "front", "orthop", "int", "sci", "nat", "circ", "plast", "ann",
    "br", "am j", "eur", "clin", "cell", "mol", "biochem", "biomed",
    "transplant", "biomater", "j biomed", "tissue eng", "acta",
    "plos", "bmc", "world j", "j surg", "j hand", "j plast",
})


def detect_and_repair_bad_titles(
    references: list[Reference],
) -> list[tuple[int, Reference]]:
    """Second-pass repair: detect titles that are journal abbrevs or garbage.

    Attempts heuristic repair from raw_text first. Returns a list of
    (index, reference) tuples that still need LLM-based repair.
    """
    needs_llm: list[tuple[int, Reference]] = []

    for i, ref in enumerate(references):
        if not is_likely_bad_title(ref.title):
            continue

        repaired = extract_title_from_raw_text(ref.raw_text)
        if repaired and len(repaired) > 25:
            logger.info(
                "Repaired title [%d]: '%s' -> '%s'",
                ref.id, ref.title[:30], repaired[:50],
            )
            references[i] = ref.model_copy(update={
                "title": repaired,
                "repair_applied": "title_re_extracted",
            })
        else:
            needs_llm.append((i, ref))

    return needs_llm


# "Synth Nano 14, 301–309", "Synth Inj., 210–219", "Hydrogels 5, 117", "Front. Synth. 11"
# — journal + volume/pages, optionally followed only by the DOI/URL.
_JOURNAL_CITATION = re.compile(
    r"^[A-Z][\w.&'’\- ]{0,80}?(?:"
    r"\s+\d+\s*(?:\(\d+\))?\s*[,:]\s*[eES]?\d+(?:\s*[–\-]\s*[eES]?\d+)?"  # Vol, pages
    r"|[.,]\s+[eES]?\d+\s*[–\-]\s*[eES]?\d+"  # Journal., first–last page
    r"|[.,]?\s+\d+\.?\s*(?=doi|https?:)"  # Journal Vol. doi: …
    r")\.?\s*(?:(?:doi|https?:)\S*.*)?$",
    re.IGNORECASE,
)
_DOI_IN_TEXT = re.compile(r"\bdoi\s*:|doi\.org/|\b10\.\d{4,}/", re.IGNORECASE)


def is_likely_bad_title(title: str) -> bool:
    """Return True if title is probably wrong (journal abbrev, DOI, etc.)."""
    if not title or not title.strip():
        return True
    stripped = title.strip().rstrip(".")
    if len(stripped) < 25:
        return True
    if stripped.lower().startswith("doi:") or stripped.lower().startswith("10."):
        return True
    if re.match(r"^\(\d{4}[a-z]?\)", stripped):
        return True
    # A DOI or a "Journal Vol, pages" tail is never part of an article title
    if _DOI_IN_TEXT.search(stripped) or looks_like_journal_citation(stripped):
        return True
    return stripped.lower() in KNOWN_JOURNAL_ABBREVS


def looks_like_journal_citation(text: str) -> bool:
    """True for "Journal Vol, pages[. doi: …]" segments (not a title)."""
    return bool(_JOURNAL_CITATION.match(text.strip()))


def extract_title_from_raw_text(raw_text: str) -> str | None:
    """Try to pull the real title from the full raw reference text.

    Splits on period-space and returns the longest candidate segment
    that is not authors, DOI, URL, or pagination.
    """
    if not raw_text:
        return None

    # "Authors (Year). Title. Journal ..." — the title is the segment after the year
    apa = parse_apa_reference(raw_text)
    if apa is not None and not is_likely_bad_title(apa.title):
        return apa.title

    segments = re.split(r"\.\s+", raw_text)
    candidates: list[str] = []

    for seg in segments:
        seg = seg.strip()
        if len(seg) < 20:
            continue
        if seg.lower().startswith("doi:") or seg.startswith("http"):
            continue
        if re.match(r"^[\d,\-\s:()]+$", seg):
            continue
        if _looks_like_authors(seg) or looks_like_journal_citation(seg):
            continue
        candidates.append(seg)

    if candidates:
        return max(candidates, key=len)
    return None


_SURNAME_INITIALS = re.compile(r"[A-Z][\w'\-]+,\s*(?:[A-Z]\.[\s\-]*)+")


def _looks_like_authors(text: str) -> bool:
    """Heuristic: author lists have many single initials and commas.

    Covers "J. Smith, A. B. Jones" and "Zhou, Q., Larsen-Moll, C."
    (initials followed by a comma rather than a space).
    """
    initials = re.findall(r"\b[A-Z]\.(?:\s|,)", text)
    if len(initials) >= 2:
        return True
    return len(_SURNAME_INITIALS.findall(text)) >= 2
