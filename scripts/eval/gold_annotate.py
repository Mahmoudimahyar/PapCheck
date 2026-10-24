"""Labels-file entries that annotate pairs the gold set already labels (keep_existing).

A later review (review D: every "supported" verdict of a run) also covers pairs
that earlier reviews labelled and two labellers reconciled. Such an entry never
changes the row's label or split: its gold_label is recorded as the review's
verdict (review_d_verdict), its review cases are recorded, its notes are appended
and its flags added. New pairs of that review become rows through gold_extra.
"""

import logging
from pathlib import Path

from gold_models import GoldRow, LabelOverride
from gold_split import load_labels

logger = logging.getLogger(__name__)


def case_numbers(cases: list[str], tag: str) -> list[int]:
    """Every review case of one tag in an entry's cases list (["D:3", "D:4"] -> [3, 4])."""
    out: list[int] = []
    for case in cases:
        prefix, _, number = case.partition(":")
        if prefix == tag and number.strip().isdigit():
            out.append(int(number))
    return sorted(out)


def review_fields(entry: LabelOverride) -> dict[str, object]:
    """review_c_case / review_d_cases / review_d_verdict of a labels entry."""
    c_cases, d_cases = case_numbers(entry.cases, "C"), case_numbers(entry.cases, "D")
    return {"review_c_case": c_cases[0] if c_cases else None, "review_d_cases": d_cases,
            "review_d_verdict": (entry.gold_label or "") if d_cases else ""}


def load_annotations(paths: list[Path]) -> dict[str, LabelOverride]:
    """keep_existing entries of the labels files; a pair may be annotated only once."""
    merged: dict[str, LabelOverride] = {}
    for path in paths:
        notes = {k: v for k, v in load_labels(path).items() if v.keep_existing}
        clash = sorted(set(notes) & set(merged))
        if clash:
            raise ValueError(f"{path}: pairs already annotated by an earlier file: {clash}")
        merged.update(notes)
    return merged


def _annotated(row: GoldRow, entry: LabelOverride) -> GoldRow:
    fields = review_fields(entry)
    update: dict[str, object] = {
        "flags": row.flags + [f for f in entry.flags or [] if f not in row.flags],
        "notes": " | ".join(p for p in (row.notes, (entry.notes or "").strip()) if p)}
    if fields["review_d_cases"]:
        update.update(review_d_cases=fields["review_d_cases"],
                      review_d_verdict=fields["review_d_verdict"])
    return row.model_copy(update=update)


def _how(row: GoldRow, entry: LabelOverride) -> str:
    if entry.gold_label is None or entry.gold_label == row.gold_label:
        return f"kept {row.gold_label} (review agrees)"
    return f"kept {row.gold_label}; review says {entry.gold_label}"


def annotate(rows: list[GoldRow], annotations: dict[str, LabelOverride],
             ) -> tuple[list[GoldRow], list[str], dict[str, str]]:
    """Rows with the annotations applied, unknown ids, and pair id -> what was kept."""
    known = {r.id for r in rows}
    unknown = sorted(set(annotations) - known)
    for pid in unknown:
        logger.warning("labels file: %s (keep_existing) is not a gold pair; ignored", pid)
    how = {r.id: _how(r, annotations[r.id]) for r in rows if r.id in annotations}
    out = [_annotated(r, annotations[r.id]) if r.id in annotations else r for r in rows]
    return out, unknown, how
