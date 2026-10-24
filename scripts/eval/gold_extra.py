"""Gold rows for labelled pairs that no review A/B verdict covers (review_C/D), and their split.

A labels-file entry whose gold_source is a NEW_ROW_SOURCES value names a
(sentence, reference) pair of the session by pair id; its row is built from the
session's claim/reference exactly like a reviewed pair (gold_merge.pair_fields).
A source may come from another run of the same manuscript (`sessions`: review_D
reviewed a later run). The split stays by reference: a new pair joins the split
its paper already has (same DOI/ref group, reference number or title); pairs of
papers new to the gold set are split by the same deterministic stratified rule
(assign_splits). Sources join one after another (join_in_stages), so neither the
existing rows nor an earlier source's new rows ever move.
"""

import logging
from collections.abc import Mapping

from gold_annotate import review_fields
from gold_db import SessionData
from gold_merge import pair_fields
from gold_models import OVERRIDE_FIELDS, GoldRow, LabelOverride, binary_of, pair_id
from gold_split import DEFAULT_DEV_FRACTION, DEFAULT_SEED, assign_splits, group_key

logger = logging.getLogger(__name__)
NEW_ROW_SOURCES = ("review_C", "review_D")  # join order: earlier sources never move
Spot = tuple[int, int]  # (claim number, reference number)


def session_pairs(session: SessionData) -> dict[str, list[Spot]]:
    """pair id -> every (claim number, reference) of the session with that pair id."""
    pairs: dict[str, list[Spot]] = {}
    for claim in session.claims:
        for ref in claim.refs:
            pairs.setdefault(pair_id(claim.sentence, ref), []).append((claim.number, ref))
    return pairs


def locate(entry: LabelOverride, spots: list[Spot]) -> Spot | None:
    """The labelled pair's claim: the entry's claim_number when it is one of the spots."""
    spots = [s for s in spots if entry.ref is None or s[1] == entry.ref]
    own = [s for s in spots if s[0] == entry.claim_number]
    if own:
        return own[0]
    return spots[0] if spots else None


def case_number(cases: list[str], tag: str = "C") -> int | None:
    """The review case of an entry's cases list (["C:4"] -> 4)."""
    for case in cases:
        prefix, _, number = case.partition(":")
        if prefix == tag and number.strip().isdigit():
            return int(number)
    return None


def label_row(pid: str, entry: LabelOverride, spot: Spot, session: SessionData) -> GoldRow:
    """A gold row built from the session pair and the labels entry alone."""
    claim = next(c for c in session.claims if c.number == spot[0])
    label = entry.gold_label or "cannot_judge"
    exclude = entry.exclude if entry.exclude is not None else label == "cannot_judge"
    fields = {name: getattr(entry, name) for name in OVERRIDE_FIELDS
              if getattr(entry, name) is not None}
    return GoldRow.model_validate({
        "id": pid, **pair_fields(session, claim, spot[1]), **fields,
        "gold_label": label, "gold_binary": binary_of(label), "gold_source": entry.gold_source,
        "exclude": exclude, "exclude_reason": "labels file" if exclude else "",
        **review_fields(entry)})


def extra_rows(labels: dict[str, LabelOverride], known: set[str], session: SessionData,
               sessions: Mapping[str, SessionData] | None = None,
               ) -> tuple[list[GoldRow], list[str]]:
    """Rows for new-source entries that are not reviewed pairs; plus ids not in the session.

    sessions: gold_source -> the run that source reviewed (default: `session`).
    """
    by_source = dict(sessions or {})
    pairs = {sid: session_pairs(s) for sid, s in
             {s.session_id: s for s in [session, *by_source.values()]}.items()}
    rows: list[GoldRow] = []
    missing: list[str] = []
    for pid, entry in sorted(labels.items()):
        if pid in known or entry.gold_source not in NEW_ROW_SOURCES:
            continue
        run = by_source.get(entry.gold_source or "", session)
        spot = locate(entry, pairs[run.session_id].get(pid, []))
        if spot is None or entry.gold_label is None:
            logger.warning("labels file: %s (%s) is not a labelled pair of %s; skipped", pid,
                           entry.gold_source, run.session_id)
            missing.append(pid)
            continue
        rows.append(label_row(pid, entry, spot, run))
    return rows, missing


def split_keys(row: GoldRow) -> list[str]:
    """Paper identities that must not straddle splits: DOI/ref group, ref number, title."""
    title = " ".join(row.ref_title.lower().split())
    return [group_key(row), f"ref:{row.ref}"] + ([f"title:{title}"] if title else [])


def join_splits(base: list[GoldRow], extra: list[GoldRow],
                dev_fraction: float = DEFAULT_DEV_FRACTION, seed: int = DEFAULT_SEED,
                ) -> tuple[list[GoldRow], dict[str, str]]:
    """Extra rows with `split` set, plus pair id -> "joined dev" / "assigned test" etc."""
    known: dict[str, str] = {}
    for row in base:
        for key in split_keys(row):
            known.setdefault(key, row.split)
    joined: list[GoldRow] = []
    fresh: list[GoldRow] = []
    for row in extra:
        split = next((known[k] for k in split_keys(row) if k in known), None)
        if split is None:
            fresh.append(row)
        else:
            joined.append(row.model_copy(update={"split": split}))
    assigned = assign_splits(fresh, dev_fraction, seed)
    how = {r.id: f"joined {r.split}" for r in joined}
    how.update({r.id: f"assigned {r.split}" for r in assigned})
    return joined + assigned, how


def join_in_stages(base: list[GoldRow], extra: list[GoldRow],
                   dev_fraction: float = DEFAULT_DEV_FRACTION, seed: int = DEFAULT_SEED,
                   ) -> tuple[list[GoldRow], dict[str, str]]:
    """join_splits per source in NEW_ROW_SOURCES order, each against all rows before it."""
    done: list[GoldRow] = []
    how: dict[str, str] = {}
    for source in NEW_ROW_SOURCES:
        batch = [r for r in extra if r.gold_source == source]
        if batch:
            joined, stage = join_splits(base + done, batch, dev_fraction, seed)
            done += joined
            how.update(stage)
    return done, how
