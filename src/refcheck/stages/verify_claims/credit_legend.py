"""Figure-legend structure around a credit line (V5.6): labels, credit sentences, title.

A legend reads "Figure: Title. (A) Panel text ... Adapted from X. (B) Panel text ...
Reproduced from Y." The credit closes the panel text before it: from the last panel
label (or the end of the previous credit sentence) up to the credit. Only labels and
credits that START a segment count (after ". ", "; ", ": " or at the start; a credit
also right after "(" or ", ": "(Adapted from X)", "..., adapted from X"), so a
mention of a panel inside a sentence ("as in (A)") never splits a panel.

A credit sentence ends at the first sentence end where the text so far is a credit
line and a new segment follows (a capital, a label, or the end): "Adapted from Smith
et al. Graft survival ..." ends after "et al.", "Adapted from Smith et al. 2019."
after the year. Credit lines may carry a year ("..., 2019", "(2019)"), a licence tail
("under a CC BY 4.0 license") and a leading noun ("Image adapted from"); captions
may start "Supplementary Figure" / "Extended Data Fig.". Panel text loses legend
boilerplate (legend_boilerplate.py: p thresholds, n per group, scale bars).
"""

import re
from typing import NamedTuple

from refcheck.stages.verify_claims.legend_boilerplate import strip_boilerplate

PANEL_MAX_CHARS = 1200
PANEL_MIN_CHARS = 40
CREDIT_SCAN_CHARS = 400  # a credit sentence ends within this many characters

_VERB = r"(?:adapted|reproduced|reprinted|modified|redrawn|taken)"
_LEAD_NOUN = r"(?:(?:figure|fig\.?|images?|panels?|schematic|illustration|photo(?:graph)?s?)\s+)?"
_LICENCE = (r"(?:copyright|©|\(c\)|(?:with\s+)?permission|licen[cs]ed?|cc[ -]by"
            r"|creative\s+commons|open[- ]access)")
# A whole credit line: verb + "from" + at most 6 short tokens (no clause after a comma),
# optionally a year (", 2019" / "(2019)") and a copyright / licence tail. "Taken together,
# data from ..." or "Adapted from the protocol of X, cells were ..." are ordinary
# sentences, not credits.
_CREDIT_RE = re.compile(
    rf"^\W*(?:[a-z]\)\s*)?{_LEAD_NOUN}{_VERB}\s+"
    r"(?:with\s+permission\s+)?from\b(?:\s+[^\s,;]+){0,6}"
    r"(?:\s*,?\s*\(?\s*(?:19|20)\d{2}[a-z]?\s*\)?)?"
    rf"(?:\s*[,;]\s*{_LICENCE}[^\n]*"
    rf"|\s+(?:under|with|via)\s+(?:the\s+|a\s+|an\s+)?(?:terms\s+of\s+(?:the\s+)?)?{_LICENCE}"
    r"[^\n]*)?\W*$",
    re.IGNORECASE)
_CREDIT_START_RE = re.compile(rf"{_VERB}\s+(?:with\s+permission\s+)?from\b", re.IGNORECASE)
_ONE = r"(?:i{1,3}|iv|vi{0,3}|ix|x|[A-Za-z])"
_LIST = rf"{_ONE}(?:\s*(?:[-–,&]|and)\s*{_ONE})*"
_LABEL_RE = re.compile(
    rf"\(\s*{_LIST}\s*\)"  # (A) (a) (A, B) (A-C) (ii)
    r"|[A-Z]\)(?=\s)"  # A)
    r"|[A-Z]\.(?=\s+[A-Z(])"  # A. Text
    r"|[a-z],(?=\s+[A-Za-z])"  # a, text (journal style)
    rf"|Panels?\s+{_LIST}(?!\w)[:.,]?")  # Panel A / Panels A-C
_CAPTION_RE = re.compile(
    r"^\W{0,3}(?:(?:Supplementary|Supplemental|Extended\s+Data)\s+)?"
    r"(?:Figure|Fig\.?|Table|Scheme|Box)\s*(?:S?\d+[A-Za-z]?)?\s*[:.|–—-]",
    re.IGNORECASE)
_END_RE = re.compile(r"[.!?](?=\s|$)")
_ABBREVIATIONS = frozenset({"al", "ref", "refs", "fig", "figs", "eg", "ie", "vs", "no", "nos",
                            "eq", "ed", "eds", "et", "ca", "cf", "approx", "resp"})
_BOUNDARY = ".;:!?…"
_EDGE = " \t\n,;:.…"


class Label(NamedTuple):
    start: int
    end: int
    key: str  # "a" for "(A)", "Panel A", "a," ...


def is_credit_line(text: str) -> bool:
    """A figure/table credit ("Adapted from X et al.") whose only claim is provenance."""
    return bool(_CREDIT_RE.match(text or ""))


def starts_segment(text: str, pos: int) -> bool:
    """``pos`` begins a legend segment: text start, a new line, or after . ; : ! ?"""
    before = text[:pos]
    stripped = before.rstrip()
    return not stripped or stripped[-1] in _BOUNDARY or "\n" in before[len(stripped):]


def segment_labels(text: str) -> list[Label]:
    """Panel labels that begin a segment, in text order."""
    return [Label(m.start(), m.end(), re.sub(r"panels?|[^a-z0-9]", "", m.group().lower()))
            for m in _LABEL_RE.finditer(text) if starts_segment(text, m.start())]


def _after_label(text: str, pos: int, labels: list[Label]) -> bool:
    return any(lab.end <= pos and not text[lab.end:pos].strip() for lab in labels)


def credit_start_ok(text: str, pos: int, labels: list[Label]) -> bool:
    """A credit may start at ``pos``: a segment start, after a label, "(" or ", "."""
    return (starts_segment(text, pos) or _after_label(text, pos, labels)
            or text[:pos].rstrip().endswith(("(", ",")))


def sentence_end(text: str, start: int, limit: int = 400) -> int | None:
    """End offset of the sentence starting at ``start`` (abbreviations skipped)."""
    stop = min(len(text), start + limit)
    for match in _END_RE.finditer(text, start, stop):
        tokens = text[start:match.start()].split()
        word = re.sub(r"\W", "", tokens[-1]).lower() if tokens else ""
        if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
            continue
        return match.end()
    return None


def _new_segment(text: str, end: int) -> bool:
    rest = text[end:].lstrip()
    return not rest or rest[0].isupper() or _LABEL_RE.match(rest) is not None


def _closing_paren(text: str, start: int, stop: int) -> int | None:
    depth = 1
    for i in range(start, stop):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return i
    return None


def credit_end(text: str, start: int, verb_end: int) -> int | None:
    """End of the credit sentence starting at ``start`` (module doc), else None."""
    stop = min(len(text), start + CREDIT_SCAN_CHARS)
    if text[:start].rstrip().endswith("("):  # "(Adapted from X et al.)"
        close = _closing_paren(text, verb_end, stop)
        return close if close is not None and is_credit_line(text[start:close]) else None
    ends = [m.end() for m in _END_RE.finditer(text, verb_end, stop)]
    ends += [len(text)] if stop == len(text) else []
    return next((end for end in ends
                 if is_credit_line(text[start:end]) and _new_segment(text, end)), None)


def credit_spans(text: str, labels: list[Label]) -> list[tuple[int, int]]:
    """(start, end) of every credit sentence that may start where it does."""
    spans: list[tuple[int, int]] = []
    for match in _CREDIT_START_RE.finditer(text):
        start = match.start()
        if credit_start_ok(text, start, labels) and (
                end := credit_end(text, start, match.end())) is not None:
            spans.append((start, end))
    return spans


def credit_positions(credit: str, paragraph: str) -> list[int]:
    """Offsets in ``paragraph`` where the credit sentence ``credit`` starts (its verb)."""
    tokens = credit.strip().rstrip(_EDGE).split()
    if not tokens or not paragraph:
        return []
    needle = re.compile(r"\s+".join(map(re.escape, tokens)), re.IGNORECASE)
    labels = segment_labels(paragraph)
    out: list[int] = []
    for match in needle.finditer(paragraph):
        verb = _CREDIT_START_RE.search(match.group())
        pos = match.start() + (verb.start() if verb else 0)
        if credit_start_ok(paragraph, pos, labels):
            out.append(pos)
    return out


def clip_panel(text: str) -> str | None:
    """Whitespace-normalised panel text without legend boilerplate, capped (None when too
    short to judge)."""
    clean = " ".join(strip_boilerplate(" ".join(text.split())).split()).strip(_EDGE)
    if len(clean) > PANEL_MAX_CHARS:  # at a word boundary, the mark included in the cap
        clean = clean[:PANEL_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(_EDGE) + " …"
    return clean if len(clean) >= PANEL_MIN_CHARS else None


def _addressed_panel(text: str, labels: list[Label], own: Label,
                     credits: list[tuple[int, int]]) -> str | None:
    """"(a) Reprinted from X" at the end of a legend: the text of panel (a) itself."""
    for lab in labels:
        if lab.start >= own.start:
            break
        if lab.key == own.key:
            stops = [x.start for x in labels if x.start > lab.start]
            stops += [start for start, _ in credits if start > lab.start]
            return clip_panel(text[lab.start:min(stops, default=own.start)])
    return None


def panel_text(paragraph: str, pos: int) -> str | None:
    """Panel description closed by the credit starting at ``pos`` (None outside a legend)."""
    labels = segment_labels(paragraph)
    credits = credit_spans(paragraph, labels)
    before = [lab for lab in labels if lab.end <= pos]
    if before and not paragraph[before[-1].end:pos].strip():
        return _addressed_panel(paragraph, labels, before[-1], credits)
    start = max([lab.start for lab in before] + [end for _, end in credits if end <= pos]
                + [-1])
    if start < 0:  # no label, no earlier credit: only a captioned legend qualifies
        caption = _CAPTION_RE.match(paragraph)
        if caption is None:
            return None
        start = sentence_end(paragraph, caption.end()) or caption.end()  # drop the title
    return clip_panel(paragraph[start:pos].rstrip().rstrip("(")) if start < pos else None
