"""Dry run of the match-stage PDF re-match on a recorded session (no writes, no APIs).

Reads the session's references from ~/.refcheck/refcheck.db opened READ-ONLY
(`mode=ro` URI), rebuilds the first-pass matches from the stored user-upload
PDF paths (mapped by file name into --pdf-dir), runs the re-match with the
resolve stage's identity gate and logs which references would be linked.
Library/open-access PDFs are attached after the match stage, so those
references count as "no PDF" here, as they would in a real run.

    python scripts/rematch_dry_run.py --session <session id> \
        --pdf-dir <folder of the uploaded PDFs> --explain 3,14
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.pdf_profile import read_pdf_profile
from refcheck.stages.match_pdfs.rematch import rematch_pdfs
from refcheck.stages.match_pdfs.rematch_evidence import assess, decide
from refcheck.stages.match_pdfs.rematch_models import RematchOutcome
from refcheck.stages.resolve_gaps.pdf_identity import pdf_identity_status

logger = logging.getLogger("rematch_dry_run")

DEFAULT_DB = Path.home() / ".refcheck" / "refcheck.db"
_COLUMNS = ("ref_number, title, authors_json, year, doi, pdf_path, pdf_source, "
            "identity_status, duplicate_of")


def load_references(db: Path, session: str) -> list[Reference]:
    """Session references from the database, opened read-only."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f'SELECT {_COLUMNS} FROM "references" WHERE session_id = ? ORDER BY ref_number',
            (session,),
        ).fetchall()
    finally:
        conn.close()
    return [Reference(
        id=r[0], title=r[1] or "", authors=json.loads(r[2] or "[]"), year=r[3], doi=r[4],
        pdf_path=Path(r[5]) if r[5] else None, pdf_source=r[6],
        identity_status=r[7] if r[7] in ("verified", "mismatch") else "unverified",
        duplicate_of=r[8],
    ) for r in rows]


def first_pass(references: list[Reference], pdf_dir: Path) -> list[MatchResult]:
    """Recorded user-upload links, pointed at the copies in pdf_dir."""
    results: list[MatchResult] = []
    for ref in references:
        if ref.pdf_source != "user_upload" or ref.pdf_path is None:
            continue
        local = pdf_dir / ref.pdf_path.name
        if not local.exists():
            logger.warning("ref %d: %s not in %s", ref.id, ref.pdf_path.name, pdf_dir)
            continue
        results.append(MatchResult(reference_id=ref.id, pdf_path=str(local), confidence=0.95,
                                   match_method="title_fuzzy"))
    return results


def explain(ref: Reference, pdf_dir: Path, top: int = 3) -> None:
    """Log the closest uploaded PDFs for one reference with their evidence."""
    rows = []
    for path in sorted(pdf_dir.glob("*.pdf")):
        profile = read_pdf_profile(path)
        if profile is None:
            continue
        ev = assess(ref, profile)
        rows.append((ev.doi_primary, ev.title_alignment, ev.title_coverage, path.name, ev,
                     profile.usable, decide(ref, ev)))
    rows.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    logger.info("ref %d (%s, %s): %s", ref.id, ref.year, ref.doi, ref.title[:90])
    for _, align, cov, name, ev, usable, method in rows[:top]:
        logger.info("    %-60.60s align=%5.1f cov=%.2f author=%s year=%s doi=%s conflict=%s "
                    "usable=%s -> %s", name, align, cov, ev.author_found, ev.year_found,
                    ev.doi_primary, ev.doi_conflict, usable, method or "no")


def report(references: list[Reference], outcome: RematchOutcome) -> None:
    """Log every re-match link with the reference and file name."""
    by_id = {r.id: r for r in references}
    logger.info("Re-matched %d reference(s):", len(outcome.records))
    for rec in outcome.records:
        ref = by_id[rec.reference_id]
        logger.info("  ref %d [%s, first pass: %s] -> %s", rec.reference_id, rec.method,
                    rec.reason, Path(rec.pdf_path).name)
        logger.info("      %s (%s, %s)", ref.title[:100], ref.year, ref.doi)
        status = pdf_identity_status(ref, Path(rec.pdf_path))
        logger.info("      identity check on the new PDF: %s", status)
    linked = {rec.reference_id for rec in outcome.records}
    left = {i: reason for i, reason in outcome.rejected.items() if i not in linked}
    logger.info("Not re-matched (%d): %s", len(left),
                ", ".join(f"{i} ({reason})" for i, reason in sorted(left.items())))


def stress_report(references: list[Reference], outcome: RematchOutcome, pdf_dir: Path) -> None:
    """Compare from-scratch re-match links with the recorded verified links."""
    recorded = {r.id: r for r in references
                if r.pdf_source == "user_upload" and r.identity_status == "verified"}
    agree = differ = extra = 0
    for rec in outcome.records:
        ref = recorded.get(rec.reference_id)
        new = Path(rec.pdf_path).name
        if ref is None:
            extra += 1
            logger.info("  NEW   ref %d -> %s (%s)", rec.reference_id, new, rec.method)
        elif ref.pdf_path is not None and ref.pdf_path.name == new:
            agree += 1
        else:
            differ += 1
            old = ref.pdf_path.name if ref.pdf_path else "-"
            logger.info("  DIFF  ref %d -> %s (%s); recorded %s", rec.reference_id, new,
                        rec.method, old)
    missed = sorted(set(recorded) - {rec.reference_id for rec in outcome.records})
    logger.info("Stress: %d same file, %d other file, %d without a verified recorded link; "
                "%d verified links not re-found: %s", agree, differ, extra, len(missed), missed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--session", required=True, help="session id in the database")
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--explain", default="", help="comma-separated reference numbers")
    parser.add_argument("--stress", action="store_true",
                        help="drop every first-pass link and compare with the recorded ones")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    references = load_references(args.db, args.session)
    if args.stress:
        outcome = rematch_pdfs(references, [], args.pdf_dir, pdf_identity_status)
        stress_report(references, outcome, args.pdf_dir)
        return
    first = first_pass(references, args.pdf_dir)
    logger.info("%d references, %d first-pass user-upload links", len(references), len(first))
    outcome = rematch_pdfs(references, first, args.pdf_dir, pdf_identity_status)
    report(references, outcome)
    wanted = {int(n) for n in args.explain.split(",") if n.strip()}
    for ref in references:
        if ref.id in wanted:
            explain(ref, args.pdf_dir)


if __name__ == "__main__":
    main()
