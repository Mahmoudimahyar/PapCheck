"""Helper to apply PDF match results to references."""

from pathlib import Path

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference


def apply_matches(
    references: list[Reference],
    matches: list[MatchResult],
) -> list[Reference]:
    """Apply PDF match results to the reference list.

    Sets pdf_path, pdf_source, and source_status on matched refs.
    """
    match_by_id: dict[int, MatchResult] = {}
    for m in matches:
        if m.match_method != "unmatched" and m.pdf_path:
            match_by_id[m.reference_id] = m

    updated: list[Reference] = []
    for ref in references:
        if ref.id in match_by_id:
            m = match_by_id[ref.id]
            updated.append(ref.model_copy(update={
                "pdf_path": Path(m.pdf_path) if m.pdf_path else None,
                "pdf_source": "user_upload",
                "source_status": "found",
            }))
        else:
            updated.append(ref)
    return updated
