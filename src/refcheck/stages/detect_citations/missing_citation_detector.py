"""Detect sentences that should have citations but don't."""

import logging
import re

from refcheck.models.citation import CitationInstance, MissingCitation
from refcheck.models.reference import ParsedManuscript
from refcheck.stages.detect_citations.sentence_splitter import (
    extract_sentence_context,
)

logger = logging.getLogger(__name__)

# Patterns for sentences that DON'T need citations
_SKIP_PATTERNS = [
    re.compile(r"^(?:We |Our |In this (?:study|paper|review)|Here, we|The present study)", re.I),
    re.compile(r"^(?:In this section|The following|As (?:discussed|described|shown))", re.I),
    re.compile(r"^(?:Figure|Fig\.|Table|Scheme|Chart|Supplementary)\s+\d", re.I),
    re.compile(r"^(?:We (?:performed|used|collected|measured|analyzed|found))", re.I),
]

# Patterns for high-priority flagging
_HIGH_PRIORITY = [
    (re.compile(r"\d+\.?\d*\s*%"), "statistical_claim", "Contains percentage"),
    (re.compile(r"(?:has|have) been (?:shown|demonstrated|reported|found)", re.I),
     "attribution", "Attribution without citation"),
    (re.compile(r"(?:studies|research) (?:have|has) (?:shown|suggested)", re.I),
     "attribution", "References other studies"),
    (re.compile(r"was first (?:described|reported|discovered)", re.I),
     "historical_claim", "Historical claim"),
    (re.compile(r"(?:is|are) (?:known|recognized|established) to", re.I),
     "attribution", "Established knowledge claim"),
]

_MIN_SENTENCE_LEN = 25
_SKIP_SECTIONS = frozenset({
    "references", "bibliography", "works cited",
    "acknowledgments", "acknowledgements",
    "supplementary materials", "data availability",
})


def detect_missing_citations(
    manuscript: ParsedManuscript,
    found_citations: list[CitationInstance],
) -> list[MissingCitation]:
    """Find sentences needing citations but lacking them."""
    cited_ranges = _build_cited_ranges(found_citations)
    all_sentences = _extract_all_sentences(manuscript)
    uncited = _filter_uncited(all_sentences, cited_ranges)
    flagged = _heuristic_flag(uncited)

    # Assign IDs
    for i, mc in enumerate(flagged, 1):
        mc.id = i

    logger.info(
        "Missing citation: %d uncited sentences, %d flagged",
        len(uncited), len(flagged),
    )
    return flagged


def _build_cited_ranges(
    citations: list[CitationInstance],
) -> set[tuple[int, int, int]]:
    """Build set of (para_idx, sent_start, sent_end) for cited sentences."""
    return {
        (c.paragraph_index, c.sentence_start, c.sentence_end)
        for c in citations
    }


def _extract_all_sentences(
    manuscript: ParsedManuscript,
) -> list[MissingCitation]:
    """Extract all sentences from manuscript body sections."""
    sentences: list[MissingCitation] = []
    para_idx = 0
    for section in manuscript.sections:
        heading = (section.heading or "").strip()
        if heading.lower() in _SKIP_SECTIONS:
            continue
        for line in section.text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Split into sentences
            sent, s_start, s_end = extract_sentence_context(
                line, 0, len(line),
            )
            sentences.append(MissingCitation(
                sentence_text=sent,
                paragraph_index=para_idx,
                char_start=s_start,
                char_end=s_end,
                section_heading=heading,
            ))
            para_idx += 1
    return sentences


def _filter_uncited(
    sentences: list[MissingCitation],
    cited_ranges: set[tuple[int, int, int]],
) -> list[MissingCitation]:
    """Filter to only uncited sentences."""
    uncited: list[MissingCitation] = []
    for sent in sentences:
        key = (sent.paragraph_index, sent.char_start, sent.char_end)
        if key in cited_ranges:
            continue
        text = sent.sentence_text.strip()
        if len(text) < _MIN_SENTENCE_LEN:
            continue
        if any(p.search(text) for p in _SKIP_PATTERNS):
            continue
        uncited.append(sent)
    return uncited


def _heuristic_flag(
    sentences: list[MissingCitation],
) -> list[MissingCitation]:
    """Flag sentences that likely need citations using heuristics."""
    flagged: list[MissingCitation] = []
    for sent in sentences:
        text = sent.sentence_text
        for pattern, category, reason in _HIGH_PRIORITY:
            if pattern.search(text):
                sent.confidence = 0.8
                sent.category = category
                sent.reason = reason
                sent.suggestion = f"Consider adding a citation: {reason}"
                flagged.append(sent)
                break
    return flagged
