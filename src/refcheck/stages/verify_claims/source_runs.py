"""Classified text blocks → contiguous section runs (used by source_parse)."""

from typing import Literal

from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.source_cleaning import SectionLabel

RunKind = Literal["body", "caption"]


class TextRun(BaseModel):
    """Contiguous prose of one section (or one caption) with page offsets."""

    section: SectionLabel
    kind: RunKind = "body"
    text: str = ""
    page_marks: list[tuple[int, int | None]] = Field(default_factory=list)  # (offset, page)


class BlockRecord(BaseModel):
    """One kept text block after heading classification."""

    section: SectionLabel
    kind: RunKind
    page: int | None
    text: str
    front: bool  # before the first major section heading


def promote_front_abstract(records: list[BlockRecord]) -> None:
    """Journals that print the abstract without a heading: take the longest front block."""
    best: BlockRecord | None = None
    for rec in records:
        words = len(rec.text.split())
        if (rec.front and rec.kind == "body" and 80 <= words <= 500
                and rec.text.count(". ") >= 2
                and (best is None or words > len(best.text.split()))):
            best = rec
    if best is not None:
        best.section = "Abstract"


def group_runs(records: list[BlockRecord]) -> list[TextRun]:
    """Merge consecutive body records of one section; captions become their own runs."""
    runs: list[TextRun] = []
    group: list[BlockRecord] = []
    pending_captions: list[TextRun] = []
    for rec in records:
        if rec.kind == "caption":
            pending_captions.append(TextRun(
                section=rec.section, kind="caption", text=rec.text, page_marks=[(0, rec.page)],
            ))
            continue
        if group and group[0].section != rec.section:
            runs.append(_body_run(group))
            runs.extend(pending_captions)
            group, pending_captions = [], []
        group.append(rec)
    if group:
        runs.append(_body_run(group))
    runs.extend(pending_captions)
    return runs


def _body_run(group: list[BlockRecord]) -> TextRun:
    parts: list[str] = []
    marks: list[tuple[int, int | None]] = []
    length = 0
    for rec in group:
        if parts and parts[-1][-1:] in ("-", "‐") and parts[-1][-2:-1].islower() \
                and rec.text[:1].islower():
            parts[-1] = parts[-1][:-1]  # hyphenated word split across blocks
            length -= 1
        elif parts:
            parts.append(" ")
            length += 1
        marks.append((length, rec.page))
        parts.append(rec.text)
        length += len(rec.text)
    return TextRun(section=group[0].section, text="".join(parts), page_marks=marks)
