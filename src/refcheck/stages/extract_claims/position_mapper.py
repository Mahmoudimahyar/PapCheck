"""Map extracted claims to their positions in the manuscript text."""

import logging
import re

from rapidfuzz import fuzz

from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation
from refcheck.models.reference import ManuscriptSection, ParsedManuscript

logger = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 80
_CITATION_PATTERN = re.compile(r"\[(\d+(?:[,\-–\s]*\d+)*)\]")
_FIGURE_TABLE_PATTERN = re.compile(
    r"\b(?:Table|Figure|Fig\.)\s*\d*", re.IGNORECASE,
)

ParagraphInfo = tuple[int, str, str]  # (index, text, section_heading)


def map_claims_to_positions(
    claims: list[Claim],
    manuscript: ParsedManuscript,
) -> list[Claim]:
    """Populate claim.location with paragraph index + character offsets.

    Returns the same claims with location fields populated.
    """
    paragraphs = _flatten_paragraphs(manuscript.sections)
    mapped_count = 0

    result: list[Claim] = []
    for claim in claims:
        location = _locate_claim(claim.manuscript_text, paragraphs)
        if location is not None:
            mapped_count += 1
        result.append(claim.model_copy(update={"location": location}))

    logger.info(
        "Mapped %d of %d claims to manuscript positions",
        mapped_count, len(claims),
    )
    return result


def _flatten_paragraphs(
    sections: list[ManuscriptSection],
) -> list[ParagraphInfo]:
    """Build a flat list of paragraphs with running index and heading."""
    paragraphs: list[ParagraphInfo] = []
    idx = 0
    for section in sections:
        heading = section.heading or ""
        for para_text in _split_section_text(section.text):
            paragraphs.append((idx, para_text, heading))
            idx += 1
    return paragraphs


def _split_section_text(text: str) -> list[str]:
    """Split section text into paragraph-sized chunks."""
    if not text.strip():
        return []
    # Split on double newlines (typical paragraph boundary)
    parts = re.split(r"\n\s*\n", text)
    result = [p.strip() for p in parts if p.strip()]
    return result if result else [text.strip()]


def _locate_claim(
    manuscript_text: str,
    paragraphs: list[ParagraphInfo],
) -> ClaimLocation | None:
    """Find the paragraph and character offsets for a claim's text."""
    if not manuscript_text:
        return None

    # Exact substring search first
    for idx, para_text, heading in paragraphs:
        pos = para_text.find(manuscript_text)
        if pos != -1:
            return _build_location(
                idx, pos, pos + len(manuscript_text),
                manuscript_text, para_text, heading,
            )

    # Fuzzy fallback
    return _fuzzy_locate(manuscript_text, paragraphs)


def _fuzzy_locate(
    manuscript_text: str,
    paragraphs: list[ParagraphInfo],
) -> ClaimLocation | None:
    """Use fuzzy matching to find the best paragraph for a claim."""
    best_score = 0.0
    best_match: ParagraphInfo | None = None

    for para_info in paragraphs:
        score = fuzz.partial_ratio(manuscript_text, para_info[1])
        if score > best_score:
            best_score = score
            best_match = para_info

    if best_score < _FUZZY_THRESHOLD or best_match is None:
        return None

    idx, para_text, heading = best_match
    char_start, char_end = _sliding_window_pos(manuscript_text, para_text)
    return _build_location(idx, char_start, char_end, manuscript_text, para_text, heading)


def _sliding_window_pos(query: str, text: str) -> tuple[int, int]:
    """Find best position of query within text using sliding window."""
    if not query or not text:
        return 0, 0
    window = len(query)
    best_pos = 0
    best_score = 0.0
    for i in range(max(1, len(text) - window + 1)):
        chunk = text[i:i + window]
        score = fuzz.ratio(query, chunk)
        if score > best_score:
            best_score = score
            best_pos = i
    return best_pos, min(best_pos + window, len(text))


def _build_location(
    para_idx: int, char_start: int, char_end: int,
    claim_text: str, para_text: str, heading: str,
) -> ClaimLocation:
    """Build a ClaimLocation with citation markers and figure detection."""
    markers = _extract_citation_markers(claim_text)
    in_fig_table = _is_figure_or_table_context(para_text, char_start)

    return ClaimLocation(
        paragraph_index=para_idx,
        char_start=char_start,
        char_end=char_end,
        citation_markers=markers,
        section_heading=heading,
        in_figure_or_table=in_fig_table,
    )


def _extract_citation_markers(text: str) -> list[str]:
    """Extract citation markers like [7], [8, 9], [1-3] from text."""
    return _CITATION_PATTERN.findall(text)


def _is_figure_or_table_context(
    para_text: str, char_start: int,
) -> bool:
    """Check if the claim position is near a table/figure reference."""
    # Look within a window around the claim position
    window_start = max(0, char_start - 50)
    window_end = min(len(para_text), char_start + 50)
    context = para_text[window_start:window_end]
    return bool(_FIGURE_TABLE_PATTERN.search(context))
