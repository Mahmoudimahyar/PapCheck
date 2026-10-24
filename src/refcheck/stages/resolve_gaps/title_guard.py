"""Title-similarity guard for search hits.

Title searches (PubMed esearch, CrossRef query, Semantic Scholar search)
always return *something*; accepting the top hit blindly attaches the
wrong paper (and its PDF/abstract) to a reference. A hit is accepted only
if its title is close to the reference title or its DOI matches exactly.
token_set_ratio scores a superset title as 100, so derivative works that
repeat the original title ("Addendum: <title>", "Review of "<title>"",
"Faculty Opinions recommendation of <title>") are rejected explicitly.
"""

import html
import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import TypeVar

from rapidfuzz import fuzz

from refcheck.utils.doi import dois_match

logger = logging.getLogger(__name__)

T = TypeVar("T")

TITLE_SIMILARITY_THRESHOLD = 0.85

_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_NOTICE_RE = re.compile(
    r"^(?:addendum|erratum|errata|corrigendum|correction|retraction|retracted"
    r"|withdrawn|withdrawal|expression of concern|editorial expression of concern"
    r"|notice of retraction|author correction|publisher correction"
    r"|comment on|commentary on|reply to|response to|in reply)\b",
)
# Words that, in front of the original title, mark a derivative work.
_DERIVATIVE_WORDS = frozenset({
    "addendum", "erratum", "errata", "corrigendum", "correction", "retraction",
    "retracted", "withdrawn", "withdrawal", "concern", "comment", "comments",
    "commentary", "reply", "response", "review", "reviews", "recommendation",
    "notice", "letter", "editorial", "re", "opinions",
})


def normalize_title(title: str) -> str:
    """Lowercase, strip markup/accents/punctuation, collapse whitespace."""
    text = html.unescape(_TAG_RE.sub(" ", title or ""))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_WORD_RE.sub(" ", text.lower()).replace("_", " ")
    return _SPACE_RE.sub(" ", text).strip()


def title_similarity(title_a: str, title_b: str) -> float:
    """Normalized token-set similarity in [0, 1] (0 if either is empty)."""
    a, b = normalize_title(title_a), normalize_title(title_b)
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a, b)) / 100.0


def is_notice_title(title: str) -> bool:
    """Addendum / erratum / retraction notice / comment / reply titles."""
    return bool(_NOTICE_RE.match(normalize_title(title)))


def is_derivative_of(ref_title: str, hit_title: str) -> bool:
    """True if the hit is a notice/review/comment about the referenced work."""
    ref, hit = normalize_title(ref_title), normalize_title(hit_title)
    if is_notice_title(hit) and not is_notice_title(ref):
        return True
    anchor = ref[:40]
    pos = hit.find(anchor) if anchor else -1
    if pos <= 0:
        return False
    prefix = set(hit[:pos].split()) - set(ref.split())
    return bool(prefix & _DERIVATIVE_WORDS)


def accept_search_hit(
    ref_title: str,
    ref_doi: str | None,
    hit_title: str,
    hit_doi: str | None,
    source: str,
) -> bool:
    """True if a title-search hit plausibly is the referenced paper."""
    if ref_doi and hit_doi and dois_match(ref_doi, hit_doi):
        return True
    if is_derivative_of(ref_title, hit_title):
        logger.info("Rejected %s hit (derivative work): %r", source, hit_title[:80])
        return False
    score = title_similarity(ref_title, hit_title)
    if score >= TITLE_SIMILARITY_THRESHOLD:
        return True
    logger.info(
        "Rejected %s hit (title similarity %.2f < %.2f): ref=%r hit=%r",
        source, score, TITLE_SIMILARITY_THRESHOLD,
        ref_title[:80], hit_title[:80],
    )
    return False


def pick_best_hit(
    ref_title: str, hits: Sequence[T], title_of: Callable[[T], str],
) -> T | None:
    """Most similar non-derivative hit; else the first hit (guard decides)."""
    best: T | None = None
    best_score = -1.0
    for hit in hits:
        title = title_of(hit)
        if is_derivative_of(ref_title, title):
            continue
        score = title_similarity(ref_title, title)
        if score > best_score:
            best, best_score = hit, score
    if best is not None:
        return best
    return hits[0] if hits else None
