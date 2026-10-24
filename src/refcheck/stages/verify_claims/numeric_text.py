"""Text clean-up before numbers are compared (taxonomy guard 1, numeric artefacts).

Two kinds of false "numbers not in the source" flags came from the text, not the
paper (V4.9 gold review):

* comparison symbols that PDF extraction drops or mangles: unicode forms are
  mapped to ASCII (">=", "<=", "+/-", "~") and, on the SOURCE side only, glyphs
  that symbol fonts turn into letters glued to the number ("Z65"/"r0.05" for
  ">=65"/"<=0.05", "³65" for ">=65") are separated so the figure is found;
* digits inside chemical, gene, locant and cell-marker names (α-1,3; β-1,4;
  1,25-dihydroxy; 5-HT; 6-OHDA; 5-FU; 3-D; 3-dimensional; 5-fluorouracil) are
  masked so they are never read as quantities. Names glued to letters (IL-6,
  CD4+, TGF-β1, Th17, 3D) are already skipped by the number patterns; a strain's
  digit after a slash (C57BL/6, DBA/2) is masked too;
* figures glued to their unit ("10mg", "8-mm", "24h", "5x", "60days") are split
  from it on both sides, so they compare with "10 mg" (V5.6, E7); on the SOURCE side
  a figure glued after a lower-case word by PDF extraction ("estimated to be14.7")
  is split too (a capitalised or mixed name such as IL6, Th17, Foxp3 is left alone);
* thousands written with a space ("10 000", thin / narrow no-break space too) are one
  figure, not "10" and "000". A thin, narrow or no-break space always joins; a plain
  space joins on the claim side only, because in PDF text it also separates table
  cells ("12 145 167" is three figures): the SOURCE side keeps the split figures and
  ``with_joined_figures`` adds each joined one (with the words after it) as well.

A "<digit>-<capitals>" name needs two or more capitals or a capital + digit (5-HT,
6-OHDA, 5-FU); a single-letter or all-caps unit stays a quantity (a 7-T scanner,
37-C, 10-K, 2-L, 50-HU, 6-MV, 24-HR, 15-ML, 20-MG, 30-HZ). Only 1- to 4-dimensional
(= 1D-4D, a shape) is masked; a "128-dimensional" vector is a count. A hyphenated
timepoint ("day-28", "week-12", "pre-2010") is a figure / year, not a name: its
hyphen becomes a space first.
"""

import re

_COMPARISONS: dict[str, str] = {
    "≥": ">=", "⩾": ">=", "≧": ">=", "≤": "<=", "⩽": "<=", "≦": "<=",
    "＞": ">", "＜": "<", "±": "+/-", "∓": "+/-", "∼": "~", "〜": "~", "≈": "~",
}
_COMPARISON_RE = re.compile("|".join(map(re.escape, _COMPARISONS)))
# Symbol-font glyphs extracted as a letter or superscript glued to the figure (source side).
# Glued to a lone "p" too: "pr0.05" is "p<=0.05".
_MANGLED_GE_RE = re.compile(r"(?:(?<=[\s(\[])|(?<=\bp)|^)(?:Z|³)(?=\d)")
_MANGLED_LE_RE = re.compile(r"(?:(?<=[\s(\[])|(?<=\bp)|^)r(?=\d)")
_CHEM_PREFIX = (
    r"(?:di|tri)?(?:hydroxy|deoxy|methyl|ethyl|amino|fluoro|chloro|bromo|iodo|nitro|oxo|"
    r"keto|phospho|acetyl|mercapto|azido|thio|carboxy|aza)"
)
# All-caps units that look like a capitals name after "<digit>-" (50-HU, 10-IU, 6-MV).
_CAPS_UNITS = (r"(?:IU|HU|MV|KV|GB|MB|TB|KB|HRS?|MIN|SEC|DAYS?|WKS?|ML|DL|MG|KG|UG|NG|PG|"
               r"MM|CM|NM|UM|K?HZ|MHZ|GHZ|KDA|KPA|MPA|GY|MEQ|M?MOL)")
_NAME_DIGIT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<=[^\W\d_]-)\d+(?:,\d+)*"),  # α-1,3 / β-1,4 / type-2 (any script)
    re.compile(r"(?<![\w.,])\d{1,2}(?:,\d{1,2})+(?=-[^\W\d_])"),  # 1,25-dihydroxy locants
    re.compile(r"(?<=[^\W\d_],)\d{1,2}(?=-[^\W\d_])"),  # 1α,25-dihydroxy
    # 5-HT, 6-OHDA, 5-FU: 2+ capitals or capital + digit (not 7-T, 37-C, 50-HU)
    re.compile(rf"(?<![\w.])\d{{1,2}}(?=-(?!{_CAPS_UNITS}\b)[A-Z][A-Z0-9]{{1,5}}\b)"),
    re.compile(r"(?<![\w.])[1-4](?=-(?:D|[Dd]imensional)\b)"),  # 3-D, 2-dimensional (not 3-d)
    re.compile(rf"(?<![\w.])\d{{1,2}}(?=-{_CHEM_PREFIX})", re.IGNORECASE),  # 5-fluorouracil
    re.compile(r"(?<=[A-Z]/)\d{1,2}(?=[A-Z]?\b)"),  # C57BL/6, C57BL/6J, DBA/2 (strains)
)
# Units a figure may be glued to ("10mg", "8-mm"); case-sensitive, so 3D / 5-HT stay names.
_GLUED_UNITS = (
    "mg/kg|mg/mL|mg/ml|µg/mL|µg/ml|ng/mL|ng/ml|mmHg|kDa|kPa|MPa|GPa|Pa|mg|kg|µg|ng|pg|mL|ml|µL|µl"
    "|mm|cm|nm|µm|Gy|hrs?|h|min|days?|d|wks?|weeks?|mo|months?|yrs?|years?|fold|x"
    "|thousand|million|billion"
)
_GLUED_UNIT_RE = re.compile(
    rf"(?<![\w.])(\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)-?"
    rf"(?=(?:{_GLUED_UNITS})(?![A-Za-z0-9]))")
# A figure glued after a lower-case word by PDF extraction ("be14.7"): source side only.
_GLUED_WORD_RE = re.compile(r"(?<![A-Za-z0-9])([a-z]{2,})(?=\d)")


# "day-28", "weeks-12", "pre-2010": a timepoint word glued to a figure by a hyphen.
_TIMEPOINT_RE = re.compile(r"\b((?:day|week|month|year|hour)s?|pre|post|mid)-(?=\d)",
                           re.IGNORECASE)
# Thousands separated by a no-break / thin / narrow no-break space (always one figure) or
# by a plain space (one figure in a claim; in source text also table cells, module doc).
_GROUP_SPACES = "   "
_THIN_GROUPS_RE = re.compile(rf"(?<![\d.,])\d{{1,3}}(?:[{_GROUP_SPACES}]\d{{3}})+(?![\d])")
_SPACED_GROUPS_RE = re.compile(rf"(?<![\d.,])\d{{1,3}}(?:[ {_GROUP_SPACES}]\d{{3}})+(?![\d])")
_JOINED_CONTEXT = 60  # chars after a joined figure kept with it (its words, unit)


def join_digit_groups(text: str, plain_space: bool = True) -> str:
    """"10 000" -> "10000" (thin / no-break spaces always; plain spaces when asked)."""
    pattern = _SPACED_GROUPS_RE if plain_space else _THIN_GROUPS_RE
    return pattern.sub(lambda m: re.sub(r"\D", "", m.group()), text)


def with_joined_figures(text: str) -> str:
    """Source text plus, after a blank line, each plain-space grouped figure joined with
    the words after it (". 10000 patients received ..."), one per line (module doc). The
    leading ". " keeps the previous line out of the figure's label / bound / time word."""
    extra = [". " + re.sub(r"\D", "", m.group())
             + text[m.end():m.end() + _JOINED_CONTEXT].split("\n")[0]
             for m in _SPACED_GROUPS_RE.finditer(text) if " " in m.group()]
    return text if not extra else text + "\n\n" + "\n".join(extra)


def normalize_comparisons(text: str, source: bool = False) -> str:
    """Unicode comparison symbols -> ASCII; on source text also unglue mangled glyphs."""
    text = _COMPARISON_RE.sub(lambda m: _COMPARISONS[m.group()], text)
    if source:
        text = _MANGLED_GE_RE.sub(">=", text)
        text = _MANGLED_LE_RE.sub("<=", text)
    return text


def unglue_figures(text: str, source: bool = False) -> str:
    """Split figures from a glued unit ("10mg" -> "10 mg"); on source text also from a
    lower-case word glued before them ("be14.7" -> "be 14.7")."""
    if source:  # first, so "be14.7million" becomes "be 14.7 million"
        text = _GLUED_WORD_RE.sub(r"\1 ", text)
    return _GLUED_UNIT_RE.sub(r"\1 ", text)


def mask_name_digits(text: str) -> str:
    """Replace the digits of chemical / gene / locant names with "x" (never quantities)."""
    for pattern in _NAME_DIGIT_RES:
        text = pattern.sub(lambda m: re.sub(r"\d", "x", m.group()), text)
    return text


def quantity_text(text: str, source: bool = False) -> str:
    """Text ready for number extraction (spaced thousands joined, symbols normalised,
    timepoints unhyphenated, name digits masked, figures split from glued units / words);
    on source text the plain-space grouped figures are also added joined (module doc)."""
    text = join_digit_groups(with_joined_figures(text) if source else text,
                             plain_space=not source)
    text = _TIMEPOINT_RE.sub(r"\1 ", normalize_comparisons(text, source))
    return unglue_figures(mask_name_digits(text), source)
