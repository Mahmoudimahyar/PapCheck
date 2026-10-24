"""Resolve verification scope for each citation (heuristic + LLM)."""

import logging
import re
from itertools import groupby

from refcheck.models.citation import CitationInstance, VerificationUnit
from refcheck.stages.detect_citations.cited_for import (
    cited_for_or_scope,
    compute_cited_for,
)
from refcheck.stages.detect_citations.claim_quality import assess_claim_quality

logger = logging.getLogger(__name__)


def resolve_scopes(
    citations: list[CitationInstance],
) -> list[VerificationUnit]:
    """For each mapped citation, determine what it covers.

    Uses heuristics first. Returns VerificationUnits with scope_text.
    """
    units: list[VerificationUnit] = []
    # Group citations by sentence (same paragraph + sentence boundaries)
    keyfunc = lambda c: (c.paragraph_index, c.sentence_start, c.sentence_end)  # noqa: E731
    sorted_cits = sorted(citations, key=keyfunc)

    for _key, group_iter in groupby(sorted_cits, key=keyfunc):
        group = list(group_iter)
        co_cited = _co_cited_count(group)
        resolved = (
            [_resolve_single(group[0])] if len(group) == 1 else _resolve_multi(group)
        )
        # extracted_claim stays the whole scope; cited_for narrows per marker
        clauses = compute_cited_for(group)
        quality = assess_claim_quality(group[0].sentence_text)
        units.extend(
            u.model_copy(update={
                "co_cited_count": co_cited, "claim_quality": quality,
                "cited_for": cited_for_or_scope(clause, u.scope_text),
            })
            for u, clause in zip(resolved, clauses, strict=True)
        )

    # Assign IDs via model_copy (Pydantic-safe, no direct mutation)
    return [
        unit.model_copy(update={"id": i})
        for i, unit in enumerate(units, 1)
    ]


def _co_cited_count(group: list[CitationInstance]) -> int:
    """Distinct references cited in one sentence (compound markers expanded)."""
    ref_ids = {c.reference_id for c in group if c.reference_id is not None}
    return max(1, len(ref_ids))


def _resolve_single(cit: CitationInstance) -> VerificationUnit:
    """Single citation in sentence: scope = sentence without marker."""
    if cit.is_narrative:
        scope = _narrative_scope(cit)
    else:
        scope = _remove_citation_markers(cit.sentence_text)
    claim_type, priority = classify_claim_type(scope, cit.is_narrative)
    return _build_unit(cit, scope, claim_type, priority)


def _resolve_multi(
    citations: list[CitationInstance],
) -> list[VerificationUnit]:
    """Multiple citations in one sentence: shared scope."""
    sentence = citations[0].sentence_text
    scope = _remove_citation_markers(sentence)
    units: list[VerificationUnit] = []
    for cit in citations:
        cit_scope = scope
        if cit.is_narrative:
            cit_scope = _narrative_scope(cit)
        claim_type, priority = classify_claim_type(cit_scope, cit.is_narrative)
        units.append(_build_unit(cit, cit_scope, claim_type, priority))
    return units


def _narrative_scope(cit: CitationInstance) -> str:
    """Extract scope for narrative citation (after the author marker)."""
    sentence = cit.sentence_text
    # Find the end of the (YEAR) marker in the sentence
    marker_in_sent = cit.raw_marker
    pos = sentence.find(marker_in_sent)
    if pos != -1:
        after = sentence[pos + len(marker_in_sent):].strip()
        after = after.lstrip(",. ")
        if after:
            return after
    # Fallback: everything after the year
    year_match = re.search(r"\(\d{4}[a-z]?\)", sentence)
    if year_match:
        after = sentence[year_match.end():].strip().lstrip(",. ")
        if after:
            return after
    return _remove_citation_markers(sentence)


def _remove_citation_markers(text: str) -> str:
    """Remove all citation markers from text."""
    # Remove parenthetical author-year citations
    cleaned = re.sub(
        r"\s*\([^)]*\d{4}[a-z]?[^)]*\)", "", text,
    )
    # Remove numbered citations
    cleaned = re.sub(r"\s*\[\d+[^\]]*\]", "", cleaned)
    return cleaned.strip().rstrip(".")


def _has_keyword(text_lower: str, words: tuple[str, ...]) -> bool:
    """Word-boundary keyword match.

    Plain substring tests misfire ("is a" inside "this approach", "using"
    inside "focusing"). Phrases need boundaries on both sides; single words
    only at the start so simple inflections ("methods") still match.
    """
    for word in words:
        suffix = r"\b" if " " in word else ""
        if re.search(rf"\b{re.escape(word)}{suffix}", text_lower):
            return True
    return False


_CONTRAST_WORDS = (
    "unlike", "in contrast", "whereas", "however",
    "conversely", "although", "contrary",
)
_ATTRIBUTION_WORDS = (
    "showed", "demonstrated", "found", "reported",
    "observed", "concluded", "suggested",
)
_METHOD_WORDS = (
    "using", "method", "protocol", "technique",
    "procedure", "approach", "performed",
)
_BACKGROUND_WORDS = (
    "is a", "are characterized", "is defined",
    "is known", "are widely", "has been",
)


def classify_claim_type(
    scope_text: str, is_narrative: bool,
) -> tuple[str, str]:
    """Classify claim type and priority using heuristics."""
    text_lower = scope_text.lower()

    # Numbers/statistics → factual, high
    if re.search(r"\d+\.?\d*\s*%", scope_text):
        return "factual", "high"
    if re.search(r"n\s*=\s*\d+", scope_text, re.IGNORECASE):
        return "factual", "high"

    if _has_keyword(text_lower, _CONTRAST_WORDS):
        return "contrast", "high"
    if is_narrative or _has_keyword(text_lower, _ATTRIBUTION_WORDS):
        return "attribution", "medium"
    if _has_keyword(text_lower, _METHOD_WORDS):
        return "methodological", "medium"
    if _has_keyword(text_lower, _BACKGROUND_WORDS):
        return "background", "low"

    return "factual", "medium"


def _build_unit(
    cit: CitationInstance, scope: str,
    claim_type: str, priority: str,
) -> VerificationUnit:
    """Build a VerificationUnit from a citation and scope."""
    return VerificationUnit(
        manuscript_text=cit.sentence_text,
        paragraph_text=cit.paragraph_text,
        scope_text=scope,
        citation_marker=cit.raw_marker,
        paragraph_index=cit.paragraph_index,
        char_start=cit.char_start,
        char_end=cit.char_end,
        section_heading=cit.section_heading,
        reference_id=cit.reference_id or 0,
        reference_title=cit.reference_title,
        citation_style=cit.style,
        is_narrative=cit.is_narrative,
        claim_type=claim_type,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        mapping_ambiguous=cit.mapping_ambiguous,
        candidate_reference_ids=list(cit.candidate_reference_ids),
    )
