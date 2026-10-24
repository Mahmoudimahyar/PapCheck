"""Dev/test split by reference (stratified by gold label) and labels-file overrides.

The split groups pairs by paper (DOI, else reference number), so a paper's
pairs never sit on both sides, and it is computed from the review-derived
labels BEFORE any labels file is applied: refining labels later never moves
a pair between dev and test.
"""

import logging
import random
from collections import defaultdict
from pathlib import Path

from gold_models import OVERRIDE_FIELDS, GoldRow, LabelOverride, binary_of
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)
DEFAULT_SEED = 49
DEFAULT_DEV_FRACTION = 0.6
# Rarest first: a paper with any negative pair is stratified as "negative".
_STRATUM_RANK = {"not_supported": 0, "contradicted": 0, "not_relevant": 0,
                 "partially_supported": 1, "supported": 2}
_STRATUM_NAMES = ("negative", "partial", "supported", "excluded")


def group_key(row: GoldRow) -> str:
    return f"doi:{row.doi.strip().lower()}" if row.doi else f"ref:{row.ref}"


def _stratum(rows: list[GoldRow]) -> str:
    ranks = [_STRATUM_RANK[r.gold_label] for r in rows
             if not r.exclude and r.gold_label in _STRATUM_RANK]
    return _STRATUM_NAMES[min(ranks)] if ranks else "excluded"


def assign_splits(rows: list[GoldRow], dev_fraction: float = DEFAULT_DEV_FRACTION,
                  seed: int = DEFAULT_SEED) -> list[GoldRow]:
    """Rows with `split` set: ~dev_fraction of each stratum's pairs go to dev."""
    groups: dict[str, list[GoldRow]] = defaultdict(list)
    for row in rows:
        groups[group_key(row)].append(row)
    strata: dict[str, list[str]] = defaultdict(list)
    for key, members in groups.items():
        strata[_stratum(members)].append(key)
    split_of: dict[str, str] = {}
    for name, keys in sorted(strata.items()):
        order = sorted(keys)
        random.Random(f"{seed}:{name}").shuffle(order)
        total = sum(len(groups[k]) for k in order)
        dev = 0
        for key in order:
            size = len(groups[key])
            to_dev = dev + size / 2 <= dev_fraction * total
            split_of[key] = "dev" if to_dev else "test"
            dev += size if to_dev else 0
    return [r.model_copy(update={"split": split_of[group_key(r)]}) for r in rows]


def load_labels(path: Path) -> dict[str, LabelOverride]:
    return TypeAdapter(dict[str, LabelOverride]).validate_json(path.read_bytes())


def load_label_files(paths: list[Path]) -> dict[str, LabelOverride]:
    """Several labels files merged; a pair id may appear in only one of them.

    keep_existing entries only annotate a labelled pair (gold_annotate) and are left out.
    """
    merged: dict[str, LabelOverride] = {}
    for path in paths:
        labels = {k: v for k, v in load_labels(path).items() if not v.keep_existing}
        clash = sorted(set(labels) & set(merged))
        if clash:
            raise ValueError(f"{path}: pair ids already labelled by an earlier file: {clash}")
        merged.update(labels)
    return merged


def _override(row: GoldRow, entry: LabelOverride) -> GoldRow:
    update: dict[str, object] = {}
    for name in OVERRIDE_FIELDS:
        value = getattr(entry, name)
        if value is not None:
            update[name] = value
    if entry.gold_label is not None:
        if row.needs_adjudication or entry.gold_label != row.gold_label:
            update.update(gold_source="adjudicated", needs_adjudication=False)
        update["gold_label"] = entry.gold_label
        update["gold_binary"] = binary_of(entry.gold_label)
        if entry.gold_label == "cannot_judge":
            update.update(exclude=True, exclude_reason="labels file: cannot_judge")
        elif row.exclude and entry.exclude is None:
            update.update(exclude=False, exclude_reason="")
    if entry.exclude is not None:
        update["exclude"] = entry.exclude
        update["exclude_reason"] = "labels file" if entry.exclude else ""
    return row.model_copy(update=update)


def apply_labels(rows: list[GoldRow], labels: dict[str, LabelOverride],
                 ) -> tuple[list[GoldRow], list[str]]:
    """Rows with the labels file applied, plus label ids that match no row."""
    known = {r.id for r in rows}
    unknown = sorted(set(labels) - known)
    for pid in unknown:
        logger.warning("labels file: %s is not a gold pair; ignored", pid)
    return [_override(r, labels[r.id]) if r.id in labels else r for r in rows], unknown
