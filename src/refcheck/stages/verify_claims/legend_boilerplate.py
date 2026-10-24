"""Figure-legend boilerplate that is not panel content (V5.6, credit panels).

A credit's panel text becomes the pair's CITED FOR (credit.py), so it must hold what
the panel shows, not the legend's statistics conventions: significance thresholds
("*p < 0.05", "**P < 0.01 versus control"), group sizes ("(n = 3 per group)"), scale
bars ("Scale bar = 200 µm"), "mean ± SEM" and error-bar statements. Their figures
would otherwise be compared with the source's own thresholds and group sizes (the
number rule, the missing-number and quoted-number notes) and turn a correct credit
into a partial. ``strip_boilerplate`` drops such clauses inside parentheses ("(top;
p = 0.001)" -> "(top)"), whole statistics parentheticals and boilerplate segments
(split at ". " / "; " outside parentheses).
"""

import re

# "; p = 0.001" / ", n = 6 mice" inside a parenthesis that also says something else
_STAT_CLAUSE_RE = re.compile(
    r"\s*[;,]\s*(?:\**\s*[pP]\s*[<>=≤≥]\s*[\d.]+|[nN]\s*=\s*\d+(?:\s+[A-Za-z]+){0,3})"
    r"(?=\s*[);,])")
# "(n = 3 per group)", "(*p < 0.05)", "(**P < 0.01 vs control)", "(p = 0.002)"
_STAT_PARENS_RE = re.compile(
    r"\s*\((?:[^()]*?\b[nN]\s*=\s*\d[^()]*|\s*\**\s*[pP]\s*[<>=≤≥][^()]*)\)")
_BOILERPLATE_RE = re.compile(
    r"^\W*(?:\*+\s*)?[pP]\s*[<>=≤≥]"  # *p < 0.05, **p < 0.01
    r"|^\W*[nN]\s*=\s*\d"  # n = 6 mice per group
    r"|\bscale\s+bars?\b|\berror\s+bars?\b"
    r"|\bmeans?\s*(?:±|\+/-|\(?\s*SEM|\(?\s*SD|and\s+(?:SEM|SD|s\.?e\.?m|s\.?d|standard))"
    r"|^\W*(?:data|values|results)\s+(?:are|were|is)\s+(?:presented|expressed|shown|given)"
    r"\s+as\b"
    r"|^\W*(?:ns|n\.s\.)\s*[,=:]?\s*not\s+significant",
    re.IGNORECASE)


def segments(text: str) -> list[str]:
    """``text`` split after ". " / "; " outside parentheses (never inside "0.05")."""
    out: list[str] = []
    depth, start = 0, 0
    for i, char in enumerate(text):
        depth = max(0, depth + {"(": 1, ")": -1}.get(char, 0))
        if depth == 0 and char in ".;" and text[i + 1:i + 2].isspace():
            out.append(text[start:i + 1].strip())
            start = i + 1
    return [s for s in [*out, text[start:].strip()] if s]


def strip_boilerplate(text: str) -> str:
    """``text`` without statistics clauses / parentheticals and boilerplate segments."""
    text = _STAT_PARENS_RE.sub("", _STAT_CLAUSE_RE.sub("", text))
    return " ".join(seg for seg in segments(text) if not _BOILERPLATE_RE.search(seg))
