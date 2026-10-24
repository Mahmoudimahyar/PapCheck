"""Split sanitized source text into section-labelled runs of prose.

Input is sanitized text where blank lines separate blocks (PDF text blocks or
markdown paragraphs) and form feeds separate pages. Output runs carry their
section label, kind (body prose or figure/table caption) and page offsets.
Reference lists, acknowledgements, funding, author contributions and similar
back matter are dropped here.
"""

import re
from collections.abc import Iterator

from pydantic import BaseModel

from refcheck.stages.verify_claims.source_cleaning import (
    Heading,
    SectionLabel,
    classify_heading,
    is_caption,
    is_keywords_line,
    join_lines,
    split_inline_abstract,
)
from refcheck.stages.verify_claims.source_runs import (
    BlockRecord,
    RunKind,
    TextRun,
    group_runs,
    promote_front_abstract,
)

__all__ = ["TextRun", "iter_blocks", "parse_runs"]

_STRUCTURED_ABSTRACT_MAX_WORDS = 250
# PDF abstracts: once this long, only blocks opening with a structured-abstract label
# ("Methods: …") continue it — journals often omit the "Introduction" heading.
_ABSTRACT_COMPLETE_WORDS = 100
_STRUCTURED_LABEL_RE = re.compile(
    r"^(background|objectives?|aims?|purpose|context|methods?|methodology|design|setting"
    r"|participants|patients|interventions?|measurements?|main outcome measures?|results?"
    r"|findings|conclusions?|interpretation|significance|trial registration)\b",
    re.IGNORECASE,
)
_BACK_MATTER_MIN_POSITION = 0.4
_REFERENCE_HEADING_RE = re.compile(r"^(references?|bibliography|literature cited|works cited)")
_REF_ENTRY_RE = re.compile(
    r"^\s*(\[\d{1,4}\]|\d{1,4}[.)]?)\s+\S|^\s*[A-Z][\w'’-]+,?\s+(?:[A-Z]\.?\s?){1,3}[,.]"
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_SECTION_OF: dict[str, SectionLabel] = {
    "Abstract": "Abstract", "Introduction": "Introduction", "Methods": "Methods",
    "Results": "Results", "Discussion": "Discussion", "Conclusion": "Conclusion",
    "other": "other",
}


class _State(BaseModel):
    section: SectionLabel = "other"
    level: int | None = None
    dropping: bool = False
    drop_level: int | None = None
    abstract_seen: bool = False
    major_seen: bool = False
    abstract_words: int = 0
    saw_keywords: bool = False


def iter_blocks(text: str) -> Iterator[tuple[int | None, list[str]]]:
    """Yield (page, lines) blocks; markdown headings are always their own block."""
    pages = text.split("\f")
    for page_idx, page_text in enumerate(pages):
        page = page_idx + 1 if len(pages) > 1 else None
        buffer: list[str] = []
        for line in page_text.split("\n"):
            if not line.strip() or line.lstrip().startswith("#"):
                if buffer:
                    yield page, buffer
                buffer = []
                if line.strip():
                    yield page, [line]
            else:
                buffer.append(line)
        if buffer:
            yield page, buffer


def parse_runs(text: str) -> list[TextRun]:
    """Classify blocks into section-labelled runs; back matter is dropped."""
    state = _State()
    records: list[BlockRecord] = []
    blocks = list(iter_blocks(text))
    for i, (page, lines) in enumerate(blocks):
        heading = classify_heading(lines[0])
        if heading is not None and heading.action == "drop" and heading.level is None:
            upcoming = ([(page, lines[1:])] if len(lines) > 1 else []) + blocks[i + 1:i + 6]
            if not _plausible_back_matter(heading, i / len(blocks), upcoming):
                heading = None  # e.g. a "References" column header inside a table
        _consume_block(state, records, page, lines, heading)
    if not state.abstract_seen and state.major_seen:
        promote_front_abstract(records)
    return group_runs(records)


def _plausible_back_matter(
    heading: Heading, position: float, upcoming: list[tuple[int | None, list[str]]],
) -> bool:
    """PDF back-matter headings must sit late in the document; a reference-list
    heading must also be followed by entries that look like references."""
    if position < _BACK_MATTER_MIN_POSITION:
        return False
    if not _REFERENCE_HEADING_RE.match(heading.text):
        return True
    joined = [" ".join(lines) for _, lines in upcoming]
    looks_like_ref = [bool(_REF_ENTRY_RE.match(t) and _YEAR_RE.search(t)) for t in joined]
    return sum(looks_like_ref) >= min(2, len(looks_like_ref))


def _consume_block(
    state: _State,
    records: list[BlockRecord],
    page: int | None,
    lines: list[str],
    heading: Heading | None,
) -> None:
    if heading is not None:
        if _apply_heading(state, heading):
            lines = lines[1:]
        elif heading.level is not None:
            lines = [lines[0].lstrip("#").strip(), *lines[1:]]
    elif not state.abstract_seen and not state.major_seen and not state.dropping:
        inline = split_inline_abstract(lines[0])
        if inline is not None:
            state.section, state.abstract_seen, state.abstract_words = "Abstract", True, 0
            lines = [inline, *lines[1:]]
    if state.dropping or not lines:
        return
    body = join_lines(lines)
    if not any(ch.isalnum() for ch in body):
        return
    if state.section == "Abstract" and state.level is None \
            and state.abstract_words >= _ABSTRACT_COMPLETE_WORDS \
            and not _STRUCTURED_LABEL_RE.match(body):
        state.section = "other"  # unlabelled introduction or front matter after the abstract
    if is_keywords_line(body):
        state.saw_keywords = True
        if state.section == "Abstract":
            state.section = "other"
    kind: RunKind = "caption" if is_caption(body) else "body"
    records.append(BlockRecord(
        section=state.section, kind=kind, page=page, text=body, front=not state.major_seen,
    ))
    if state.section == "Abstract":
        state.abstract_words += len(body.split())


def _apply_heading(state: _State, heading: Heading) -> bool:
    """Update the state for a heading line; True when the line is consumed as a heading."""
    if heading.action == "drop":
        state.dropping, state.drop_level = True, heading.level
        return True
    if heading.action == "unknown":
        if not state.dropping:
            return False
        ends_drop = (heading.level is not None and state.drop_level is not None
                     and heading.level <= state.drop_level)
        if ends_drop:
            state.dropping, state.section, state.level = False, "other", heading.level
        return True
    if state.dropping:
        state.dropping = False
    elif _is_subheading(state, heading):
        return False
    action = _SECTION_OF[heading.action]
    if action == "Abstract" and (state.abstract_seen or state.major_seen):
        action = "Conclusion" if heading.text == "summary" and state.major_seen else "other"
    state.section, state.level = action, heading.level
    if action == "Abstract":
        state.abstract_seen, state.abstract_words = True, 0
    else:
        state.major_seen = True
    return True


def _is_subheading(state: _State, heading: Heading) -> bool:
    if heading.level is not None:
        return state.level is not None and heading.level > state.level
    if state.section != "Abstract" or heading.text == "introduction":
        return False
    # Structured-abstract labels ("Background", "Methods", "Results") stay in the abstract.
    return state.abstract_words < _STRUCTURED_ABSTRACT_MAX_WORDS and not state.saw_keywords
