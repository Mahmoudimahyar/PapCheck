"""Manual review files -> one verdict per reviewed (sentence, reference) pair.

Review A (40 "not supported" cases of an earlier run): cases.json +
manual_gold.json (+ optional per-case notes {case: [verdict, evidence, fix]}).
Review B (133 "partially supported" cases of the fixed run): cases.json +
review_results.json ({rev, sec, final}) + harsh_categories.json (why the tool
was too harsh, preliminary). Review A pairs whose citation now maps to another
reference were judged against the wrong paper: their verdict is kept for the
record but is not gold for the new pair.
"""

import re
from pathlib import Path
from typing import Literal

from gold_models import Confidence
from pydantic import BaseModel, ConfigDict, TypeAdapter

# V4.9 citation remaps between the review-A run and the fixed run (case -> new ref).
A_REMAP: dict[int, int] = {32: 107, 33: 107, 8: 30, 34: 106}
# Remapped cases whose review-A verdict was judged on a different paper (34: 106 is a
# duplicate entry of 105, the same paper, so its review stays valid).
A_WRONG_PAPER_REMAPS = frozenset({8, 32, 33})
_A_LABELS = {"partially_supported_tool_ok": "partially_supported"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CaseRow(_Loose):
    case: int
    claim_id: int
    ref: int
    sentence: str


class ManualRow(_Loose):
    case: int
    manual: str


class FirstReview(_Loose):
    confidence: str = "medium"
    full_text_used: bool = True
    missing_or_overstated: str = ""
    manuscript_fix: str = ""


class SecondReview(_Loose):
    my_verdict: str = ""
    agrees_with_first_reviewer: bool = True
    note: str = ""


class FinalReview(_Loose):
    outcome: str = ""
    verdict: str
    status: str = ""


class ReviewBResults(_Loose):
    rev: dict[str, FirstReview]
    sec: dict[str, SecondReview]
    final: dict[str, FinalReview]


class ReviewVerdict(BaseModel):
    """One reviewer verdict for a pair (ref already remapped to the fixed run)."""

    source: Literal["review_A", "review_B"]
    case: int
    ref: int
    sentence: str
    claim_number: int  # in the session the reviewer looked at
    raw_label: str
    label: str  # normalised gold label ("" when the verdict is not usable)
    valid: bool = True
    invalid_reason: str = ""
    confidence: Confidence = "medium"
    basis: Literal["full_text", "abstract"] = "full_text"
    notes: str = ""
    misread: str = ""  # review B: why the tool was too harsh (slug)


def slug(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")


def _a_verdict(case: CaseRow, manual: str, note: list[str]) -> ReviewVerdict:
    ref = A_REMAP.get(case.case, case.ref)
    valid, reason = True, ""
    if case.case in A_WRONG_PAPER_REMAPS:
        valid, reason = False, (f"review A judged ref {case.ref}; the citation now maps to "
                                f"ref {ref} (never reviewed against it)")
    elif manual == "wrong_paper":
        valid, reason = False, "review A: the linked PDF/reference was not the cited paper"
    text = " ".join(note[1:2]) + (f" Fix: {note[2]}" if len(note) > 2 and note[2] else "")
    if manual == "partially_supported_tool_ok":
        text = "Reviewer A: partial; the tool's not_supported is acceptable. " + text
    return ReviewVerdict(
        source="review_A", case=case.case, ref=ref, sentence=case.sentence,
        claim_number=case.claim_id, raw_label=manual,
        label=_A_LABELS.get(manual, manual) if valid else "", valid=valid,
        invalid_reason=reason, notes=text.strip(),
        confidence="low" if manual == "partially_supported_tool_ok" else "medium")


def load_review_a(folder: Path, notes_path: Path | None) -> list[ReviewVerdict]:
    cases = TypeAdapter(list[CaseRow]).validate_json(
        (folder / "cases.json").read_bytes())
    manual = {m.case: m.manual for m in TypeAdapter(list[ManualRow]).validate_json(
        (folder / "manual_gold.json").read_bytes())}
    notes: dict[str, list[str]] = {}
    if notes_path is not None and notes_path.is_file():
        notes = TypeAdapter(dict[str, list[str]]).validate_json(notes_path.read_bytes())
    return [_a_verdict(c, manual[c.case], notes.get(str(c.case), []))
            for c in cases if c.case in manual]


def _b_confidence(rev: FirstReview, final: FinalReview) -> Confidence:
    if "split" in final.status:
        return "low"
    return rev.confidence if rev.confidence in ("high", "medium", "low") \
        else "medium"  # type: ignore[return-value]


def _b_notes(rev: FirstReview, sec: SecondReview | None, final: FinalReview) -> str:
    parts = [rev.missing_or_overstated.strip()]
    if rev.manuscript_fix.strip():
        parts.append(f"Fix: {rev.manuscript_fix.strip()}")
    if sec is not None and not sec.agrees_with_first_reviewer:
        parts.append(f"2nd reviewer ({sec.my_verdict}): {sec.note}")
    parts.append(f"[B: {final.outcome}, {final.status}]")
    return " ".join(p for p in parts if p)


def load_review_b(folder: Path) -> list[ReviewVerdict]:
    cases = TypeAdapter(list[CaseRow]).validate_json((folder / "cases.json").read_bytes())
    results = ReviewBResults.model_validate_json(
        (folder / "review_results.json").read_bytes())
    harsh_path = folder / "harsh_categories.json"
    harsh = TypeAdapter(dict[str, str]).validate_json(harsh_path.read_bytes()) \
        if harsh_path.is_file() else {}
    out: list[ReviewVerdict] = []
    for case in cases:
        key = str(case.case)
        rev, final = results.rev[key], results.final[key]
        out.append(ReviewVerdict(
            source="review_B", case=case.case, ref=case.ref, sentence=case.sentence,
            claim_number=case.claim_id, raw_label=final.verdict, label=final.verdict,
            confidence=_b_confidence(rev, final),
            basis="full_text" if rev.full_text_used else "abstract",
            notes=_b_notes(rev, results.sec.get(key), final),
            misread=slug(harsh[key]) if final.verdict == "supported" and key in harsh
            else ""))
    return out
