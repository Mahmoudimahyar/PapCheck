"""Text sanitation and heading classification for cited-source documents.

Pure functions shared by the source parser and quote validation. PDF text
arrives with ligatures, soft hyphens, control characters and hard line
breaks; everything downstream (BM25, embeddings, quote checks) assumes the
cleaned form produced here.
"""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel

SectionLabel = Literal[
    "Abstract", "Introduction", "Methods", "Results", "Discussion", "Conclusion", "other",
]
HeadingAction = Literal[
    "Abstract", "Introduction", "Methods", "Results", "Discussion", "Conclusion",
    "other", "drop", "unknown",
]

LIGATURES: dict[str, str] = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_LIGATURE_RE = re.compile("|".join(LIGATURES))
_INVISIBLE_RE = re.compile("[­​‌‍⁠﻿]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_SPACES_RE = re.compile(r"[ \t  -   　]+")


class Heading(BaseModel):
    """A line recognised as a section heading."""

    action: HeadingAction
    text: str  # normalised heading text (lowercase, no numbering)
    level: int | None = None  # markdown level ('#' count); None for PDF text


def sanitize_source_text(text: str) -> str:
    """Normalise raw extracted text; keeps newlines and form feeds (page breaks).

    NFKC folds ligatures (ﬁ → fi), full-width forms (，→ ,), the micro sign
    (µ → μ) and similar compatibility characters, so BM25, embeddings and quote
    validation (which also uses NFKC) all see the same spelling as the claim.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = _LIGATURE_RE.sub(lambda m: LIGATURES[m.group(0)], text)
    text = _INVISIBLE_RE.sub("", text)
    # "…" stays one character: as "..." it would end sentences for the splitter.
    text = "…".join(unicodedata.normalize("NFKC", part) for part in text.split("…"))
    text = _SPACES_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(" \n\t")  # keep form feeds (page numbers)


def join_lines(lines: list[str]) -> str:
    """Join hard-wrapped lines, repairing words split at a line-end hyphen.

    "aggre-\\ngation" → "aggregation" (soft hyphenation between lowercase parts);
    "T-\\ncell", "VX-\\n880", "anti-\\nCD3" keep their hyphen and lose the space,
    because a capital or digit next to the hyphen marks a real compound.
    """
    parts: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        prev = parts[-1] if parts else ""
        if prev[-1:] in ("-", "‐") and prev[-2:-1].isalnum() and line[:1].isalnum():
            if prev[-2:-1].islower() and line[:1].islower():
                parts[-1] = prev[:-1] + line
            else:
                parts[-1] = prev + line
        else:
            parts.append(line)
    return " ".join(parts)


_DROP_RE = re.compile(
    r"^(references?( and notes)?|bibliography|literature cited|works cited|cited literature"
    r"|acknowledge?ments?|funding.*|financial (support|disclosures?)|grants?"
    r"|authors?'? ?contributions?|contributors?|contributor information"
    r"|competing (financial )?interests?|conflicts? of interests?|declarations?( of.*)?"
    r"|disclosures?( forms)?|footnotes|notes|abbreviations|data (availability|sharing).*"
    r"|ethics (statement|declarations)|publisher'?s note|orcid|disclaimer.*"
    r"|(credit )?(authorship )?contribution statement|author statement)$"
)
_SECTION_RES: list[tuple[HeadingAction, re.Pattern[str]]] = [
    ("Abstract", re.compile(r"^(abstract|summary)$")),
    ("Introduction", re.compile(r"^(introduction|background)$")),
    ("Results", re.compile(r"^(results?( and discussion)?|findings)$")),
    ("Methods", re.compile(
        r"^(.{0,30}\bmethods?\b.{0,30}|methodology|experimental( procedures| section)?"
        r"|study design)$"
    )),
    ("Discussion", re.compile(r"^((general )?discussion|discussion and conclusions?)$")),
    ("Conclusion", re.compile(
        r"^(conclusions?|concluding remarks|summary and conclusions?"
        r"|conclusions? and (perspectives|outlook|future directions))$"
    )),
    ("other", re.compile(
        r"^(supplementa(ry|l) (materials?|information|data|appendix)|supporting information"
        r"|extended data|appendix( [a-z0-9])?|figure legends|figures?|tables?)$"
    )),
]
_NUMBERING_RE = re.compile(r"^(\d+(\.\d+)*\.?|[ivx]+\.|[a-h]\.)\s+")
_MD_RE = re.compile(r"^(#{1,6})\s*(.*)$")
_CAPTION_RE = re.compile(
    r"^(?i:(supplementa(ry|l) )?(fig(ure)?s?\.?|table)\s*s?\d+[a-z]?)"
    r"\s*([.:|\-–—]|\s+[A-Z(])"
)
_KEYWORDS_RE = re.compile(r"^(key ?words?|index terms)\b", re.IGNORECASE)
_INLINE_ABSTRACT_RE = re.compile(
    r"^(?:#+\s*)?(abstract\b[\s:.—–-]*|summary\s*[:.—–-]\s*)(?=\S)",
    re.IGNORECASE,
)


def normalize_heading(line: str) -> str:
    """Lowercase heading text without markdown hashes, numbering or trailing colon."""
    text = line.strip().lstrip("#").strip().lower()
    text = _NUMBERING_RE.sub("", text)
    text = re.sub(r"[★*†:]+", " ", text)
    text = re.sub(r"[^\w\s'&/-]", "", text).replace("&", "and").replace("/", " ")
    return " ".join(text.split())


def classify_heading(line: str) -> Heading | None:
    """Return a Heading when the line looks like a section title, else None."""
    stripped = line.strip()
    md = _MD_RE.match(stripped)
    level = len(md.group(1)) if md else None
    body = md.group(2).strip() if md else stripped
    if not body or len(body) > 80 or len(body.split()) > 7:
        return Heading(action="unknown", text=body.lower(), level=level) if md and body else None
    if level is None and (body.endswith((".", ",", ";")) or not body[:1].isalnum()
                          or (body[:1].isalpha() and not body[:1].isupper())):
        return None
    norm = normalize_heading(body)
    if _DROP_RE.match(norm):
        return Heading(action="drop", text=norm, level=level)
    for action, pattern in _SECTION_RES:
        if pattern.match(norm):
            return Heading(action=action, text=norm, level=level)
    return Heading(action="unknown", text=norm, level=level) if md else None


def split_inline_abstract(line: str) -> str | None:
    """'Abstract Background: text…' → the text after the label (≥5 words), else None."""
    match = _INLINE_ABSTRACT_RE.match(line.strip())
    if match is None:
        return None
    rest = line.strip()[match.end():].strip()
    return rest if len(rest.split()) >= 5 else None


def is_caption(text: str) -> bool:
    """True for figure / table caption blocks ("Figure 2. …", "Table 1 | …")."""
    return bool(_CAPTION_RE.match(text.strip()))


def is_keywords_line(text: str) -> bool:
    """True for a 'Keywords:' line, which marks the end of an abstract."""
    return bool(_KEYWORDS_RE.match(text.strip()))
