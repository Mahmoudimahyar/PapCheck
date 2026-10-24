"""Co-cited references' sources for gold rows (the co-cited union check, cascade mode).

In the app every reference of a sentence is a pair of the run, so its source is
already loaded (verifier.run.sources). A gold run holds only the rows of its
split, so each co-cited reference (co_cited_refs) is found, in this order:

1. a reference of this run (already resolved: same document object);
2. another gold row with the same reference number and session, in ANY split
   (the full refcheck_v49_gold.jsonl, excluded rows included: their reference
   data is still valid), preferring a row with a PDF, then one with an abstract;
3. the session's reference in ~/.refcheck/refcheck.db, opened read-only
   (gold_db: --session, else the gold row's own session_id), with the
   duplicate-entry inheritance of production (gold_db.production_pdf).

Each found reference is loaded with the production loader
(eval_gold.resolve_references: identity re-check, resolve_source).
"""

import json
import logging
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from eval_gold import gold_co_cited, gold_reference, resolve_references
from eval_models import EvalItem, SourceMode
from gold_db import DEFAULT_DB, DbReference, load_session, production_pdf
from gold_models import GoldRow

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import ResolvedSource

logger = logging.getLogger(__name__)
_IDENTITY = ("verified", "unverified", "mismatch")


def wanted(items: Iterable[EvalItem]) -> dict[int, str]:
    """Co-cited reference number -> the session of the first row naming it."""
    out: dict[int, str] = {}
    for item in items:
        row = item.gold_row
        for ref in gold_co_cited(row) if row is not None else []:
            out.setdefault(ref.number, row.session_id if row is not None else "")
    return out


def _rank(row: GoldRow) -> int:
    return 0 if row.pdf_path else 1 if row.abstract else 2


def gold_pool(path: Path) -> dict[tuple[str, int], GoldRow]:
    """(session, reference number) -> the best gold row for that reference (module doc)."""
    rows: dict[tuple[str, int], list[GoldRow]] = defaultdict(list)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip() and "gold_source" in json.loads(line):
                row = GoldRow.model_validate_json(line)
                rows[(row.session_id, row.ref)].append(row)
    return {key: min(found, key=_rank) for key, found in rows.items()}


def db_reference(refs: dict[int, DbReference], number: int) -> Reference | None:
    """The session's reference as verification sees it, or None."""
    if (found := refs.get(number)) is None:
        return None
    ref = production_pdf(refs, found)
    status = ref.identity_status if ref.identity_status in _IDENTITY else "unverified"
    return Reference(
        id=number, title=ref.title, authors=ref.authors, year=ref.year, doi=ref.doi,
        pdf_path=Path(ref.pdf_path) if ref.pdf_path else None,
        source_status="found" if ref.pdf_path or ref.abstract else "not_found",
        abstract_text=ref.abstract, abstract_source=ref.abstract_source,
        identity_status=status)  # type: ignore[arg-type]


def _from_db(missing: dict[int, str], session: str, db_path: Path) -> dict[int, Reference]:
    found: dict[int, Reference] = {}
    for sess in sorted({session or s for s in missing.values() if session or s}):
        try:
            refs = load_session(sess, db_path, with_verifications=False).references
        except (ValueError, OSError, sqlite3.Error) as exc:  # no such session / DB
            logger.warning("co-cited sources: session %s unreadable (%s)", sess, exc)
            continue
        for number, row_session in missing.items():
            if (session or row_session) == sess and (ref := db_reference(refs, number)):
                found[number] = ref
    return found


async def resolve_cocited_sources(items: list[EvalItem], resolved: dict[str, ResolvedSource],
                                  source: SourceMode, pool_path: Path, session: str = "",
                                  db_path: Path = DEFAULT_DB) -> dict[int, SourceDocument]:
    """Reference number -> loaded source of every co-cited reference found (module doc)."""
    need = wanted(items)
    docs = {n: r.doc for n in need if (r := resolved.get(f"ref{n}")) and r.doc is not None}
    missing = {n: s for n, s in need.items() if f"ref{n}" not in resolved}
    pool = gold_pool(pool_path) if missing else {}
    refs = {n: gold_reference(pool[(s, n)]) for n, s in missing.items() if (s, n) in pool}
    rest = {n: s for n, s in missing.items() if n not in refs}
    from_db = _from_db(rest, session, db_path) if rest else {}
    logger.info("co-cited sources: %d wanted, %d in this run, %d from other gold rows, %d "
                "from the DB", len(need), len(need) - len(missing), len(refs), len(from_db))
    refs.update(from_db)
    if refs:
        loaded = await resolve_references({f"ref{n}": r for n, r in refs.items()}, source)
        docs.update({int(k[3:]): r.doc for k, r in loaded.items() if r.doc is not None})
    logger.info("co-cited sources: %d of %d usable", len(docs), len(need))
    return docs
