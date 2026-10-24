"""What kind of figure a plain number is: its statistic label and the words after it.

Used by source_numbers.figures_only_absent to decide whether an abstract states a
claim's figure differently ("180 adult patients" vs the claim's "240 patients",
"HR 0.85" vs "HR 0.72", "58 yr" vs "65 years") or merely lacks it:

* label: the statistic named right before the figure ("HR 0.72", "p < 0.001",
  "n = 40"), from a fixed list so ordinary words are never labels;
* nouns: up to three words right after the figure (a noun after up to two
  adjectives), stopping at a stopword or punctuation, plus a time word right
  before it ("day 28", "week-12"), normalised so unit abbreviations and plurals
  compare equal (yr/yrs/years -> year, d/days -> day);
* object: when the nouns stop at "in / of / for / on", up to three words after it
  (an article skipped): "50% reduction in graft rejection" -> ["graft", "rejection"]
  (V5.6, number_rule.py: "a 20% reduction in IL-6" is not the same kind of figure);
* bound: "lower" for "more than / over / at least / > X", "upper" for "less than /
  under / up to / < X" right before the figure (V5.6, number_rule.py);
* scale: a multiplier word after the figure ("9.5 million") multiplies its value.
"""

import re

_LABELS = frozenset({
    "hr", "ahr", "or", "aor", "rr", "arr", "irr", "p", "ci", "n", "sd", "se", "sem",
    "iqr", "md", "smd", "wmd", "auc", "r", "nnt", "rho",
})
_LABEL_RE = re.compile(r"(?<![\w-])([A-Za-z]{1,4})\s*(?:[=<>~:]+\s*)?\(?$")
_LABEL_WINDOW = 12
_WORD_RE = re.compile(r"(?:\s+|-)?([A-Za-z][A-Za-z-]*)")
_MAX_NOUNS = 3
_TIME_BEFORE_RE = re.compile(
    r"(?<![\w-])(days?|weeks?|months?|years?|hours?|d|wk|mo|yr|h)[\s-]*$", re.IGNORECASE)
_STOPWORDS = frozenset({
    "a", "an", "the", "in", "of", "for", "and", "or", "to", "at", "with", "vs", "versus",
    "per", "on", "from", "by", "was", "were", "is", "are", "than", "after", "before",
    "each", "who", "that", "which", "had", "has", "have",
})
_ABBREVIATIONS = {
    "y": "year", "yr": "year", "yrs": "year", "wk": "week", "wks": "week",
    "mo": "month", "mos": "month", "d": "day", "h": "hour", "hr": "hour", "hrs": "hour",
    "min": "minute", "mins": "minute", "pt": "patient", "pts": "patient",
}
_LOWER_RE = re.compile(r"(?:more\s+than|greater\s+than|over|above|exceed(?:s|ing|ed)?|at\s+least"
                       r"|>=?)\s*(?:approximately\s+|about\s+|~\s*)?$", re.IGNORECASE)
_UPPER_RE = re.compile(r"(?:less\s+than|fewer\s+than|under|below|up\s+to|at\s+most|<=?)"
                       r"\s*(?:approximately\s+|about\s+|~\s*)?$", re.IGNORECASE)
_BOUND_WINDOW = 30
_OBJECT_STOPS = frozenset({"in", "of", "for", "on"})
_ARTICLE_RE = re.compile(r"\s+(?:the|a|an)\b", re.IGNORECASE)
MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def normalize_word(word: str) -> str:
    """Lower case, unit abbreviations expanded, a plural "s" dropped (years -> year)."""
    w = _ABBREVIATIONS.get(word.lower(), word.lower())
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def label_before(text: str, start: int) -> str:
    """The statistic label right before a figure ("hr", "p", "n"), else ""."""
    match = _LABEL_RE.search(text[max(0, start - _LABEL_WINDOW):start])
    label = match.group(1).lower() if match else ""
    return label if label in _LABELS else ""


def nouns_around(text: str, start: int, end: int) -> list[str]:
    """Up to three normalised words right after a figure (stopping at a stopword), plus
    a time word right before it ("day 28" -> ["day"])."""
    before = _TIME_BEFORE_RE.search(text[max(0, start - _LABEL_WINDOW):start])
    nouns = [normalize_word(before.group(1))] if before else []
    return nouns + nouns_after(text, end)


def _words_from(text: str, pos: int) -> tuple[list[str], str, int]:
    """Up to three normalised words from ``pos``; the stopword that ended them (or "") and
    the position after it."""
    words: list[str] = []
    while len(words) < _MAX_NOUNS and (match := _WORD_RE.match(text, pos)):
        word = match.group(1).lower()
        if word in _STOPWORDS:
            return words, word, match.end()
        words.append(normalize_word(word))
        pos = match.end()
    return words, "", pos


def nouns_after(text: str, end: int) -> list[str]:
    """Up to three normalised words right after a figure, stopping at a stopword."""
    return _words_from(text, end)[0]


def object_after(text: str, end: int) -> list[str]:
    """The words after "in / of / for / on" that ends a figure's nouns (module doc)."""
    _, stop, pos = _words_from(text, end)
    if stop not in _OBJECT_STOPS:
        return []
    article = _ARTICLE_RE.match(text, pos)
    return _words_from(text, article.end() if article else pos)[0]


def bound_before(text: str, start: int) -> str:
    """'lower' / 'upper' when the figure is stated as a bound ("more than 10,000"), else ''."""
    before = text[max(0, start - _BOUND_WINDOW):start]
    if _LOWER_RE.search(before):
        return "lower"
    return "upper" if _UPPER_RE.search(before) else ""


def scaled(value: float, nouns: list[str]) -> tuple[float, list[str]]:
    """The value times a multiplier word right after it ("9.5 million"), and the other
    words (the multiplier says nothing about the kind of figure)."""
    if nouns and nouns[0] in MULTIPLIERS:
        return value * MULTIPLIERS[nouns[0]], nouns[1:]
    return value, nouns
