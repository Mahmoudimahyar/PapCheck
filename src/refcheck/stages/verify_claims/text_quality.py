"""PDF text quality scoring for verification (V2).

Detects metadata-only PDFs, supplements, and low-quality extractions
so the verifier can adjust confidence or fall back to abstracts.
"""

import re

SECTION_KEYWORDS: dict[str, list[str]] = {
    "abstract": ["abstract"],
    "methods": ["methods", "materials and methods", "experimental"],
    "results": ["results", "findings"],
}

# A supplement announces itself in its title area with a heading line such as
# "Supplementary Materials" or "Table S1"; a main paper merely *mentioning*
# "Supplementary Table S1" in its abstract must not be flagged.
_TITLE_AREA_LINES = 8
_SUPPLEMENT_HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:"
    r"(?:supplementa(?:ry|l)|supporting|electronic supplementary)"
    r"(?:\s+(?:online\s+)?(?:materials?|information|data|methods|appendix|text|"
    r"figures?|tables?|files?|notes?|fig\.?)\b.*)?"
    r"|(?:table|figure|fig\.?)\s+s\d+\b.*"
    r"|(?:sdc|supplemental digital content)\b.*"
    r")$",
    re.IGNORECASE,
)
_SUPPLEMENT_HEADING_MAX_WORDS = 12
# A Supporting-Information PDF can open with the article's own title page and
# then consist of "Figure S1. …", "Table S2. …" captions; it is recognised by
# those S-numbered caption lines outnumbering ordinary ones, or by its file name
# (ACS "…_si_001.pdf", Springer "…_MOESM1_ESM.pdf", Elsevier "mmc1.pdf").
_S_CAPTION_RE = re.compile(
    r"^(?i:(?:supplementa(?:ry|l)\s+)?(?:fig(?:ure)?s?\.?|table))\s*[Ss](\d+)[a-z]?"
    r"\s*(?:[.:|]|\s+\(?[A-Z])"
)
_MAIN_CAPTION_RE = re.compile(r"^(?i:fig(?:ure)?\.?|table)\s*(\d+)[a-z]?\s*(?:[.:|]|\s+\(?[A-Z])")
_MAIN_HEADING_RE = re.compile(r"^(?:#+\s*)?(?:\d+\.?\s*)?(?:abstract|introduction|discussion)$")
_SUPPLEMENT_FILE_RE = re.compile(
    r"(?:^|[^a-z])(?:si|esi|esm|sapp|supp|suppl|supplement(?:ary|al)?|supporting"
    r"|moesm\d+|mmc\d+|data[\s_-]?sheet[\s_-]?\d+)(?:[^a-z]|$)",
    re.IGNORECASE,
)
_MIN_S_CAPTIONS = 3


def supplement_file_name(name: str) -> bool:
    """True when a PDF file name looks like a supplementary-material file."""
    return bool(name) and _SUPPLEMENT_FILE_RE.search(name.rsplit(".", 1)[0]) is not None


def _s_captions(lines: list[str]) -> list[str]:
    """S-numbers of the "Figure S1." / "Table S2:" caption lines."""
    return [m.group(1) for ln in lines if (m := _S_CAPTION_RE.match(ln))]


def s_caption_dominant(text: str) -> bool:
    """True when "Figure S1."-style caption lines dominate and there is no
    Abstract/Introduction/Discussion heading (a main article with its supplement
    appended keeps those headings)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    s_numbers = _s_captions(lines)
    main = sum(1 for ln in lines if _MAIN_CAPTION_RE.match(ln))
    structured = any(_MAIN_HEADING_RE.match(ln.lower()) for ln in lines)
    return len(set(s_numbers)) >= _MIN_S_CAPTIONS and len(s_numbers) >= 2 * main \
        and not structured


def is_supplement_text(text: str, source_name: str = "") -> bool:
    """Supplement heading in the title area, S-caption dominance, or a
    supplement-like file name backed by an S caption or a missing abstract."""
    if _check_supplement(text.lower()) or s_caption_dominant(text):
        return True
    if not supplement_file_name(source_name):
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return bool(_s_captions(lines)) or not _has_keywords(text.lower(), "abstract")


def score_pdf_text(text: str, source_name: str = "") -> dict[str, float | bool | int]:
    """Score the quality of extracted PDF text.

    Returns dict with total_chars, total_words, section indicators,
    and an overall score from 0.0 to 1.0. `source_name` (the PDF file name)
    adds the file-name supplement signal.
    """
    total_chars = len(text)
    words = text.split()
    total_words = len(words)
    text_lower = text.lower()

    has_abstract = _has_keywords(text_lower, "abstract")
    has_methods = _has_keywords(text_lower, "methods")
    has_results = _has_keywords(text_lower, "results")

    is_metadata_only = total_chars < 500
    is_likely_supplement = is_supplement_text(text, source_name)

    score = _compute_score(
        total_words, is_metadata_only, is_likely_supplement,
        has_abstract, has_results,
    )

    return {
        "total_chars": total_chars,
        "total_words": total_words,
        "has_abstract": has_abstract,
        "has_methods": has_methods,
        "has_results": has_results,
        "is_metadata_only": is_metadata_only,
        "is_likely_supplement": is_likely_supplement,
        "score": score,
    }


def _has_keywords(text_lower: str, section: str) -> bool:
    """Check if text contains keywords for a given section type."""
    return any(kw in text_lower for kw in SECTION_KEYWORDS[section])


def _check_supplement(text_lower: str) -> bool:
    """True when a supplement heading appears as a line in the title area."""
    lines = [ln.strip() for ln in text_lower.splitlines() if ln.strip()]
    return any(
        len(line.split()) <= _SUPPLEMENT_HEADING_MAX_WORDS
        and _SUPPLEMENT_HEADING_RE.match(line) is not None
        for line in lines[:_TITLE_AREA_LINES]
    )


def describe_quality(text: str, source_name: str = "") -> tuple[float, str]:
    """(score, reason) where reason is ok / metadata_only / likely_supplement /
    short_text / no_sections — the first rule that set the score."""
    result = score_pdf_text(text, source_name)
    if result["is_metadata_only"]:
        reason = "metadata_only"
    elif result["is_likely_supplement"]:
        reason = "likely_supplement"
    elif int(result["total_words"]) < 200:
        reason = "short_text"
    elif not result["has_abstract"] and not result["has_results"]:
        reason = "no_sections"
    else:
        reason = "ok"
    return float(result["score"]), reason


def _compute_score(
    total_words: int,
    is_metadata_only: bool,
    is_likely_supplement: bool,
    has_abstract: bool,
    has_results: bool,
) -> float:
    """Compute overall text quality score (0.0 to 1.0)."""
    if is_metadata_only:
        return 0.1
    if is_likely_supplement:
        return 0.2
    if total_words < 200:
        return 0.4
    if not has_abstract and not has_results:
        return 0.6
    return 1.0


def check_topic_coherence(claim_text: str, section_text: str) -> float:
    """Return 0-1 score of keyword overlap between claim and section.

    Uses non-stopword token overlap ratio. Values below 0.10
    suggest the section may be irrelevant to the claim.
    """
    stopwords = _COHERENCE_STOPWORDS
    claim_words = _extract_content_words(claim_text, stopwords)
    section_words = _extract_content_words(section_text, stopwords)
    if not claim_words:
        return 0.0
    return len(claim_words & section_words) / len(claim_words)


_COHERENCE_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
    "to", "for", "of", "and", "or", "with", "that", "this", "it",
    "by", "from", "as", "be", "has", "have", "had", "not", "but",
    "they", "their", "we", "our", "its", "been", "also", "can",
    "may", "could", "would", "should",
})


def _extract_content_words(text: str, stopwords: frozenset[str]) -> set[str]:
    """Extract meaningful content words from text."""
    return {
        w.lower()
        for w in re.findall(r"\b\w+\b", text)
        if w.lower() not in stopwords and len(w) > 2
    }
