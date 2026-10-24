"""Review verdicts + one session's claims/references -> gold rows (one per unique pair).

Each verdict is matched to the session's (sentence, reference) pair: exactly on
the normalised sentence, else (review A sentences that the fixed run split in
two) on the same reference with the session sentence contained in the
reviewed one. Two usable verdicts on one pair must agree; a disagreement keeps
review B's label (the later review, two reviewers, run on the fixed citation
mapping) and is flagged needs_adjudication until a labels file resolves it.
"""

import logging

from gold_db import DbClaim, PairKey, SessionData, production_pdf
from gold_models import GoldRow, binary_of, normalize_sentence, pair_id
from gold_reviews import ReviewVerdict
from pydantic import BaseModel
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)
FUZZY_MIN = 90.0


class PairReviews(BaseModel):
    claim: DbClaim
    ref: int
    a: ReviewVerdict | None = None
    b: ReviewVerdict | None = None


def match_claim(verdict: ReviewVerdict, session: SessionData,
                index: dict[PairKey, list[int]]) -> DbClaim | None:
    """The session claim for a reviewed pair (None when the pair is not in the session)."""
    by_number = {c.number: c for c in session.claims}
    numbers = index.get((normalize_sentence(verdict.sentence), verdict.ref))
    if numbers:
        own = verdict.source == "review_B" and verdict.claim_number in numbers
        return by_number[verdict.claim_number if own else numbers[0]]
    target = normalize_sentence(verdict.sentence)
    scored = [(fuzz.partial_ratio(normalize_sentence(c.sentence), target), c.number)
              for c in session.claims if verdict.ref in c.refs]
    if not scored or max(scored)[0] < FUZZY_MIN:
        return None
    best = max(scored)[1]
    logger.info("%s case %d matched by containment to claim %d", verdict.source,
                verdict.case, best)
    return by_number[best]


def group_reviews(verdicts: list[ReviewVerdict], session: SessionData,
                  ) -> tuple[dict[str, PairReviews], list[ReviewVerdict]]:
    """pair id -> the A/B verdicts on it; plus verdicts whose pair is not in the session."""
    index = session.pair_index()
    pairs: dict[str, PairReviews] = {}
    missing: list[ReviewVerdict] = []
    for verdict in verdicts:
        claim = match_claim(verdict, session, index)
        if claim is None:
            missing.append(verdict)
            continue
        pid = pair_id(claim.sentence, verdict.ref)
        pair = pairs.setdefault(pid, PairReviews(claim=claim, ref=verdict.ref))
        slot = "a" if verdict.source == "review_A" else "b"
        if getattr(pair, slot) is not None:
            logger.warning("Pair %s has two %s verdicts; keeping the first", pid, verdict.source)
            continue
        setattr(pair, slot, verdict)
    return pairs, missing


def _label_fields(p: PairReviews) -> dict[str, object]:
    a, b = p.a, p.b
    a_ok = a is not None and a.valid
    if b is not None:
        fields: dict[str, object] = {
            "gold_label": b.label, "gold_source": "review_B", "gold_confidence": b.confidence,
            "gold_basis": b.basis, "notes": f"B: {b.notes}", "tool_misread_type": b.misread}
        if a is not None and a_ok:
            if a.label == b.label:
                fields["gold_source"] = "both"
                fields["gold_confidence"] = "high" if b.basis == "full_text" else b.confidence
            else:
                fields.update(needs_adjudication=True, gold_confidence="low")
            fields["notes"] = f"{fields['notes']} | A ({a.raw_label}): {a.notes}"
        elif a is not None:
            fields["notes"] = f"{fields['notes']} | A not comparable: {a.invalid_reason}"
        return fields
    if a is None:  # group_reviews only creates pairs that have a verdict
        raise ValueError("pair without any review verdict")
    if a_ok:
        return {"gold_label": a.label, "gold_source": "review_A",
                "gold_confidence": a.confidence, "notes": f"A: {a.notes}"}
    return {"gold_label": "cannot_judge", "gold_source": "review_A", "gold_confidence": "low",
            "exclude": True, "exclude_reason": a.invalid_reason,
            "notes": f"A ({a.raw_label}): {a.notes}"}


def pair_fields(session: SessionData, claim: DbClaim, ref_number: int) -> dict[str, object]:
    """Manuscript + reference fields of a (claim, reference) pair, as production sees them."""
    ref = production_pdf(session.references, session.references[ref_number])
    return {
        "session_id": session.session_id, "claim_number": claim.number,
        "sentence": claim.sentence, "claim": claim.claim, "cited_for": claim.cited_for,
        "paragraph": claim.paragraph, "section": claim.section,
        "claim_type": claim.claim_type, "claim_quality": claim.claim_quality,
        "co_cited_count": claim.co_cited_count,
        "co_cited_refs": session.co_cited(claim.sentence, ref_number),
        "ref": ref_number, "ref_title": ref.title, "ref_authors": ref.authors,
        "ref_year": ref.year, "doi": ref.doi, "pdf_path": ref.pdf_path,
        "abstract": ref.abstract, "abstract_source": ref.abstract_source,
        "identity_status": ref.identity_status}


def build_row(pid: str, pair: PairReviews, session: SessionData) -> GoldRow:
    fields = _label_fields(pair)
    label = str(fields["gold_label"])
    return GoldRow.model_validate({
        "id": pid, **pair_fields(session, pair.claim, pair.ref),
        "gold_binary": binary_of(label),
        "review_a_case": pair.a.case if pair.a else None,
        "review_b_case": pair.b.case if pair.b else None,
        "review_a_verdict": pair.a.raw_label if pair.a else "",
        "review_b_verdict": pair.b.raw_label if pair.b else "", **fields})


def build_rows(verdicts: list[ReviewVerdict], session: SessionData,
               ) -> tuple[list[GoldRow], list[ReviewVerdict]]:
    pairs, missing = group_reviews(verdicts, session)
    for verdict in missing:
        logger.warning("%s case %d (ref %d) is not a pair of %s: skipped", verdict.source,
                       verdict.case, verdict.ref, session.session_id)
    rows = [build_row(pid, pair, session) for pid, pair in pairs.items()]
    return sorted(rows, key=lambda r: (r.ref, r.claim_number)), missing
