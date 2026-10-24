"""Local sentence/paragraph context for a citation.

The DOCX parser joins Word paragraphs with a single newline, while the
detector's "paragraphs" are split on blank lines, so a detector paragraph
is often a whole section. The context handed to verification must be the
local Word paragraph around the citing sentence, never the whole section.
"""

from refcheck.models.citation import CitationInstance
from refcheck.stages.detect_citations.sentence_splitter import (
    extract_sentence_context,
)

PARAGRAPH_WINDOW_CHARS = 2000


def line_span(text: str, pos: int) -> tuple[int, int]:
    """Offsets [start, end) of the newline-delimited line containing pos."""
    pos = min(max(pos, 0), len(text))
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, len(text) if end == -1 else end


def clip_sentence_to_line(
    text: str, sent_start: int, sent_end: int, anchor: int,
) -> tuple[str, int, int]:
    """Clip a sentence span to the line holding the citation marker.

    The sentence splitter can run across a Word paragraph break (e.g. an
    unpunctuated sub-heading followed by the citing sentence).
    """
    line_start, line_end = line_span(text, anchor)
    start = max(sent_start, line_start)
    end = min(sent_end, line_end)
    if start >= end:
        start, end = sent_start, sent_end
    return _stripped_span(text, start, end)


def _stripped_span(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Sentence text plus offsets of exactly that text, so a marker sits at
    ``char_start - sentence_start`` inside ``sentence_text``."""
    raw = text[start:end]
    lead = len(raw) - len(raw.lstrip())
    stripped = raw.strip()
    return stripped, start + lead, start + lead + len(stripped)


def local_paragraph(
    text: str,
    sent_start: int,
    sent_end: int,
    max_chars: int = PARAGRAPH_WINDOW_CHARS,
) -> str:
    """Paragraph containing the sentence, capped to a window around it."""
    if not text:
        return ""
    para_start, _ = line_span(text, sent_start)
    _, para_end = line_span(text, max(sent_start, sent_end - 1))
    if para_end - para_start <= max_chars:
        return text[para_start:para_end].strip()
    start, end = _window(text, para_start, para_end, sent_start, sent_end, max_chars)
    return text[start:end].strip()


def _window(
    text: str,
    para_start: int,
    para_end: int,
    sent_start: int,
    sent_end: int,
    max_chars: int,
) -> tuple[int, int]:
    """A max_chars window inside the paragraph, centred on the sentence."""
    sent_len = sent_end - sent_start
    if sent_len >= max_chars:
        return sent_start, sent_start + max_chars
    start = max(para_start, sent_start - (max_chars - sent_len) // 2)
    end = min(para_end, start + max_chars)
    start = max(para_start, end - max_chars)
    # Snap to word boundaries so the window never starts/ends mid-word.
    if start > para_start:
        space = text.find(" ", start, sent_start)
        if space != -1:
            start = space + 1
    if end < para_end:
        space = text.rfind(" ", sent_end, end)
        if space != -1:
            end = space
    return start, end


def add_context(cit: CitationInstance, text: str) -> CitationInstance:
    """Return a copy of the citation with sentence + local paragraph set."""
    _, s_start, s_end = extract_sentence_context(
        text, cit.char_start, cit.char_end,
    )
    sentence, s_start, s_end = clip_sentence_to_line(
        text, s_start, s_end, cit.char_start,
    )
    return cit.model_copy(update={
        "sentence_text": sentence,
        "sentence_start": s_start,
        "sentence_end": s_end,
        "paragraph_text": local_paragraph(text, s_start, s_end),
    })
