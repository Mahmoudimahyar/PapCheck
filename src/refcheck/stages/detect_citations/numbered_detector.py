"""Detect numbered citation styles: [N], [N-M], superscript, (N)."""

import re

from refcheck.models.citation import CitationInstance

# [1], [1,2,3], [1-3], [1, 3-5, 7]
_BRACKET_RE = re.compile(
    r"\[(\d+(?:\s*[,;\-–—]\s*\d+)*)\]"
)

# Superscript unicode: ¹²³⁴⁵⁶⁷⁸⁹⁰
_SUPER_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUPER_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+(?:[,\-–—][⁰¹²³⁴⁵⁶⁷⁸⁹]+)*")


def detect_numbered_bracket(
    text: str, para_idx: int, section: str,
) -> list[CitationInstance]:
    """Detect [1], [1,2,3], [1-3] style citations."""
    results: list[CitationInstance] = []
    for m in _BRACKET_RE.finditer(text):
        raw = m.group(0)
        numbers = expand_number_range(m.group(1))
        if not numbers:
            continue
        # Create one CitationInstance per number (split later)
        results.append(CitationInstance(
            raw_marker=raw,
            style="numbered_bracket",
            paragraph_index=para_idx,
            char_start=m.start(),
            char_end=m.end(),
            section_heading=section,
            number=numbers[0],
        ))
    return results


def detect_numbered_superscript(
    text: str, para_idx: int, section: str,
) -> list[CitationInstance]:
    """Detect superscript number citations (unicode superscripts)."""
    results: list[CitationInstance] = []
    for m in _SUPER_RE.finditer(text):
        raw = m.group(0)
        ascii_nums = raw.translate(_SUPER_MAP)
        numbers = expand_number_range(ascii_nums)
        if not numbers:
            continue
        results.append(CitationInstance(
            raw_marker=raw,
            style="numbered_superscript",
            paragraph_index=para_idx,
            char_start=m.start(),
            char_end=m.end(),
            section_heading=section,
            number=numbers[0],
        ))
    return results


def expand_number_range(range_str: str) -> list[int]:
    """Expand '1, 3-5, 7' into [1, 3, 4, 5, 7]."""
    ids: list[int] = []
    parts = re.split(r"\s*[,;]\s*", range_str.strip())
    for part in parts:
        part = part.strip()
        range_match = re.match(r"(\d+)\s*[\-–—]\s*(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if end >= start and (end - start) < 100:
                ids.extend(range(start, end + 1))
        elif part.isdigit():
            ids.append(int(part))
    return ids
