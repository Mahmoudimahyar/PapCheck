"""Is a fetched abstract good enough to keep looking no further?

Enrichment treats a stub (under 300 characters, a single short sentence, or
the title with little else) as missing and tries the next source, because the
verify stage will not let such an abstract stand in for an unusable PDF
(verify_claims/source_fallback.judgeable_abstract, V5.6 E3). Stages do not
import each other, so the same rule is restated here; keep the two in step.
A stub is still kept when no source has anything better (MIN_ABSTRACT_CHARS).
"""

import re

MIN_ABSTRACT_CHARS = 50  # shorter than this is no abstract at all
MIN_JUDGEABLE_CHARS = 300
SINGLE_SENTENCE_WORDS = 50  # a single sentence this long is a real (structured) abstract
_TITLE_SLACK_CHARS = 100  # an "abstract" this close to the title adds nothing
_SENTENCE_END_RE = re.compile(r"(?P<word>[\w.]*)[.!?](?=\s+\S)")
_ABBREVIATIONS = frozenset({"al", "e.g", "i.e", "eg", "ie", "vs", "fig", "figs", "ref", "refs",
                            "approx", "ca", "cf", "no", "nos", "et", "resp", "incl"})


def usable_abstract(text: str | None) -> bool:
    """At least MIN_ABSTRACT_CHARS of text (better than nothing)."""
    return len((text or "").strip()) >= MIN_ABSTRACT_CHARS


def judgeable_abstract(text: str | None, title: str | None = None) -> bool:
    """A full abstract: long enough, more than one sentence, more than the title."""
    clean = " ".join((text or "").split())
    if len(clean) < MIN_JUDGEABLE_CHARS:
        return False
    if len(clean.split()) < SINGLE_SENTENCE_WORDS and not _sentence_ends(clean):
        return False
    heading = " ".join((title or "").lower().split()).rstrip(".")
    return not heading or not (heading in clean.lower()
                               and len(clean) - len(heading) < _TITLE_SLACK_CHARS)


def _sentence_ends(text: str) -> bool:
    """A sentence end followed by more text (not after an abbreviation or an initial)."""
    for match in _SENTENCE_END_RE.finditer(text):
        word = match.group("word").lower().strip(".")
        if word not in _ABBREVIATIONS and not (len(word) == 1 and word.isalpha()):
            return True
    return False


def choose_abstract(
    current: str | None, title: str | None, candidates: list[tuple[str, str]],
) -> tuple[str, str] | None:
    """(source, text) to store, or None to keep the current abstract.

    The first judgeable candidate (in preference order) replaces a current
    abstract that is not judgeable; failing that, the first usable candidate
    fills an empty (or sub-usable) one.
    """
    if judgeable_abstract(current, title):
        return None
    for source, text in candidates:
        if judgeable_abstract(text, title):
            return source, text
    if usable_abstract(current):
        return None
    for source, text in candidates:
        if usable_abstract(text):
            return source, text
    return None
