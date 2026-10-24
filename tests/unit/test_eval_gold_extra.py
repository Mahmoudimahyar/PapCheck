"""Unit tests for gold-builder follow-ups: new label fields, review_C rows, split joining,
several labels files and co-cited abstracts (synthetic reviews + a synthetic read-only DB)."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import build_refcheck_gold  # noqa: E402
from gold_db import clip_abstract, load_session  # noqa: E402
from gold_extra import case_number, extra_rows, join_splits  # noqa: E402
from gold_merge import build_rows  # noqa: E402
from gold_models import GoldRow, LabelOverride, pair_id  # noqa: E402
from gold_reviews import load_review_a, load_review_b  # noqa: E402
from gold_split import apply_labels, assign_splits, load_label_files  # noqa: E402

from tests.unit.test_eval_gold_build import (  # noqa: E402
    S1,
    S2,
    S3,
    SESSION,
    make_db,
    write_reviews,
)

S5 = "V lowers rejection in pigs (Kim, 2019; Park, 2022)."
S6 = "U is a common biomaterial (Smith, 2020b)."
# Unreviewed pairs: S5 cites ref 4 (already gold) and new ref 5; S6 cites ref 6, a new
# entry whose title equals ref 1's (same paper, no DOI).
NEW_CLAIMS = [(6, S5, [4], 2), (7, S5, [5], 2), (8, S6, [6], 1)]
NEW_REFS = [(5, "Park trial", "10.1/c", ""), (6, "Drug X in mice", None, "")]


def make_db_c(path: Path) -> Path:
    make_db(path)
    con = sqlite3.connect(path)
    for num, sent, refs, co in NEW_CLAIMS:
        con.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (SESSION, num, sent, sent.split(" (")[0], json.dumps(refs), sent,
                     "2. Results", "factual", "ok", co, ""))
    for ref, title, doi, abstract in NEW_REFS:
        con.execute('INSERT INTO "references" VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (SESSION, ref, title, "[]", 2022, doi, None, abstract or None, None,
                     "verified", None))
    con.commit()
    con.close()
    return path


def c_entry(label: str, claim: int, ref: int, case: int, **extra: object) -> dict[str, object]:
    return {"gold_label": label, "gold_partial_type": extra.pop("ptype", ""),
            "gold_source": "review_C", "claim_number": claim, "ref": ref,
            "cases": [f"C:{case}"], "secondary_types": ["cocited_share"], "severity": "none",
            "flags": ["secondary_source"], "gold_basis": "full_text", "gold_confidence": "high",
            "tool_misread_types": [], "notes": "C: synthetic", **extra}


def labels_c() -> dict[str, dict[str, object]]:
    return {pair_id(S5, 4): c_entry("supported", 6, 4, 1),
            pair_id(S5, 5): c_entry("partially_supported", 7, 5, 2, ptype="missing_element",
                                    severity="minor", partial_types=["missing_element"]),
            pair_id(S6, 6): c_entry("supported", 8, 6, 3),
            "v49-notapair000": c_entry("supported", 99, 9, 4)}


def base_rows(tmp_path: Path) -> tuple[list[GoldRow], object]:
    session = load_session(SESSION, make_db_c(tmp_path / "db.sqlite"), with_verifications=False)
    a, notes, b = write_reviews(tmp_path)
    rows, _ = build_rows(load_review_a(a, notes) + load_review_b(b), session)
    return assign_splits(rows, seed=7), session


def test_clip_abstract_cuts_at_word_boundary_and_maps_empty_to_none() -> None:
    assert clip_abstract("  a  b\n c ") == "a b c"
    assert clip_abstract("alpha beta gamma", limit=11) == "alpha beta"
    assert clip_abstract("abcdefgh", limit=4) == "abcd"
    assert clip_abstract("") is None and clip_abstract(None) is None


def test_co_cited_refs_carry_the_db_abstract(tmp_path: Path) -> None:
    rows, _ = base_rows(tmp_path)
    row = next(r for r in rows if r.id == pair_id(S1, 1))
    assert [(c.ref, c.abstract) for c in row.co_cited_refs] == [(2, "Abstract of Review of Y.")]


def test_label_override_new_fields_reach_the_row(tmp_path: Path) -> None:
    rows, _ = base_rows(tmp_path)
    labels = {pair_id(S2, 3): LabelOverride(
        gold_basis="abstract", secondary_types=["certainty_overstated"], severity="major",
        flags=["reconciled"], partial_types=["missing_element", "certainty_overstated"],
        tool_misread_types=[])}
    out, _ = apply_labels(rows, labels)
    row = next(r for r in out if r.id == pair_id(S2, 3))
    assert (row.gold_basis, row.severity, row.flags) == ("abstract", "major", ["reconciled"])
    assert row.partial_types == ["missing_element", "certainty_overstated"]
    assert row.secondary_types == ["certainty_overstated"] and row.tool_misread_types == []
    untouched = next(r for r in out if r.id == pair_id(S3, 4))
    assert untouched.severity == "" and untouched.flags == []


def test_extra_rows_are_built_from_the_session(tmp_path: Path) -> None:
    rows, session = base_rows(tmp_path)
    labels = {k: LabelOverride.model_validate(v) for k, v in labels_c().items()}
    extra, missing = extra_rows(labels, {r.id for r in rows}, session)
    by_id = {r.id: r for r in extra}
    assert missing == ["v49-notapair000"] and len(extra) == 3
    partial = by_id[pair_id(S5, 5)]
    assert partial.gold_source == "review_C" and partial.review_c_case == 2
    assert (partial.claim_number, partial.ref, partial.doi) == (7, 5, "10.1/c")
    assert partial.gold_binary == "problem" and partial.severity == "minor"
    assert [c.ref for c in partial.co_cited_refs] == [4] and partial.co_cited_count == 2
    assert by_id[pair_id(S5, 4)].gold_binary == "ok" and by_id[pair_id(S5, 4)].flags == [
        "secondary_source"]


def test_join_splits_keeps_papers_on_one_side(tmp_path: Path) -> None:
    rows, session = base_rows(tmp_path)
    labels = {k: LabelOverride.model_validate(v) for k, v in labels_c().items()}
    extra, _ = extra_rows(labels, {r.id for r in rows}, session)
    joined, how = join_splits(rows, extra, seed=7)
    split = {r.id: r.split for r in joined}
    ref_split = {r.ref: r.split for r in rows}
    assert split[pair_id(S5, 4)] == ref_split[4] and how[pair_id(S5, 4)].startswith("joined")
    assert split[pair_id(S6, 6)] == ref_split[1]  # same title as ref 1 -> same paper
    assert how[pair_id(S5, 5)] == f"assigned {split[pair_id(S5, 5)]}"


def test_case_number_and_label_files_merge(tmp_path: Path) -> None:
    assert case_number(["B:3", "C:12"]) == 12 and case_number(["A:1"]) is None
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    first.write_text(json.dumps({"v49-x": {"gold_label": "supported"}}), encoding="utf-8")
    second.write_text(json.dumps({"v49-y": {"severity": "minor"}}), encoding="utf-8")
    assert set(load_label_files([first, second])) == {"v49-x", "v49-y"}
    with pytest.raises(ValueError, match="already labelled"):
        load_label_files([first, first])


def test_build_cli_adds_review_c_rows_without_moving_existing_ones(tmp_path: Path) -> None:
    db = make_db_c(tmp_path / "db.sqlite")
    a, notes, b = write_reviews(tmp_path)
    final, extra = tmp_path / "labels_final.json", tmp_path / "labels_c.json"
    final.write_text(json.dumps({pair_id(S2, 3): {"gold_label": "not_supported"}}),
                     encoding="utf-8")
    extra.write_text(json.dumps(labels_c()), encoding="utf-8")
    common = ["--review-a", str(a), "--notes-a", str(notes), "--review-b", str(b), "--db",
              str(db), "--session", SESSION, "--name", "g", "--seed", "7"]
    one = build_refcheck_gold.build(build_refcheck_gold.parse_args(
        [*common, "--labels", str(final), "--out-dir", str(tmp_path / "one")]))
    two = build_refcheck_gold.build(build_refcheck_gold.parse_args(
        [*common, "--labels", str(final), "--labels", str(extra), "--out-dir",
         str(tmp_path / "two")]))
    before = {r.id: (r.split, r.gold_label) for r in one}
    after = {r.id: (r.split, r.gold_label) for r in two}
    assert len(two) == len(one) + 3 and all(after[k] == v for k, v in before.items())
    manifest = json.loads((tmp_path / "two" / "g.manifest.json").read_text(encoding="utf-8"))
    assert manifest["by_source"]["review_C"] == 3 and len(manifest["labels_files"]) == 2
    assert manifest["unknown_label_ids"] == ["v49-notapair000"]
    assert manifest["case_ids"]["C:2"] == pair_id(S5, 5) and len(manifest["added_from_labels"]) == 3
    single = json.loads((tmp_path / "one" / "g.manifest.json").read_text(encoding="utf-8"))
    assert single["labels_sha"] == hashlib.sha256(final.read_bytes()).hexdigest()[:16]
    line = json.loads((tmp_path / "two" / "g.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert {"severity", "flags", "secondary_types", "partial_types", "tool_misread_types",
            "review_c_case"} <= set(line)
