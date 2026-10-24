"""Parse APA/Harvard-style references: "Authors (Year). Title. Journal Vol, pages. doi".

The generic parser split such entries at the first "lowercase letter + period"
and stored what followed — "Synth Nano 14, 301–309. doi: …" — as the title,
and it returned surnames and initials as separate "authors". Here the
"(Year)." slot anchors the split: authors before it, title = the first
sentence after it.
"""

import re

from pydantic import BaseModel

_HEAD = re.compile(
    r"^(?P<authors>[^()\[\]]{2,800}?)\s*"
    r"\((?:(?:19|20)\d{2}[a-z]?(?:,[^)]{0,30})?|n\.\s?d\.|in press)\)"
    r"[.,:]?\s+(?P<rest>\S.*)$",
    re.DOTALL,
)
_INITIALS = re.compile(r"^(?:[A-Z][a-z]?\.[\s\-‐]*)+$")
_INITIALS_NO_DOTS = re.compile(r"^(?P<surname>.+?)\s+(?P<initials>[A-Z]{1,3})$")
_PARTICLES = frozenset({
    "de", "da", "das", "do", "dos", "del", "della", "der", "den", "di", "du",
    "la", "le", "van", "von", "ten", "ter", "y", "e", "el", "al", "bin", "ibn",
})
_NAME_WORD = re.compile(r"^[A-ZÀ-ɏ][\w'’\-‐À-ɏ]*$")
_ET_AL = re.compile(r",?\s*et\s+al\.?\s*$", re.IGNORECASE)
_SPLIT_AUTHORS = re.compile(r",\s*(?:and\s+|&\s+)?|\s+(?:and|&)\s+")
# Abbreviations whose period does not end a title
_TITLE_ABBREV = re.compile(r"\b(vs|e\.g|i\.e|et al|sp|spp|approx|ca|cf|no|vol)\.", re.IGNORECASE)
_DOTTED_ACRONYM = re.compile(r"\b(?:[A-Z]\.){2,}")
_TITLE_END = re.compile(r"(?<=\S\S)[.?!](?=\s|$)")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]{0,20}>")
_MIN_TITLE_WORDS = 2


class ApaParts(BaseModel):
    """Authors and title split out of an APA/Harvard reference."""

    authors: list[str]
    title: str


def parse_apa_reference(text: str) -> ApaParts | None:
    """Split an "Authors (Year). Title. ..." reference, or None if not that shape."""
    match = _HEAD.match(text.strip())
    if not match:
        return None
    authors = split_apa_authors(match.group("authors"))
    title = apa_title(match.group("rest"))
    if authors is None or not title:
        return None
    return ApaParts(authors=authors, title=title)


def apa_title(rest: str) -> str:
    """First sentence of the text after "(Year)." — the article title."""
    cleaned = _HTML_TAG.sub("", rest).strip()
    protected = cleaned
    for pattern in (_DOTTED_ACRONYM, _TITLE_ABBREV):  # "U.S.", "vs." do not end a title
        protected = pattern.sub(lambda m: m.group(0).replace(".", "\x00"), protected)
    end = _TITLE_END.search(protected)
    title = cleaned[: end.start() + 1] if end else cleaned
    title = title.strip().rstrip(".").strip()
    if len(title.split()) < _MIN_TITLE_WORDS or re.match(r"(?i)doi\b|https?:", title):
        return ""
    return title


def split_apa_authors(text: str) -> list[str] | None:
    """["Surname, I.", ...] from "Surname, I., Surname, I. J., and Surname, K."

    None when the text does not look like an author list (so the caller can
    fall back to other strategies instead of inventing authors).
    """
    cleaned = _ET_AL.sub("", text.strip().rstrip(",").strip())
    tokens = [t.strip() for t in _SPLIT_AUTHORS.split(cleaned) if t and t.strip()]
    if not tokens:
        return None
    authors: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not _is_surname(token):
            return _single_organisation(tokens)
        if i + 1 < len(tokens) and _INITIALS.match(tokens[i + 1]):
            authors.append(f"{token}, {tokens[i + 1]}")
            i += 2
            continue
        no_dots = _INITIALS_NO_DOTS.match(token)
        if no_dots and _is_surname(no_dots.group("surname")):
            authors.append(f"{no_dots.group('surname')}, {no_dots.group('initials')}")
        elif len(tokens) == 1:
            authors.append(token)
        else:
            return None
        i += 1
    return authors


def _is_surname(token: str) -> bool:
    """A family name of up to four words; particles may be lowercase."""
    words = token.split()
    if not 1 <= len(words) <= 4:
        return False
    if not any(_NAME_WORD.match(w) for w in words):
        return False
    return all(_NAME_WORD.match(w) or w.lower() in _PARTICLES for w in words)


def _single_organisation(tokens: list[str]) -> list[str] | None:
    """A group author such as "World Health Organization" (one token only)."""
    if len(tokens) != 1:
        return None
    token = tokens[0]
    if re.search(r"[\d:;]", token) or len(token.split()) > 10:
        return None
    return [token] if token[:1].isupper() else None
