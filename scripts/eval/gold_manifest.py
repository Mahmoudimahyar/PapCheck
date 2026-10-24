"""Manifest of a refcheck_v49_gold build (counts, inputs, labels files, case -> pair ids)."""

import argparse
import hashlib
from collections import Counter
from pathlib import Path

from gold_models import GoldRow
from pydantic import BaseModel, Field


class GoldManifest(BaseModel):
    dataset: str
    session_id: str
    seed: int
    dev_fraction: float
    labels_file: str = ""  # first labels file (kept for older readers)
    labels_sha: str = ""  # sha256[:16] over all labels files' bytes, in order
    labels_files: list[str] = Field(default_factory=list)
    labels_shas: dict[str, str] = Field(default_factory=dict)
    n_rows: int
    n_excluded: int
    by_split: dict[str, dict[str, int]] = Field(default_factory=dict)  # split -> label -> n
    by_source: dict[str, int] = Field(default_factory=dict)
    by_confidence: dict[str, int] = Field(default_factory=dict)
    needs_adjudication: list[str] = Field(default_factory=list)
    excluded: dict[str, str] = Field(default_factory=dict)  # pair id -> reason
    unmatched_reviews: list[str] = Field(default_factory=list)
    unknown_label_ids: list[str] = Field(default_factory=list)
    added_from_labels: dict[str, str] = Field(default_factory=dict)  # pair id -> split decision
    # keep_existing entries: pair id -> "kept <label> (review agrees)" / "...; review says X"
    annotated_from_labels: dict[str, str] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    case_ids: dict[str, str] = Field(default_factory=dict)  # "A:12"/"B:40"/"C:4"/"D:7" -> pair id


def _sha(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16] if paths else ""


def _case_ids(rows: list[GoldRow]) -> dict[str, str]:
    ids = {f"{tag}:{case}": r.id for r in rows
           for tag, case in (("A", r.review_a_case), ("B", r.review_b_case),
                             ("C", r.review_c_case)) if case is not None}
    ids.update({f"D:{case}": r.id for r in rows for case in r.review_d_cases})
    return ids


def _inputs(args: argparse.Namespace) -> dict[str, str]:
    inputs = {"review_a": str(args.review_a), "review_b": str(args.review_b),
              "notes_a": str(args.notes_a) if args.notes_a.is_file() else "",
              "db": str(args.db)}
    for item in getattr(args, "source_session", None) or []:
        source, _, sid = item.partition("=")
        inputs[f"session:{source.strip()}"] = sid.strip()
    return inputs


def build_manifest(rows: list[GoldRow], args: argparse.Namespace, unmatched: list[str],
                   unknown: list[str], added: dict[str, str],
                   annotated: dict[str, str] | None = None) -> GoldManifest:
    """Counts over the kept rows plus the provenance of the build."""
    kept = [r for r in rows if not r.exclude]
    labels: list[Path] = list(args.labels or [])
    return GoldManifest(
        dataset=args.name, session_id=args.session, seed=args.seed,
        dev_fraction=args.dev_fraction, labels_file=str(labels[0]) if labels else "",
        labels_sha=_sha(labels), labels_files=[str(p) for p in labels],
        labels_shas={str(p): _sha([p]) for p in labels}, n_rows=len(rows),
        n_excluded=len(rows) - len(kept),
        by_split={split: dict(Counter(r.gold_label for r in kept if r.split == split))
                  for split in ("dev", "test")},
        by_source=dict(Counter(r.gold_source for r in kept)),
        by_confidence=dict(Counter(r.gold_confidence for r in kept)),
        needs_adjudication=[r.id for r in rows if r.needs_adjudication],
        excluded={r.id: r.exclude_reason for r in rows if r.exclude},
        unmatched_reviews=unmatched, unknown_label_ids=unknown, added_from_labels=added,
        annotated_from_labels=annotated or {}, inputs=_inputs(args), case_ids=_case_ids(rows))
