"""Frozen copy of the pre-V5 section_finder ranking, for retrieval_eval comparisons.

Mirrors `section_finder.find_relevant_sections_with_headings` as of V2
(keyword-overlap paragraph scoring, top-5 within 24,000 chars, whole text
for sources under 30,000 chars), applied to plain text instead of a PDF.
"""

import re

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "and", "or",
    "but", "if", "than", "that", "which", "who", "whom", "this", "these",
    "those", "it", "its", "of", "in", "to", "for", "with", "on", "at",
    "by", "from", "as", "into", "about", "between", "through", "during",
    "before", "after", "not", "no", "nor", "so", "very", "also", "both",
    "each", "more", "most", "other", "some", "such", "only", "own",
    "same", "then", "there", "here", "when", "where", "how", "all", "any",
    "et", "al",
})
_MIN_SCORE = 0.1
_SHORT_CHARS = 30000
_MAX_CONCAT_CHARS = 24000
_MAX_SECTIONS = 5


def _score(section: str, keywords: set[str], numbers: set[str]) -> float:
    if not keywords:
        return 0.0
    lower = section.lower()
    keyword_score = sum(1 for kw in keywords if kw in lower) / len(keywords)
    number_boost = min(sum(1 for n in numbers if n in section) * 0.15, 0.3)
    return keyword_score + number_boost


def ranked_paragraphs(claim: str, text: str) -> list[str]:
    """All paragraphs (>50 chars) with score > 0.1, best first (the old ranking)."""
    keywords = {w for w in re.findall(r"[a-zA-Z]{3,}", claim.lower()) if w not in _STOP_WORDS}
    numbers = set(re.findall(r"\d+\.?\d*%?", claim))
    paragraphs = [c.strip() for c in re.split(r"\n\s*\n", text) if len(c.strip()) > 50]
    scored = [(_score(p, keywords, numbers), p) for p in paragraphs]
    scored = [(s, p) for s, p in scored if s > _MIN_SCORE]
    scored.sort(key=lambda sp: sp[0], reverse=True)
    return [p for _, p in scored]


def old_context(claim: str, text: str) -> list[str]:
    """What the old verifier sent to the LLM for this claim."""
    if len(text) < _SHORT_CHARS:
        return [text]
    ranked = ranked_paragraphs(claim, text)
    if not ranked:
        return [text[:500]]
    out: list[str] = []
    total = 0
    for para in ranked[:_MAX_SECTIONS]:
        if total + len(para) > _MAX_CONCAT_CHARS and out:
            break
        out.append(para)
        total += len(para)
    return out
