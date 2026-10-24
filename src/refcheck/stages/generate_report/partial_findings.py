"""Group partial verdicts by sub-type and supported verdicts by the guard that cleared them.

Shared by the results API (filter + counts) and the DOCX report (sub-sections).
Labels, meanings, severities and author actions come from
``models/partial_types.py`` (taxonomy v1.1); this module only decides which
bucket a stored result falls into. Results stored before V5.4 carry no
``partial_type``: their partial verdicts are grouped as "unclassified".

A reviewer override changes only the verdict. When it differs from the model's
verdict, the stored type, elements, action and guards explained the model's
verdict, not the reviewer's, so every accessor here hides them (a reviewer's
"partially supported" is then "unclassified"). A cannot_verify result has no
sub-type either (an abstract fallback may have replaced a typed negative).
Report, API and UI read them through these accessors only.
"""

from collections import Counter

from refcheck.models.partial_types import (
    GUARD_LABELS,
    GUARD_ORDER,
    PARTIAL_TYPE_INFO,
    author_action,
    default_severity,
)
from refcheck.models.verification import VerificationResult

UNCLASSIFIED = "unclassified"
GUARDED = "guarded"
_GUARD_PREFIX = f"{GUARDED}:"
UNCLASSIFIED_INFO: tuple[str, str, str] = (
    "Other partial findings",
    "Partial results without a recorded type (older runs or reviewer overrides).",
    "minor",
)
# Sub-section order of the report and the UI (taxonomy report_subsections).
PARTIAL_KEYS: tuple[str, ...] = (*PARTIAL_TYPE_INFO, UNCLASSIFIED)


def type_key(verdict: str, partial_type: str | None) -> str | None:
    """Bucket of a partially supported result (None for any other verdict)."""
    if verdict != "partially_supported":
        return None
    return partial_type if partial_type in PARTIAL_TYPE_INFO else UNCLASSIFIED


def reviewer_changed_verdict(v: VerificationResult) -> bool:
    """A reviewer replaced the model's verdict (the stored sub-type fields are stale)."""
    return v.user_override and v.original_verdict != v.verdict


def _hidden(v: VerificationResult) -> bool:
    """Stored sub-type fields do not describe the shown verdict (module doc)."""
    return reviewer_changed_verdict(v) or v.verdict == "cannot_verify"


def partial_type_of(v: VerificationResult) -> str | None:
    """The model's partial type, unless a reviewer changed the verdict."""
    return None if _hidden(v) else v.partial_type


def elements_of(v: VerificationResult) -> list[str]:
    """What the source does not state, unless a reviewer changed the verdict."""
    return [] if _hidden(v) else list(v.unsupported_elements)


def partial_key(v: VerificationResult) -> str | None:
    """Bucket of ``v`` when it is partially supported."""
    return type_key(v.verdict, partial_type_of(v))


def type_info(key: str) -> tuple[str, str, str]:
    """(label, one-line meaning, default severity) of a bucket."""
    return PARTIAL_TYPE_INFO.get(key, UNCLASSIFIED_INFO)


def type_label(partial_type: str | None) -> str:
    """Display label of a genuine type ("" for none / unknown)."""
    info = PARTIAL_TYPE_INFO.get(partial_type or "")
    return info[0] if info else ""


def severity_of(v: VerificationResult) -> str | None:
    """Stored severity, else the type's default (None without a type)."""
    if _hidden(v):
        return None
    return v.partial_severity or default_severity(v.partial_type)


def action_of(v: VerificationResult) -> str:
    """Stored author action, else the type's template naming the first element."""
    if _hidden(v):
        return ""
    if v.author_action:
        return v.author_action
    element = v.unsupported_elements[0] if v.unsupported_elements else None
    return author_action(v.partial_type, element)


def guards_of(v: VerificationResult) -> list[str]:
    """Known guards that cleared a concern on ``v``, in taxonomy order."""
    if _hidden(v):
        return []
    return [g for g in GUARD_ORDER if g in v.guards_applied]


def is_guarded(verdict: str, guards: list[str]) -> bool:
    """A supported result that had a concern a benign guard cleared."""
    return verdict == "supported" and any(g in GUARD_LABELS for g in guards)


def matches_partial_filter(verdict: str, partial_type: str | None, guards: list[str],
                           value: str) -> bool:
    """Results-API filter: a bucket id, "guarded" or "guarded:<guard>"."""
    if value == "all":
        return True
    if value == GUARDED:
        return is_guarded(verdict, guards)
    if value.startswith(_GUARD_PREFIX):
        return is_guarded(verdict, guards) and value[len(_GUARD_PREFIX):] in guards
    return type_key(verdict, partial_type) == value


def partial_counts(verifications: list[VerificationResult]) -> dict[str, int]:
    """Partially supported results per bucket: every type (0 included), and
    "unclassified" only when legacy rows exist."""
    found = Counter(partial_key(v) for v in verifications)
    counts = {key: found.get(key, 0) for key in PARTIAL_TYPE_INFO}
    if found.get(UNCLASSIFIED):
        counts[UNCLASSIFIED] = found[UNCLASSIFIED]
    return counts


def severity_counts(verifications: list[VerificationResult]) -> dict[str, int]:
    """Partially supported results per severity ("minor" / "major")."""
    found = Counter(severity_of(v) or "minor" for v in verifications
                    if v.verdict == "partially_supported")
    return {"major": found.get("major", 0), "minor": found.get("minor", 0)}


def guarded_results(verifications: list[VerificationResult]) -> list[VerificationResult]:
    """Supported results whose concern a guard cleared."""
    return [v for v in verifications if is_guarded(v.verdict, guards_of(v))]


def guard_counts(verifications: list[VerificationResult]) -> dict[str, int]:
    """Supported-with-a-note results per guard (a result may count under several)."""
    found = Counter(g for v in guarded_results(verifications) for g in guards_of(v))
    return {g: found[g] for g in GUARD_ORDER if found.get(g)}
