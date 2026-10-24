"""Abbreviation definitions from a text's own "long form (SF)" pairs (V5.7 #5).

Schwartz & Hearst (2003): a short form is a 2-10 character parenthesised token with a
letter, starting with a letter or digit; its long form is the words just before the
parenthesis (at most min(|SF| + 5, 2 * |SF|) words) whose characters match the short
form's letters from right to left, the first letter starting a word. Used to make the
co-cited union's about-check see "foreign body response (FBR) reduction" and "the
foreign body reaction (FBR)" as the same thing (clear_rules.about_loose). Pure text: no
model, no network.
"""

import re

_PAIR = re.compile(r"((?:[^\s()]+\s+){1,12}?)\(\s*([^\s()]{2,10})\s*\)")
_WORD = re.compile(r"[^\W_]+")


def _valid_short(short: str) -> bool:
    return short[0].isalnum() and any(c.isalpha() for c in short) and len(short.split()) == 1


def best_long_form(short: str, before: str) -> str | None:
    """The long form of ``short`` at the end of ``before`` (Schwartz-Hearst), else None."""
    words = before.split()
    limit = min(len(short) + 5, 2 * len(short))
    text = " ".join(words[-limit:])
    s_idx, l_idx = len(short) - 1, len(text) - 1
    while s_idx >= 0:
        c = short[s_idx].lower()
        if not c.isalnum():
            s_idx -= 1
            continue
        while l_idx >= 0 and (text[l_idx].lower() != c or (
                s_idx == 0 and l_idx > 0 and text[l_idx - 1].isalnum())):
            l_idx -= 1
        if l_idx < 0:
            return None
        l_idx -= 1
        s_idx -= 1
    start = text.rfind(" ", 0, l_idx + 1) + 1
    long_form = text[start:].strip(" ,;:")
    return long_form if len(long_form) > len(short) else None


def definitions(text: str) -> dict[str, str]:
    """Short form (lower case) -> long form, for every "long form (SF)" pair in ``text``."""
    found: dict[str, str] = {}
    for match in _PAIR.finditer(text or ""):
        short = match.group(2).strip(".,;:")
        if len(short) < 2 or not _valid_short(short):
            continue
        long_form = best_long_form(short, match.group(1))
        if long_form and short.lower() not in found:
            found[short.lower()] = long_form
    return found


def expand(text: str, context: str) -> str:
    """``text`` with each short form defined in ``context`` followed by its long form."""
    table = definitions(context)
    if not table:
        return text

    def _sub(match: re.Match[str]) -> str:
        word = match.group(0)
        long_form = table.get(word.lower())
        return f"{word} {long_form}" if long_form else word

    return _WORD.sub(_sub, text)
