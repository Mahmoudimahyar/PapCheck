"""Partial-verdict sub-types (taxonomy v1.1, see prompts/partial_taxonomy.json).

Shared by the verdict logic (verify_claims) and the surfaces (API, UI, report).
A partial verdict gets exactly one genuine type; concerns cleared by a benign
guard are recorded in ``guards_applied`` and leave the verdict ``supported``.
"""

from typing import Literal

PartialType = Literal[
    "tangential_source",
    "specific_detail_mismatch",
    "unsupported_inference",
    "scope_overgeneralized",
    "missing_element",
    "certainty_overstated",
    "coverage_limited",
    "none",
]
BenignNote = Literal[
    "cocited_share", "author_framing_or_example", "overliteral_wording", "secondary_source",
]
GuardName = Literal[
    "evidence_recheck", "cocited_share", "author_framing_or_example", "overliteral_wording",
]
PartialSeverity = Literal["minor", "major"]

# Genuine types, most severe first (taxonomy precedence step 2).
GENUINE_PRECEDENCE: tuple[str, ...] = (
    "tangential_source",
    "specific_detail_mismatch",
    "unsupported_inference",
    "scope_overgeneralized",
    "missing_element",
    "certainty_overstated",
)
# Benign guards in the order they are applied (taxonomy precedence step 1).
GUARD_ORDER: tuple[str, ...] = (
    "evidence_recheck", "cocited_share", "author_framing_or_example", "overliteral_wording",
)

# Report / UI sub-section per type: (title, one-line meaning, default severity).
PARTIAL_TYPE_INFO: dict[str, tuple[str, str, str]] = {
    "specific_detail_mismatch": (
        "Wrong or missing specifics",
        "A number, model, material or other specific is absent from or different in the source.",
        "major",
    ),
    "tangential_source": (
        "Weak or misplaced citation",
        "The source does not support the main point of the clause the citation is attached to.",
        "major",
    ),
    "unsupported_inference": (
        "Author's inference attributed to the source",
        "The facts are in the source, but the link, cause or conclusion drawn from them is not.",
        "major",
    ),
    "scope_overgeneralized": (
        "Overgeneralized scope",
        "A result is stretched beyond the source's population, model or breadth.",
        "major",
    ),
    "missing_element": (
        "Missing pieces",
        "Part of a compound claim has no support in this source.",
        "minor",
    ),
    "certainty_overstated": (
        "Overstated certainty",
        "The source says the same thing with more caution, or weaker results.",
        "minor",
    ),
    "coverage_limited": (
        "Could not verify (coverage)",
        "Only the abstract or part of the paper was available, so part of the claim "
        "could not be checked.",
        "minor",
    ),
}

# What the author should do, per type ({element} is filled when known).
AUTHOR_ACTIONS: dict[str, str] = {
    "specific_detail_mismatch": (
        "Correct or remove the specific{element}, or cite the paper that reports it."
    ),
    "tangential_source": (
        "Replace or move this citation: the source does not state the main point{element}."
    ),
    "unsupported_inference": (
        "Mark the link{element} as your own interpretation (e.g. 'we propose') "
        "or cite a source that states it."
    ),
    "scope_overgeneralized": (
        "Narrow the wording to the source's population or context{element}, "
        "or add a source at the claimed scope."
    ),
    "missing_element": (
        "Add a citation for the unsupported part{element} or drop it."
    ),
    "certainty_overstated": (
        "Soften the wording{element} to match the source's own qualifier."
    ),
    "coverage_limited": (
        "Upload the full text of this reference so the remaining part{element} can be checked."
    ),
}

# Note shown on a supported result when a guard cleared a concern.
GUARD_LABELS: dict[str, tuple[str, str]] = {
    "evidence_recheck": (
        "Evidence re-check",
        "A targeted search of the full text found the passage the first check missed.",
    ),
    "cocited_share": (
        "Co-cited reference",
        "The rest of the sentence is supported by the other reference(s) cited with it; "
        "consider placing each citation next to the clause it supports.",
    ),
    "author_framing_or_example": (
        "Author framing / example",
        "The source is cited as an example, or the extra words are the author's own framing.",
    ),
    "overliteral_wording": (
        "Wording only",
        "The claim paraphrases the source; the difference is wording, not substance.",
    ),
}

# Legacy problem_type -> default partial_type when a model did not classify.
LEGACY_PROBLEM_MAP: dict[str, str] = {
    "certainty_overstated": "certainty_overstated",
    "overgeneralized": "scope_overgeneralized",
    "wrong_population": "scope_overgeneralized",
    "compound_part_only": "missing_element",
    "numeric_mismatch": "specific_detail_mismatch",
    "not_in_source": "missing_element",
    "unrelated_source": "tangential_source",
    "wrong_direction": "specific_detail_mismatch",
}


# partial_type -> the legacy problem_type a layer should report with it (prompt + fallback).
LEGACY_FOR_TYPE: dict[str, str] = {
    "tangential_source": "not_in_source",
    "specific_detail_mismatch": "numeric_mismatch",
    "unsupported_inference": "not_in_source",
    "scope_overgeneralized": "overgeneralized",
    "missing_element": "compound_part_only",
    "certainty_overstated": "certainty_overstated",
    "coverage_limited": "not_in_source",
}
# A model's benign note -> the guard recorded on the result (secondary_source is a note only).
GUARD_FOR_NOTE: dict[str, str] = {
    "cocited_share": "cocited_share",
    "author_framing_or_example": "author_framing_or_example",
    "overliteral_wording": "overliteral_wording",
}
# Gold tool_misread_type -> the pipeline guard that should clear it (eval routing).
GUARD_FOR_MISREAD: dict[str, str] = {
    "evidence_gap": "evidence_recheck",
    "cocited_share": "cocited_share",
    "author_framing_or_example": "author_framing_or_example",
    "overliteral_wording": "overliteral_wording",
}


def is_genuine(partial_type: str | None) -> bool:
    """A genuine partial type (coverage_limited included; "none" excluded)."""
    return partial_type in PARTIAL_TYPE_INFO


def guards_from_notes(notes: list[str]) -> list[str]:
    """Benign notes -> guard names, in GUARD_ORDER, without duplicates."""
    found = {GUARD_FOR_NOTE[n] for n in notes if n in GUARD_FOR_NOTE}
    return [g for g in GUARD_ORDER if g in found]


def default_severity(partial_type: str | None) -> str | None:
    """Default severity for a partial type (None for none/unknown)."""
    info = PARTIAL_TYPE_INFO.get(partial_type or "")
    return info[2] if info else None


def author_action(partial_type: str | None, element: str | None = None) -> str:
    """One-sentence author action for a type, naming the element when known."""
    template = AUTHOR_ACTIONS.get(partial_type or "")
    if not template:
        return ""
    element = (element or "").strip().strip(".")
    return template.format(element=f" ('{element}')" if element else "")
