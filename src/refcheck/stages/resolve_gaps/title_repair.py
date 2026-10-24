"""Replace a garbled parsed title with the authoritative title of the DOI/PMID record.

References formatted "Authors (Year). Title. Journal Vol, pages. doi: ..." are
sometimes parsed with the citation tail as the title ("Synth Nano 14, 301-309.
doi: 10.5555/..."). Once the resolver holds the CrossRef record for the
reference's DOI (or the PubMed record for its PMID) the record's title is
authoritative. It replaces the parsed title when the parsed title looks broken
or differs from it, provided the reference string itself contains the record's
title, which guards against a wrong DOI in the manuscript. raw_text is kept.
"""

import logging
import re

from rapidfuzz import fuzz

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.markup import strip_markup
from refcheck.stages.resolve_gaps.title_guard import normalize_title
from refcheck.utils.doi import dois_match

logger = logging.getLogger(__name__)

REPAIR_LABEL = "title_from_api"
MIN_TITLE_CHARS = 12
SAME_TITLE_RATIO = 90
RAW_SUPPORT = 0.8
_DOI_RE = re.compile(r"\bdoi\b|10\.\d{4,9}/|https?://|www\.", re.IGNORECASE)
# Journal + volume (+ issue) + pages: "Synth Nano 14, 301-309", "Gels 5(2), 117", "Nature 400:100"
_CITATION_TAIL_RE = re.compile(
    r"\b\d{1,4}\s*(?:\(\s*[\w\s-]{1,12}\))?\s*[,:]\s*[a-z]?\d{1,6}(?:\s*[-–]\s*[a-z]?\d{1,6})?\b",
    re.IGNORECASE,
)
_BRACKETED_RE = re.compile(r"\[(.+)\]\.?")
_SHORT_WORDS = frozenset({"the", "and", "for", "with", "from", "into", "via", "its", "of", "in"})


def title_looks_bad(title: str) -> bool:
    """True for empty/very short titles and citation tails parsed as a title."""
    text = (title or "").strip()
    if len(text) < MIN_TITLE_CHARS or _DOI_RE.search(text):
        return True
    letters = sum(ch.isalpha() for ch in text)
    if letters < 0.5 * len(text.replace(" ", "")):
        return True
    words = normalize_title(text).split()
    return bool(_CITATION_TAIL_RE.search(text)) and len(words) <= 8


def clean_api_title(title: str) -> str:
    """Record title without markup and the trailing period PubMed adds."""
    text = strip_markup(title or "").strip()
    bracketed = _BRACKETED_RE.fullmatch(text)  # PubMed marks translated titles "[Title]."
    if bracketed and "]" not in bracketed.group(1):
        text = bracketed.group(1)
    return text.rstrip(". ").strip()


def raw_text_supports(api_title: str, raw_text: str) -> bool:
    """True when the reference string contains (almost) all words of the record title."""
    words = [w for w in normalize_title(api_title).split() if w not in _SHORT_WORDS]
    if not words or not raw_text:
        return False
    raw_words = set(normalize_title(raw_text).split())
    return sum(1 for w in words if w in raw_words) / len(words) >= RAW_SUPPORT


def title_repair_update(
    ref: Reference, crossref_title: str = "", pubmed_title: str = "", pubmed_doi: str = "",
) -> dict[str, object]:
    """Reference updates replacing the title with the record's title ({} = keep).

    `crossref_title` must come from the record of the reference's own DOI and
    `pubmed_title` from the record of its PMID (ignored when that record's DOI
    contradicts the reference DOI).
    """
    candidates = [crossref_title]
    if not (ref.doi and pubmed_doi and not dois_match(ref.doi, pubmed_doi)):
        candidates.append(pubmed_title)
    api_title = next((t for t in map(clean_api_title, candidates) if len(t) >= MIN_TITLE_CHARS),
                     "")
    if not api_title:
        return {}
    parsed, wanted = normalize_title(ref.title), normalize_title(api_title)
    if parsed == wanted:
        return {}
    bad = title_looks_bad(ref.title)
    if not bad and fuzz.ratio(parsed, wanted) >= SAME_TITLE_RATIO:
        return {}
    raw = ref.raw_text or ref.raw_text_original
    if not raw_text_supports(api_title, raw) and not (bad and not raw):
        logger.info(
            "Ref %d: record title %r not found in the reference text; title kept",
            ref.id, api_title[:80],
        )
        return {}
    logger.info("Ref %d: title %r replaced by record title %r", ref.id, ref.title[:60],
                api_title[:80])
    return {"title": api_title, "repair_applied": REPAIR_LABEL}
