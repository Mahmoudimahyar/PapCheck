"""Quotes that are front matter, never evidence (V5.6, finding E1).

The manual review of "supported" verdicts found figure credits ("Adapted from
X et al.") evidenced by the source's title or author block. A quote that is
(mostly) the reference's title, its author list / affiliation block, or the
journal header printed before the abstract on page 1 identifies the paper; it
states nothing the paper found. Such a quote is context only: kept in the layer
trace, never counted as evidence (layer_audit.py).
"""

import re

from rapidfuzz import fuzz

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.quote_validator import normalize_for_match, validate_quotes
from refcheck.stages.verify_claims.source_models import SourceDocument

_WORD_RE = re.compile(r"[a-z0-9]+")
_CASED_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_STOP = frozenset([
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to",
    "with",
])
_HEADER_WORDS = frozenset([
    "university", "univ", "department", "dept", "institute", "school", "college",
    "hospital", "center", "centre", "laboratory", "lab", "faculty", "division", "clinic",
    "foundation", "academy", "email", "mail", "correspondence", "corresponding", "author",
    "authors", "received", "accepted", "revised", "published", "online", "available",
    "copyright", "rights", "reserved", "doi", "org", "www", "http", "https", "journal",
    "vol", "volume", "issue", "issn", "pages", "article", "open", "access", "licence",
    "license", "creative", "commons", "citation", "editor", "usa", "uk", "china", "germany",
    "japan", "france", "italy", "canada", "korea", "street", "road", "avenue",
])
_TITLE_RATIO = 88  # fuzz.ratio: the quote is the title (small extraction differences)
_TITLE_IN_QUOTE = 90  # fuzz.partial_ratio: the title sits inside the quote ...
_TITLE_SHARE = 0.6  # ... and makes up most of it
_MIN_FRAGMENT_WORDS = 3  # a contiguous title fragment of at least this many content words
_BLOCK_SHARE = 0.7  # quote words that are names, initials, numbers or header vocabulary
_MIN_BLOCK_WORDS = 3
# Statistics or a comparison: "52 ± 4 d", "P = 0.002", "n = 6", "40%", "10 mg", "vs".
_STATS_RE = re.compile(
    r"±|\+/-|\b[pPnN]\s*[=<>≤≥]|\d\s*%|\b(?:vs\.?|versus)\s"
    r"|\d\s*(?:mg|kg|µg|μg|ng|ml|mL|µl|μl|mm|cm|µm|μm|nm|kPa|MPa|mmHg|°C|days?|weeks?|months?"
    r"|h|hours?|min)\b")
_MAX_LOWER_WORDS = 2  # lower-case content words (not header vocabulary): running text
_HEADER_SCAN_CHARS = 2500  # a longer "header" is not a title/author block: ignored
_HEADER_SIMILARITY = 0.95
_ABSTRACT_OPENING = 60  # chars of the abstract unit looked up in the full text
_SEGMENT_RE = re.compile(r"(?:[^.!?\n]|\n(?!\s*\n))+")  # a sentence / paragraph piece
_PROSE_WORDS = 12
_PROSE_LOWER = 0.6
# A heading: at a line start, followed by punctuation, or in capitals ("ABSTRACT").
_ABSTRACT_RE = re.compile(
    r"(?im:^\s*(?:abstract|summary)\b)|(?i:\b(?:abstract|summary)\s*[:.—–-])|\bABSTRACT\b")


def _norm(text: str) -> str:
    return normalize_for_match(text)[0]


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP]


def is_title(quote: str, title: str) -> bool:
    """The quote is the title, a title fragment, or the title plus a few header words."""
    q, t = _norm(quote), _norm(title)
    if not q or not t:
        return False
    if fuzz.ratio(q, t) >= _TITLE_RATIO:
        return True
    if q in t and len(_words(q)) >= _MIN_FRAGMENT_WORDS:
        return True
    return (_TITLE_SHARE * len(q) <= len(t) <= len(q)
            and fuzz.partial_ratio(t, q) >= _TITLE_IN_QUOTE)


def _name_words(ref: Reference) -> set[str]:
    """Words of the author names (initials dropped); never the journal's words."""
    return {w for author in ref.authors for w in _WORD_RE.findall(author.lower()) if len(w) > 1}


def reports_data(quote: str) -> bool:
    """Statistics, a comparison or running text: never an author / affiliation block."""
    if _STATS_RE.search(quote):
        return True
    lower = [w for w in _CASED_WORD_RE.findall(quote) if w.islower() and len(w) > 2
             and w not in _STOP and w not in _HEADER_WORDS]
    return len(lower) >= _MAX_LOWER_WORDS


def is_author_block(quote: str, ref: Reference) -> bool:
    """Mostly author names, initials, affiliations or journal / licence boilerplate.

    Once an author's name appears, capitalised words count as names too (the
    reference list gives initials, the paper's byline full first names). The journal's
    words count as header vocabulary only ("transplant" in a result is not a name), and
    a quote with statistics, a comparison or lower-case running text never qualifies.
    """
    raw = [w for w in _CASED_WORD_RE.findall(quote) if w.lower() not in _STOP]
    if len(raw) < _MIN_BLOCK_WORDS or reports_data(quote):
        return False
    names = _name_words(ref)
    vocabulary = _HEADER_WORDS | set(_words(ref.journal or ""))
    named = any(w.lower() in names for w in raw)
    header = [w for w in raw if w.lower() in names or w.lower() in vocabulary
              or len(w) == 1 or w.isdigit() or (named and w[0].isupper())]
    boilerplate = sum(w.lower() in vocabulary for w in raw) >= 2
    return (named or boilerplate) and len(header) >= _BLOCK_SHARE * len(raw)


def header_text(doc: SourceDocument | None) -> str:
    """Full-text page-1 matter before the abstract (its heading or its opening words;
    "" when neither is found)."""
    if doc is None or doc.coverage != "full_text":
        return ""
    scan = doc.full_text[:_HEADER_SCAN_CHARS]
    starts = [m.start() for m in [_ABSTRACT_RE.search(scan)] if m is not None]
    chunk = doc.abstract_chunk
    if chunk is not None and len(opening := chunk.text[:_ABSTRACT_OPENING].strip()) > 20:
        starts.append(scan.find(opening))
    found = [s for s in starts if s > 0]
    return _before_prose(scan[:min(found)]) if found else ""


def _before_prose(text: str) -> str:
    """``text`` up to its first running-text sentence (>= _PROSE_WORDS words, mostly lower
    case): page-1 matter is titles, names and affiliations; a PDF whose abstract is
    extracted after the Introduction must not turn the Introduction into "header"."""
    for match in _SEGMENT_RE.finditer(text):
        words = [w for w in match.group().split() if w[0].isalpha()]
        lower = sum(w[0].islower() for w in words)
        if len(words) >= _PROSE_WORDS and lower >= _PROSE_LOWER * len(words):
            return text[:match.start()]
    return text


def in_header(quote: str, doc: SourceDocument | None) -> bool:
    """The quote is printed in the journal header before the abstract."""
    head = header_text(doc)
    return bool(head.strip()) and validate_quotes([quote], head, _HEADER_SIMILARITY)[0] \
        .found_in_source


def front_matter(quote: str, ref: Reference, doc: SourceDocument | None = None) -> str | None:
    """Why ``quote`` is front matter ("the title", ...), or None when it may be evidence."""
    if ref.title and is_title(quote, ref.title):
        return "the reference's title"
    if is_author_block(quote, ref):
        return "the author or affiliation block"
    if in_header(quote, doc):
        return "the journal header before the abstract"
    return None
