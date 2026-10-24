"""What a reader must see about one verification result besides its verdict.

The verify stage records several findings only as sentences in
``VerificationResult.reasoning`` (and each layer's own view in
``model_reasoning``): a dispute between the verifier and the blind
cross-check, a supporting passage that itself cites other work, claim numbers
found nowhere in the source, and an attached PDF that cannot stand for the
article (another paper, a scan, the supplement, a metadata page). The report
and the UI used to show only the verdict and the whole reasoning text, so a
disputed "not supported" read like a firm finding and a wrong PDF was
invisible. These helpers turn them into fields. The note wording is pinned
to the verify stage's own output by tests/unit/test_result_signals.py.
V5.7 (#9): a "supported" verdict the verify stage's check-first triage flagged
(verify_claims/check_first.py: "Check first: shown as supported, but <reasons> — ...")
is check_first too, with its reasons in ``ResultSignals.check_first_reasons``.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.verification import ModelReasoning, VerificationResult
from refcheck.stages.generate_report.layer_trace import VERIFIER_LAYERS, last_entry

SourceProblem = Literal["reference_mismatch", "pdf_scanned", "pdf_supplement",
                        "pdf_metadata_only"]

SOURCE_PROBLEM_TEXT: dict[SourceProblem, str] = {
    "reference_mismatch": "The attached PDF is a different paper than this reference",
    "pdf_scanned": "The attached PDF is a scan without a usable text layer",
    "pdf_supplement": "The attached PDF is the supplementary material, not the article",
    "pdf_metadata_only": "The attached PDF holds only a metadata page",
}
# Opening words of the verify stage's abstract-fallback notes (source_fallback.py);
# a fallback keeps a positive verdict, so the note is the only trace of the problem.
_FALLBACK_OPENINGS: tuple[tuple[str, SourceProblem], ...] = (
    ("The attached PDF is a different paper", "reference_mismatch"),
    ("The attached PDF is a scan", "pdf_scanned"),
    ("The attached PDF has no readable text", "pdf_scanned"),
    ("The attached PDF is the supplementary material", "pdf_supplement"),
    ("The attached PDF holds only a metadata page", "pdf_metadata_only"),
)
SECONDARY_CITATION_OPENING = "Secondary citation:"
_NUMBERS_RE = re.compile(
    r"Numbers not found in the source: (?P<nums>.+?)(?: \([^()]*\))? — please check")
_CHECK_FIRST_RE = re.compile(  # verify_claims/check_first.check_first_note
    r"Check first: shown as supported, but (?P<reasons>.+?) — please confirm")
_NEGATIVE = frozenset({"not_supported", "contradicted", "not_relevant"})


class LayerView(BaseModel):
    """One model's verdict and its own explanation."""

    verdict: str
    model_name: str = ""
    explanation: str = ""


class DisputeViews(BaseModel):
    """Both sides of a verifier / cross-check disagreement."""

    verifier: LayerView
    cross_check: LayerView
    shown_verdict: str  # the cascade's verdict (before any user override)


class ResultSignals(BaseModel):
    """Structured findings of one result (all empty for an ordinary result)."""

    dispute: DisputeViews | None = None
    secondary_citation: bool = False
    numbers_not_found: list[str] = Field(default_factory=list)
    source_problem: SourceProblem | None = None
    source_problem_text: str = ""
    check_first_reasons: list[str] = Field(default_factory=list)  # V5.7: supported, check first


def _view(entry: ModelReasoning) -> LayerView:
    return LayerView(verdict=entry.verdict, model_name=entry.model_name,
                     explanation=entry.reasoning)


def dispute_views(v: VerificationResult) -> DisputeViews | None:
    """The verifier's and the cross-check's views when they disagreed."""
    if v.consensus_type != "disputed":
        return None
    verifier = last_entry(v, *VERIFIER_LAYERS)
    second = last_entry(v, "confirm", "judge")
    if verifier is None or second is None:
        return None
    shown = v.original_verdict if v.user_override and v.original_verdict else v.verdict
    return DisputeViews(verifier=_view(verifier), cross_check=_view(second),
                        shown_verdict=shown)


def source_problem(v: VerificationResult) -> SourceProblem | None:
    """Why the attached PDF could not be used as the cited article, if it could not."""
    reason = v.cannot_verify_reason or ""
    for problem in SOURCE_PROBLEM_TEXT:
        if reason == problem:
            return problem
    for opening, problem in _FALLBACK_OPENINGS:
        if opening in v.reasoning:
            return problem
    return None


def numbers_not_found(reasoning: str) -> list[str]:
    """Claim figures the verify stage found nowhere in the source text."""
    match = _NUMBERS_RE.search(reasoning)
    return match.group("nums").split(", ") if match else []


def missed_problem_reasons(reasoning: str) -> list[str]:
    """Why the verify stage's triage flagged a supported verdict (V5.7 #9), else []."""
    match = _CHECK_FIRST_RE.search(reasoning)
    return match.group("reasons").split("; ") if match else []


def result_signals(v: VerificationResult) -> ResultSignals:
    """All structured findings of ``v``."""
    problem = source_problem(v)
    return ResultSignals(
        dispute=dispute_views(v),
        secondary_citation=SECONDARY_CITATION_OPENING in v.reasoning,
        numbers_not_found=numbers_not_found(v.reasoning),
        source_problem=problem,
        source_problem_text=SOURCE_PROBLEM_TEXT[problem] if problem else "",
        check_first_reasons=missed_problem_reasons(v.reasoning)
        if v.verdict == "supported" else [],
    )


def check_first(v: VerificationResult) -> bool:
    """A result that may hide a real problem and must be reviewed first: a "partially
    supported" that must not be filed with the minor issues (one model found no support
    and only the other's disagreement softened it - dispute rule, either direction - or
    figures in the claim occur nowhere in the source), or (V5.7) a "supported" verdict
    the triage flagged that no reviewer has confirmed yet."""
    if v.verdict == "supported":
        return not v.user_override and bool(missed_problem_reasons(v.reasoning))
    if v.verdict != "partially_supported":
        return False
    views = dispute_views(v)
    softened = views is not None and (views.verifier.verdict in _NEGATIVE
                                       or views.cross_check.verdict in _NEGATIVE)
    return softened or bool(numbers_not_found(v.reasoning))
