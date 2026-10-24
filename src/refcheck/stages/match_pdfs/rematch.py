"""Second chance for references the first matching pass left without a usable PDF.

Before a reference falls back to its abstract (no PDF linked, or the linked
PDF is a supplement, a scan without text, or another paper) the uploaded PDFs
that no other reference holds confidently are searched for its DOI (printed,
whitespace-tolerant) and its title (aligned with page 1, plus first author and
year). Supplements and scans are never linked; the identity gate (the resolve
stage's identity check, injected by the runner because stages do not import
each other) must not report a mismatch, and must report "verified" for a link
made on the title alone. A PDF another reference holds confidently is reused
only for a duplicate entry of the same work.
"""

import logging
from pathlib import Path

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.rematch_evidence import RematchMethod, assess, decide
from refcheck.stages.match_pdfs.rematch_models import (
    IdentityGate,
    PdfReader,
    RejectReason,
    RematchOutcome,
    RematchRecord,
)
from refcheck.stages.match_pdfs.rematch_select import (
    Candidate,
    contested,
    pick_candidate,
    same_reference_paper,
)

logger = logging.getLogger(__name__)

_CONFIDENCE: dict[RematchMethod, float] = {"rematch_doi": 0.97, "rematch_title": 0.92}


def rematch_or_keep(
    references: list[Reference],
    results: list[MatchResult],
    pdf_dir: Path,
    identity: IdentityGate | None = None,
) -> RematchOutcome:
    """`rematch_pdfs`, but an unexpected failure keeps the first-pass results."""
    try:
        return rematch_pdfs(references, results, pdf_dir, identity)
    except Exception:  # the re-match is a best-effort second pass; never fail the stage
        logger.exception("PDF re-match failed; keeping the first-pass matches")
        return RematchOutcome(results=list(results))


def rematch_pdfs(
    references: list[Reference],
    results: list[MatchResult],
    pdf_dir: Path,
    identity: IdentityGate | None = None,
) -> RematchOutcome:
    """Re-match references without a usable PDF against the uploaded PDFs."""
    pdf_files = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.lower()) \
        if pdf_dir.exists() else []
    if not pdf_files:
        return RematchOutcome(results=list(results))
    reader = PdfReader()
    current = {r.reference_id: r for r in results if r.match_method != "unmatched" and r.pdf_path}
    rejected = {ref.id: reason for ref in references
                if (reason := _rejection(ref, current.get(ref.id), reader, identity))}
    held = _held_pdfs(references, current, rejected)
    by_id = {r.id: r for r in references}
    records: list[RematchRecord] = []
    for ref_id, reason in rejected.items():
        ref = by_id[ref_id]
        pool = [p for p in pdf_files if _available(ref, p, current.get(ref_id), held, by_id)]
        chosen = pick_candidate(ref, _qualifying(ref, pool, reader, identity))
        if chosen is None or contested(ref, chosen, references):
            continue
        old = current.get(ref_id)
        records.append(RematchRecord(
            reference_id=ref_id, pdf_path=chosen.profile.path, method=chosen.method,
            reason=reason, replaced_pdf=old.pdf_path if old else None,
        ))
        logger.info("Re-match: ref %d -> %s (%s; first pass: %s)",
                    ref_id, chosen.profile.name, chosen.method, reason)
    return RematchOutcome(results=_merge(results, records), records=records, rejected=rejected)


def _rejection(
    ref: Reference, match: MatchResult | None, reader: PdfReader,
    identity: IdentityGate | None,
) -> RejectReason | None:
    """Why the first-pass PDF cannot stand for the reference (None: it can)."""
    if match is None or not match.pdf_path:
        return "no_pdf"
    return pdf_rejection(ref, Path(match.pdf_path), reader, identity)


def pdf_rejection(
    ref: Reference, path: Path, reader: PdfReader, identity: IdentityGate | None,
) -> RejectReason | None:
    """Why `path` cannot stand for the reference: supplement, no text, scan, another paper."""
    if reader.supplement(path):
        return "supplement"
    profile = reader.profile(path)
    if profile is None or not profile.has_text:
        return "no_text"
    if profile.scanned:
        return "scanned"
    if identity is not None and identity(ref, path) == "mismatch":
        return "identity_mismatch"
    return None


def _held_pdfs(
    references: list[Reference], current: dict[int, MatchResult],
    rejected: dict[int, RejectReason],
) -> dict[str, list[int]]:
    """PDF path -> references that hold it confidently (accepted first-pass matches)."""
    held: dict[str, list[int]] = {}
    for ref in references:
        match = current.get(ref.id)
        if match and match.pdf_path and ref.id not in rejected \
                and not match.needs_user_confirmation:
            held.setdefault(str(Path(match.pdf_path)), []).append(ref.id)
    return held


def _available(
    ref: Reference, path: Path, own: MatchResult | None,
    held: dict[str, list[int]], by_id: dict[int, Reference],
) -> bool:
    """A PDF the reference may be re-matched to (not its own rejected one)."""
    if own is not None and own.pdf_path and Path(own.pdf_path) == path:
        return False
    holders = held.get(str(path), [])
    return all(same_reference_paper(ref, by_id[h]) for h in holders)


def _qualifying(
    ref: Reference, pool: list[Path], reader: PdfReader, identity: IdentityGate | None,
) -> list[Candidate]:
    """Usable, non-supplement PDFs whose first pages support the reference."""
    found: list[Candidate] = []
    for path in pool:
        profile = reader.profile(path)
        if profile is None or not profile.usable:
            continue
        evidence = assess(ref, profile)
        method = decide(ref, evidence)
        if method is None or reader.supplement(path):
            continue
        if identity is not None and not _identity_allows(method, identity(ref, path)):
            continue
        found.append(Candidate(profile=profile, evidence=evidence, method=method))
    return found


def _identity_allows(method: RematchMethod, status: str) -> bool:
    """A printed DOI tolerates an inconclusive identity check; a title-only link does not."""
    return status == "verified" or (method == "rematch_doi" and status != "mismatch")


def _merge(results: list[MatchResult], records: list[RematchRecord]) -> list[MatchResult]:
    """First-pass results with the re-matched references' results replaced."""
    new = {rec.reference_id: MatchResult(
        reference_id=rec.reference_id, pdf_path=rec.pdf_path,
        confidence=_CONFIDENCE[rec.method], match_method=rec.method,
        needs_user_confirmation=False,
    ) for rec in records}
    kept = [r for r in results if r.reference_id not in new]
    return kept + list(new.values())
