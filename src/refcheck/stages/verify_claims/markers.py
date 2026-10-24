"""Citation markers inside SOURCE text: "[10, 11]", "(3–5)", "(Smith et al., 2019)".

Used by the secondary-citation check (post_checks.py: a supporting quote that cites
other work) and by its own-statement search (own_statement.py: a sentence that states
the point WITHOUT a marker is the paper's own statement). A lone "(12)" may be a count
and is not a marker; a superscript reference glued to a word ("mice27,28") is one for
the own-statement search only (has_marker), where over-detection is the safe side.
"""

import re

_NAME = r"[A-Z][A-Za-z'’\-]+"
MARKER = (
    r"\[\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\]"  # [12], [10, 11], [3–5]
    r"|\(\s*\d+(?:\s*[-–,;]\s*\d+)+\s*\)"  # (10, 11), (3–5); a lone "(12)" may be a count
    rf"|\({_NAME}(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_NAME})?,?\s+(?:19|20)\d{{2}}[a-z]?"
    r"(?:\s*[;,]\s*[^()]{0,80})?\)"  # (Smith et al., 2019; Lee 2020)
)
MARKER_RE = re.compile(MARKER)
LEADING_MARKER_RE = re.compile(rf"\s*[.,;:]?\s*(?:{MARKER})")
# "mice27", "reported12,13", "shown3–5." (a superscript reference glued to a word)
_SUPERSCRIPT_RE = re.compile(r"[a-z]{3,}\d{1,3}(?:[,–-]\d{1,3})*(?=[\s.,;:)]|$)")
_NARRATIVE_RE = re.compile(
    rf"\b{_NAME}(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_NAME})\s*\(\s*(?:19|20)\d{{2}}[a-z]?\s*\)")


def has_marker(sentence: str) -> bool:
    """Any citation marker, a glued superscript reference or "Smith et al. (2019)"."""
    return bool(MARKER_RE.search(sentence) or _SUPERSCRIPT_RE.search(sentence)
                or _NARRATIVE_RE.search(sentence))
