"""Colour claims of a figure legend or sentence (V5.8 G2): "<marker> (green)" -> {marker: green}.

Recognised forms (case-insensitive colour words, figure_colors.COLOUR_WORDS):

* "CD8⁺ (green)", "CD8⁺ T cells (in green)";
* "CD8 in red", "CD8⁺ cells are shown / labelled / stained in red";
* "red: CD8", "red = CD8";
* "green-labelled CD8", "red-stained Ki67";
* "green (signal / staining / fluorescence) indicates / denotes / represents QDX";
* "CD8/CD4/DAPI (red/green/blue)" (equal-length slash lists).

Only MARKER-LIKE names count (``marker_like``: two capitals or a digit and a letter:
CD8, GFP, Ki67, FoxP3, QDX), so "with (red) or without (black)", "red blood cells" or
"green fluorescent protein" are no claims. A marker given two different colours in the
same text makes the text ambiguous: no claims at all (never flag on uncertainty).
Markers are compared by ``marker_key``: lower case, superscript / trailing signs and
"-positive" removed, hyphens and dots dropped ("CD8⁺" = "CD8+" = "cd8"; "PD-L1" = "PDL1").
"""

import re

from pydantic import BaseModel

from refcheck.stages.verify_claims.figure_colors import COLOUR_PATTERN, COLOUR_WORDS

_C = rf"(?P<c>{COLOUR_PATTERN})"
_M = r"(?P<m>[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9][⁺⁻+\-]*|[A-Za-z0-9][⁺⁻+]*)"
_CELLS = r"(?:\s+(?:T\s+)?(?:cells?|signals?|staining|channel))?"
_VERB = (r"(?:(?:is|are)\s+)?"
         r"(?:shown|labell?ed|stained|marked|depicted|highlighted|coloured|colored)")
_FORMS: tuple[re.Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    rf"(?<![\w-]){_M}{_CELLS}\s*\(\s*(?:in\s+)?{_C}\s*\)",
    rf"(?<![\w-]){_M}{_CELLS}\s+(?:{_VERB}\s+)?in\s+{_C}\b",
    rf"\b{_C}\s*[:=]\s*{_M}(?![\w-])",
    rf"\b{_C}[- ](?:labell?ed|stained|coloured|colored)\s+{_M}(?![\w-])",
    rf"\b{_C}(?:\s+(?:signal|staining|fluorescence|channel))?\s+"
    rf"(?:indicates|denotes|represents|marks|shows)\s+{_M}(?![\w-])",
))
_LISTS = re.compile(
    rf"(?<![\w-])(?P<ms>[A-Za-z0-9][\w.\-⁺⁻+]*(?:\s*/\s*[A-Za-z0-9][\w.\-⁺⁻+]*)+)\s*"
    rf"\(\s*(?P<cs>(?:{COLOUR_PATTERN})(?:\s*/\s*(?:{COLOUR_PATTERN}))+)\s*\)", re.IGNORECASE)
_TRAILING = re.compile(r"(?:[⁺⁻+\-*°'’]+|-?positive)$", re.IGNORECASE)
_STOP = frozenset({"in", "and", "or", "with", "without", "the", "of", "to", "is", "are"})


class ColourClaim(BaseModel):
    """One marker the text gives a colour."""

    marker: str  # as written ("CD8⁺")
    colour: str  # the colour word, lower case ("green")


def marker_key(token: str) -> str:
    """Comparable form of a marker name (module doc); "" for no marker."""
    text = _TRAILING.sub("", token.strip().strip("()[],;:"))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def marker_like(token: str) -> bool:
    """A marker name: two capitals, or a digit and a letter (module doc)."""
    text = _TRAILING.sub("", token.strip())
    if text.lower() in _STOP or text.lower() in COLOUR_WORDS:
        return False
    capitals = sum(ch.isupper() for ch in text)
    has_digit, has_letter = any(ch.isdigit() for ch in text), any(ch.isalpha() for ch in text)
    return has_letter and (capitals >= 2 or has_digit)


def _found(text: str) -> list[tuple[str, str]]:
    pairs = [(m.group("m"), m.group("c")) for form in _FORMS for m in form.finditer(text)]
    for match in _LISTS.finditer(text):
        names = [n.strip() for n in match.group("ms").split("/")]
        colours = [c.strip() for c in match.group("cs").split("/")]
        if len(names) == len(colours):
            pairs.extend(zip(names, colours, strict=True))
    return pairs


def colour_claims(text: str) -> list[ColourClaim]:
    """The marker colours ``text`` states, in order of first mention (module doc)."""
    by_key: dict[str, ColourClaim] = {}
    for name, colour in _found(text or ""):
        key = marker_key(name)
        if not key or not marker_like(name):
            continue
        claim = ColourClaim(marker=_TRAILING.sub("", name) + _sign(name), colour=colour.lower())
        held = by_key.setdefault(key, claim)
        if held.colour != claim.colour:
            return []  # one marker, two colours: ambiguous
    return sorted(by_key.values(), key=lambda c: (text or "").find(c.marker.rstrip("⁺⁻+")))


def _sign(name: str) -> str:
    """Keep a "+" sign for display ("CD8⁺"), never a stray hyphen."""
    tail = _TRAILING.search(name)
    return tail.group(0) if tail and any(s in tail.group(0) for s in "⁺+") else ""
