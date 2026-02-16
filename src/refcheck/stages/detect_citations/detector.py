"""Main citation detector: orchestrates sub-detectors."""

import logging
import re

from refcheck.models.citation import CitationInstance
from refcheck.models.reference import ParsedManuscript
from refcheck.stages.detect_citations.author_year_detector import (
    detect_author_year_narrative,
    detect_author_year_parenthetical,
)
from refcheck.stages.detect_citations.compound_splitter import (
    split_compound_citation,
)
from refcheck.stages.detect_citations.numbered_detector import (
    detect_numbered_bracket,
    detect_numbered_superscript,
)
from refcheck.stages.detect_citations.sentence_splitter import (
    extract_sentence_context,
)

logger = logging.getLogger(__name__)

_BRACKET_RE = re.compile(r"\[\d+")
_AUTHOR_YEAR_RE = re.compile(r"\([A-Z][a-z]+.*?\d{4}")


def detect_all_citations(
    manuscript: ParsedManuscript,
) -> list[CitationInstance]:
    """Find every citation in the manuscript. Deterministic, no LLM."""
    paragraphs = _flatten_paragraphs(manuscript)
    style = detect_citation_style(paragraphs)
    logger.info("Detected citation style: %s (%d paragraphs)", style, len(paragraphs))

    raw_citations: list[CitationInstance] = []
    for para_idx, text, section in paragraphs:
        raw_citations.extend(
            _detect_in_paragraph(text, para_idx, section, style),
        )

    # Split compound citations
    expanded: list[CitationInstance] = []
    for cit in raw_citations:
        expanded.extend(split_compound_citation(cit))

    # Add sentence context
    para_map = {idx: text for idx, text, _ in paragraphs}
    for cit in expanded:
        text = para_map.get(cit.paragraph_index, "")
        sent, s_start, s_end = extract_sentence_context(
            text, cit.char_start, cit.char_end,
        )
        cit.sentence_text = sent
        cit.sentence_start = s_start
        cit.sentence_end = s_end

    deduped = _deduplicate(expanded)

    # Assign sequential IDs
    for i, cit in enumerate(deduped, 1):
        cit.id = i

    logger.info("Found %d citations (style=%s)", len(deduped), style)
    return deduped


def detect_in_paragraph(
    text: str, para_idx: int, section: str,
) -> list[CitationInstance]:
    """Detect citations in a single paragraph (public helper)."""
    style = _detect_style_for_text(text)
    raw = _detect_in_paragraph(text, para_idx, section, style)
    expanded: list[CitationInstance] = []
    for cit in raw:
        expanded.extend(split_compound_citation(cit))
    # Add sentence context
    for cit in expanded:
        sent, s_start, s_end = extract_sentence_context(
            text, cit.char_start, cit.char_end,
        )
        cit.sentence_text = sent
        cit.sentence_start = s_start
        cit.sentence_end = s_end
    return _deduplicate(expanded)


def _detect_in_paragraph(
    text: str, para_idx: int, section: str, style: str,
) -> list[CitationInstance]:
    """Run all relevant sub-detectors on a paragraph."""
    results: list[CitationInstance] = []
    if style in ("author_year", "mixed"):
        results.extend(detect_author_year_parenthetical(text, para_idx, section))
        results.extend(detect_author_year_narrative(text, para_idx, section))
    if style in ("numbered", "mixed"):
        results.extend(detect_numbered_bracket(text, para_idx, section))
        results.extend(detect_numbered_superscript(text, para_idx, section))
    return results


def detect_citation_style(
    paragraphs: list[tuple[int, str, str]],
) -> str:
    """Auto-detect citation style from manuscript paragraphs."""
    sample = paragraphs[:20]
    ay_count = 0
    num_count = 0
    for _, text, _ in sample:
        ay_count += len(_AUTHOR_YEAR_RE.findall(text))
        num_count += len(_BRACKET_RE.findall(text))

    total = ay_count + num_count
    if total == 0:
        return "author_year"
    if ay_count > total * 0.8:
        return "author_year"
    if num_count > total * 0.8:
        return "numbered"
    return "mixed"


def _detect_style_for_text(text: str) -> str:
    """Detect citation style for a single text block."""
    ay = len(_AUTHOR_YEAR_RE.findall(text))
    num = len(_BRACKET_RE.findall(text))
    if ay > 0 and num > 0:
        return "mixed"
    if num > 0:
        return "numbered"
    return "author_year"


def _flatten_paragraphs(
    manuscript: ParsedManuscript,
) -> list[tuple[int, str, str]]:
    """Flatten manuscript sections into (index, text, heading) tuples.

    IMPORTANT: Uses the same double-newline split as the viewer
    (manuscript_helpers._split_text) so paragraph_index values match.
    """
    result: list[tuple[int, str, str]] = []
    para_idx = 0
    for section in manuscript.sections:
        heading = section.heading or ""
        # Skip reference sections
        if heading.lower() in ("references", "bibliography", "works cited"):
            continue
        for para in _split_section_text(section.text):
            result.append((para_idx, para, heading))
            para_idx += 1
    return result


def _split_section_text(text: str) -> list[str]:
    """Split section text into paragraphs on double-newline boundaries.

    Must match manuscript_helpers._split_text exactly so paragraph
    indices are consistent between detection and the viewer.
    """
    if not text.strip():
        return []
    parts = re.split(r"\n\s*\n", text)
    cleaned = [p.strip() for p in parts if p.strip()]
    return cleaned if cleaned else [text.strip()]


def _deduplicate(
    citations: list[CitationInstance],
) -> list[CitationInstance]:
    """Remove duplicate citations at the same location."""
    seen: set[tuple[int, int, int, str | None, int | None]] = set()
    result: list[CitationInstance] = []
    for cit in citations:
        key = (
            cit.paragraph_index, cit.char_start, cit.char_end,
            cit.year, cit.number,
        )
        if key not in seen:
            seen.add(key)
            result.append(cit)
    return result
