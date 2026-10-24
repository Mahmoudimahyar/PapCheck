"""Human-readable stage-complete messages (SSE events) for stages 1, 2 and 4.

They name the bibliography problems a stage found (duplicate entries,
citations that fit several references, incomplete sentences, repaired
titles, wrong-paper PDFs) so the user sees them while the pipeline runs,
not only in the final report.
"""

from refcheck.models.claim import Claim
from refcheck.models.reference import ParsedManuscript, Reference


def _with_details(head: str, details: dict[tuple[str, str], int]) -> str:
    """``head (2 duplicate entries, 1 incomplete sentence)``; zero counts are left out."""
    extra = [f"{n} {one if n == 1 else many}" for (one, many), n in details.items() if n]
    return f"{head} ({', '.join(extra)})" if extra else head


def parse_summary(manuscript: ParsedManuscript) -> str:
    """Stage 1: reference count plus duplicate entries."""
    refs = manuscript.references
    return _with_details(f"{len(refs)} references extracted", {
        ("duplicate entry", "duplicate entries"):
            sum(1 for r in refs if r.duplicate_of is not None),
    })


def detect_summary(citation_count: int, claims: list[Claim]) -> str:
    """Stage 2: citation / claim counts plus mapping and sentence problems."""
    return _with_details(f"{citation_count} citations, {len(claims)} claims", {
        ("ambiguous citation mapping", "ambiguous citation mappings"):
            sum(1 for c in claims if c.mapping_ambiguous),
        ("incomplete sentence", "incomplete sentences"):
            sum(1 for c in claims if c.claim_quality == "fragment"),
    })


def resolve_summary(refs: list[Reference]) -> str:
    """Stage 4 outcome for the stage-complete event."""
    counts = {
        "found": sum(1 for r in refs if r.source_status == "found"),
        "not found": sum(1 for r in refs if r.source_status == "not_found"),
        "with abstract": sum(1 for r in refs if r.abstract_text),
        "PDF identity mismatch": sum(1 for r in refs if r.identity_status == "mismatch"),
        "retracted": sum(1 for r in refs if r.retraction_status == "retracted"),
        "with title from DOI/PMID record": sum(
            1 for r in refs if r.repair_applied == "title_from_api"),
    }
    parts = [f"{counts['found']} found"]
    parts += [f"{n} {label}" for label, n in counts.items() if n and label != "found"]
    return ", ".join(parts)
