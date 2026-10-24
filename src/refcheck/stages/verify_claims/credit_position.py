"""Which occurrence of a repeated credit sentence a claim is (V5.6).

One legend can credit the same source twice ("(A) ... Adapted from X. (B) ...
(C) ... Adapted from X."): both claims then have the same sentence and paragraph
text. The paragraph text may be a window of the detector's paragraph, so a claim's
own offset (``location.char_start``, in detector-paragraph coordinates) cannot be
mapped into it directly; but the offsets of two claims with the same sentence
differ by exactly the distance between their credits. So occurrence ``i`` is this
claim's when ``pos[i] + diff`` is another occurrence for some sibling's ``diff``.
Unresolved (no location, no sibling claim, ambiguous) -> no entry.
"""

from collections import defaultdict
from collections.abc import Iterable

from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.credit_legend import credit_positions, is_credit_line

GroupKey = tuple[int, str]  # (paragraph index, whitespace-normalised sentence)


def credit_text(claim: Claim) -> str:
    """The text whose credit-line shape decides whether a claim is a figure credit."""
    return claim.cited_for or claim.extracted_claim or claim.manuscript_text


def credit_needle(claim: Claim) -> str:
    """The credit sentence to look for in the claim's paragraph."""
    sentence = claim.manuscript_text
    return sentence if is_credit_line(sentence) else credit_text(claim)


def credit_occurrences(claims: Iterable[Claim]) -> dict[int, int]:
    """claim id -> index of its credit among the identical credits of its paragraph."""
    groups: dict[GroupKey, list[Claim]] = defaultdict(list)
    for claim in claims:
        if claim.location is not None and is_credit_line(credit_text(claim)):
            key = (claim.location.paragraph_index, " ".join(claim.manuscript_text.split()))
            groups[key].append(claim)
    out: dict[int, int] = {}
    for group in groups.values():
        for claim in group:
            index = _occurrence(claim, group)
            if index is not None:
                out[claim.id] = index
    return out


def _offset(claim: Claim) -> int:
    return claim.location.char_start if claim.location is not None else 0


def _occurrence(claim: Claim, group: list[Claim]) -> int | None:
    positions = credit_positions(credit_needle(claim), claim.paragraph_text)
    if len(positions) < 2:
        return 0 if positions else None
    known = set(positions)
    candidates = set(range(len(positions)))
    for other in group:
        diff = _offset(other) - _offset(claim)
        matches = {i for i, pos in enumerate(positions) if diff and pos + diff in known}
        if matches:
            candidates &= matches
    return candidates.pop() if len(candidates) == 1 else None
