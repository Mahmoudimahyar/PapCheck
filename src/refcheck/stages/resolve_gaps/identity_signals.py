"""Hard identity signals read from a PDF's first pages: printed DOIs, title numbers.

A PDF of the wrong paper can share almost every title word and the first
author with the cited one (the 2020 edition of an annual report attached to a
reference for the 2017 edition). Two signals separate them: the DOI printed in
the PDF, and the numbers inside the title ("2017 Annual Data Report").
"""

import re

from refcheck.stages.resolve_gaps.title_guard import normalize_title
from refcheck.utils.doi import normalize_doi

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>\[\]{}]+", re.IGNORECASE)
_DOI_TRAILING = ".,;:"
# Preprint servers: a preprint is another version of the same work, not another paper.
_PREPRINT_PREFIXES = (
    "10.1101/", "10.21203/", "10.20944/", "10.2139/", "10.48550/", "10.31219/",
    "10.31234/", "10.26434/", "10.36227/", "10.22541/",
)
_NUMBER_RE = re.compile(r"^\d{1,4}$")
_CONTEXT_WORDS = 3
_MIN_CONTEXT_CHARS = 8


def find_dois(text: str) -> list[str]:
    """Normalized DOIs printed in text, in order of appearance, without duplicates."""
    found: list[str] = []
    for match in _DOI_RE.finditer(text or ""):
        doi = _trim(match.group(0))
        if doi and doi not in found:
            found.append(doi)
    return found


def _trim(raw: str) -> str:
    """Drop sentence punctuation and unbalanced closing brackets after a DOI.

    Parentheses inside a DOI are legal ("10.1016/S0140-6736(20)30183-5"), so a
    trailing ")" is removed only when it closes a bracket opened before the DOI.
    """
    doi = raw.rstrip(_DOI_TRAILING)
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(_DOI_TRAILING)
    return normalize_doi(doi)


def dois_related(doi_a: str, doi_b: str) -> bool:
    """Same DOI, or one extends the other (chapter vs book, article vs its SI file)."""
    a, b = normalize_doi(doi_a), normalize_doi(doi_b)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return long_.startswith(short) and not long_[len(short)].isalnum()


def doi_conflict(ref_doi: str | None, page_dois: list[str], page_text: str) -> str | None:
    """A DOI printed in the PDF that is not the reference's, when the reference's is absent.

    Returns the conflicting DOI, or None (no reference DOI, no printed DOI, the
    reference DOI is printed too, or the only other DOIs are preprint versions).
    """
    if not ref_doi or not page_dois:
        return None
    wanted = normalize_doi(ref_doi)
    if any(dois_related(wanted, doi) for doi in page_dois):
        return None
    if wanted in _squash(page_text):
        return None  # printed with a line break / hyphen inside it
    others = [doi for doi in page_dois if not doi.startswith(_PREPRINT_PREFIXES)]
    return others[0] if others else None


def _squash(text: str) -> str:
    """Lowercase text without whitespace, so broken-up DOIs are still found."""
    return re.sub(r"\s+", "", (text or "").lower())


def title_number_conflict(title: str, page_text: str) -> tuple[str, str] | None:
    """(reference number, PDF number) when the title appears with a different number.

    For every number in the reference title, the surrounding title words form
    a frame ("registry <N> annual data report"). A conflict needs the frame
    with another number on the page and never with the reference's own number.
    The number needs title words on both sides, so a mis-parsed "title" such
    as "Synth Nano 14, 301-309. doi: ..." (journal, volume, pages) never counts.
    """
    if find_dois(title):
        return None  # not a real title (citation tail parsed as title)
    tokens = normalize_title(title).split()
    page = " " + normalize_title(page_text) + " "
    for i, token in enumerate(tokens):
        if not _NUMBER_RE.match(token):
            continue
        left = _context(tokens[max(0, i - _CONTEXT_WORDS):i][::-1])[::-1]
        right = _context(tokens[i + 1:i + 1 + _CONTEXT_WORDS])
        if not left or not right or len(" ".join(left + right)) < _MIN_CONTEXT_CHARS:
            continue
        pattern = " ".join([*map(re.escape, left), r"(\d{1,4})", *map(re.escape, right)])
        numbers = {m.group(1) for m in re.finditer(rf" {pattern} ", page)}
        if numbers and token not in numbers:
            return token, sorted(numbers)[0]
    return None


def _context(words: list[str]) -> list[str]:
    """Leading run of non-number words (a frame stops at the next number)."""
    run: list[str] = []
    for word in words:
        if _NUMBER_RE.match(word):
            break
        run.append(word)
    return run
