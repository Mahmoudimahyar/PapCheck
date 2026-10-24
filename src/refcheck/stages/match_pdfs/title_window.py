"""Does a reference title align with one stretch of PDF page 1? (re-match evidence)

``title_match`` gives the best-window similarity of the normalised title on page 1
(rapidfuzz partial_ratio_alignment) and whether EVERY key word of the title is in
that window, widened to whole words. Key words match exactly or after a light stem
(plural s/es/ies, -ise/-ize and -our/-or spellings), never by fuzzy similarity: a
fuzzy ratio accepts opposite words that differ by a prefix (coated / uncoated,
hyperglycemia / hypoglycemia), so a companion paper's title would count as aligned.
"""

import re

from rapidfuzz import fuzz

from refcheck.stages.match_pdfs.pdf_profile import normalize_text

TITLE_ALIGNMENT_MIN = 90.0
WINDOW_MARGIN = 15  # chars around the aligned stretch (words cut by its edges)
TITLE_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "via", "its", "their", "are", "was",
    "were", "has", "have", "this", "that", "between", "among", "after", "during",
    "under", "over", "than", "not", "but", "can", "use",
})
_ISE_RE = re.compile(r"is(e|ed|es|ing|ation|ations)$")


def stem(word: str) -> str:
    """Light stem so plural and British/American spellings compare equal."""
    word = _singular(_ISE_RE.sub(r"iz\1", word))
    return word[:-3] + "or" if len(word) > 5 and word.endswith("our") else word


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes", "uses")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def key_words(normalized_title: str) -> list[str]:
    """Numbers and content words (length > 2, not a stopword) of a normalised title."""
    return [w for w in normalized_title.split()
            if w.isdigit() or (len(w) > 2 and w not in TITLE_STOPWORDS)]


def window_words(text: str, start: int, end: int) -> list[str]:
    """Whole words of ``text[start:end]`` widened by the margin to word boundaries."""
    lo = text.rfind(" ", 0, max(0, start - WINDOW_MARGIN)) + 1
    hi = text.find(" ", min(len(text), end + WINDOW_MARGIN))
    return text[lo:hi if hi >= 0 else len(text)].split()


def title_match(title: str, page_variants: list[str]) -> tuple[float, bool]:
    """(best-window similarity 0-100, every title key word is in a window >= the minimum)."""
    wanted = normalize_text(title)
    if not wanted:
        return 0.0, False
    key = {stem(w) for w in key_words(wanted)}
    best, aligned = 0.0, False
    for variant in (v for v in page_variants if v):
        found = fuzz.partial_ratio_alignment(wanted, variant)
        if found is None:
            continue
        window = window_words(variant, found.dest_start, found.dest_end)
        best = max(best, float(found.score))
        aligned = aligned or (found.score >= TITLE_ALIGNMENT_MIN
                              and key <= {stem(w) for w in window})
    return best, aligned
