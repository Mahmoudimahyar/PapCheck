"""Unit tests for review D in the gold builder: rows from a later run (--source-session),
keep_existing annotations, staged split joins (synthetic reviews + a synthetic read-only DB)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import build_refcheck_gold  # noqa: E402
import score_recorded  # noqa: E402
from gold_annotate import annotate, case_numbers, load_annotations  # noqa: E402
from gold_db import load_session  # noqa: E402
from gold_extra import extra_rows, join_in_stages, join_splits  # noqa: E402
from gold_models import LabelOverride  # noqa: E402
from gold_models import pair_id as pid  # noqa: E402
from gold_split import load_label_files  # noqa: E402

from tests.unit.test_eval_gold_build import (  # noqa: E402
    S1,
    S2,
    S3,
    SESSION,
    make_db,
    write_reviews,
)
from tests.unit.test_eval_gold_extra import S5, base_rows, labels_c, make_db_c  # noqa: E402
from tests.unit.test_eval_score_recorded import row  # noqa: E402

D_SESSION = "sess_test_d"
S7 = "Q heals wounds in rats (Ng, 2021)."  # new paper (ref 7)
S8 = "Drug X is cheap to make (Smith, 2020)."  # new pair of a gold paper (ref 1)
CLAIM_COLS = ("claim_number, manuscript_text, extracted_claim, reference_ids_json, paragraph_text, "
              "section_heading, claim_type, claim_quality, co_cited_count, cited_for")
REF_COLS = ("ref_number, title, authors_json, year, doi, pdf_path, abstract_text, abstract_source, "
            "identity_status, duplicate_of")


def make_db_d(path: Path) -> Path:
    """The review-C DB plus a later run of the same manuscript (claims renumbered +100)."""
    make_db_c(path)
    con = sqlite3.connect(path)
    con.execute(f"INSERT INTO claims (session_id, {CLAIM_COLS}) SELECT ?, claim_number + 100, "
                f"{CLAIM_COLS.split(', ', 1)[1]} FROM claims WHERE session_id = ?",
                (D_SESSION, SESSION))
    con.execute(f'INSERT INTO "references" (session_id, {REF_COLS}) SELECT ?, {REF_COLS} '
                'FROM "references" WHERE session_id = ?', (D_SESSION, SESSION))
    for num, sent, ref in ((201, S7, 7), (202, S8, 1)):
        con.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (D_SESSION, num, sent, sent.split(" (")[0], json.dumps([ref]),
                     f"Para. {sent}", "3. Discussion", "factual", "ok", 1, ""))
    con.execute('INSERT INTO "references" VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (D_SESSION, 7, "Q in rats", "[]", 2021, "10.1/q", None, "Q abstract.", "pubmed",
                 "verified", None))
    con.commit()
    con.close()
    return path


def d_entry(label: str, claim: int, ref: int, cases: list[int],
            **extra: object) -> dict[str, object]:
    return {"gold_label": label, "gold_partial_type": extra.pop("ptype", ""),
            "gold_source": "review_D", "claim_number": claim, "ref": ref,
            "cases": [f"D:{c}" for c in cases], "severity": extra.pop("severity", "none"),
            "flags": extra.pop("flags", ["second_reviewed"]), "gold_confidence": "high",
            "gold_basis": "full_text", "tool_misread_types": [], "notes": "D: synthetic", **extra}


def labels_d() -> dict[str, dict[str, object]]:
    return {pid(S7, 7): d_entry("partially_supported", 201, 7, [2, 1], ptype="missing_element",
                                severity="minor", partial_types=["missing_element"]),
            pid(S8, 1): d_entry("supported", 202, 1, [3]),
            pid(S3, 4): d_entry("partially_supported", 104, 4, [4], keep_existing=True,
                                flags=["review_d_disagrees", "pattern_L2"]),
            pid(S5, 4): d_entry("supported", 106, 4, [5], keep_existing=True, flags=[])}


def write(path: Path, data: dict[str, object]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_keep_existing_entries_annotate_instead_of_labelling(tmp_path: Path) -> None:
    labels_file = write(tmp_path / "d.json", labels_d())
    assert set(load_label_files([labels_file])) == {pid(S7, 7), pid(S8, 1)}
    assert set(load_annotations([labels_file])) == {pid(S3, 4), pid(S5, 4)}
    other = write(tmp_path / "x.json", {pid(S3, 4): {"gold_label": "supported"}})
    assert set(load_label_files([labels_file, other])) == {pid(S7, 7), pid(S8, 1), pid(S3, 4)}
    with pytest.raises(ValueError, match="already annotated"):
        load_annotations([labels_file, labels_file])
    assert case_numbers(["C:2", "D:9", "D:3", "D:x"], "D") == [3, 9]


def test_annotate_keeps_the_label_and_records_the_review(tmp_path: Path) -> None:
    rows, _ = base_rows(tmp_path)
    notes = {k: LabelOverride.model_validate(v) for k, v in labels_d().items()
             if v.get("keep_existing")}
    notes["v49-nope"] = LabelOverride(gold_label="supported", keep_existing=True)
    out, unknown, how = annotate(rows, notes)
    before, after = {r.id: r for r in rows}, {r.id: r for r in out}
    row = after[pid(S3, 4)]
    assert (row.gold_label, row.split, row.gold_source) == (
        before[pid(S3, 4)].gold_label, before[pid(S3, 4)].split, "review_A")
    assert row.review_d_cases == [4] and row.review_d_verdict == "partially_supported"
    assert row.flags == ["review_d_disagrees", "pattern_L2"]
    assert row.notes.startswith(before[pid(S3, 4)].notes) and row.notes.endswith(" | D: synthetic")
    assert how[pid(S3, 4)] == "kept supported; review says partially_supported"
    assert unknown == sorted(["v49-nope", pid(S5, 4)])  # S5/4: a review_C row, not built here
    assert after[pid(S2, 3)] == before[pid(S2, 3)]


def test_review_d_rows_come_from_their_own_run(tmp_path: Path) -> None:
    db = make_db_d(tmp_path / "db.sqlite")
    session = load_session(SESSION, db, with_verifications=False)
    later = load_session(D_SESSION, db, with_verifications=False)
    labels = {k: LabelOverride.model_validate(v) for k, v in labels_d().items()
              if not v.get("keep_existing")}
    rows, missing = extra_rows(labels, set(), session, {"review_D": later})
    by_id = {r.id: r for r in rows}
    assert not missing and set(by_id) == {pid(S7, 7), pid(S8, 1)}
    new = by_id[pid(S7, 7)]
    assert (new.session_id, new.claim_number, new.doi, new.gold_source) == (
        D_SESSION, 201, "10.1/q", "review_D")
    assert new.review_d_cases == [1, 2] and new.review_d_verdict == "partially_supported"
    assert new.review_c_case is None and new.paragraph == f"Para. {S7}" and new.abstract
    _, missing_here = extra_rows(labels, set(), session)  # neither is in the first run
    assert missing_here == sorted([pid(S7, 7), pid(S8, 1)])


def test_join_in_stages_never_moves_an_earlier_source(tmp_path: Path) -> None:
    rows, session = base_rows(tmp_path)
    later = load_session(D_SESSION, make_db_d(tmp_path / "d.sqlite"), with_verifications=False)
    labels = {k: LabelOverride.model_validate(v) for k, v in {**labels_c(), **labels_d()}.items()
              if not v.get("keep_existing")}
    extra, _ = extra_rows(labels, {r.id for r in rows}, session, {"review_D": later})
    c_only, _ = join_splits(rows, [r for r in extra if r.gold_source == "review_C"], seed=7)
    staged, how = join_in_stages(rows, extra, seed=7)
    split = {r.id: r.split for r in staged}
    assert all(split[r.id] == r.split for r in c_only) and len(staged) == len(extra)
    ref1 = next(r.split for r in rows if r.ref == 1)
    assert split[pid(S8, 1)] == ref1 and how[pid(S8, 1)] == f"joined {ref1}"
    assert how[pid(S7, 7)] == f"assigned {split[pid(S7, 7)]}"


def test_build_cli_adds_review_d_without_touching_existing_rows(tmp_path: Path) -> None:
    db = make_db_d(tmp_path / "db.sqlite")
    a, notes, b = write_reviews(tmp_path)
    c_file, d_file = write(tmp_path / "c.json", labels_c()), write(tmp_path / "d.json", labels_d())
    common = ["--review-a", str(a), "--notes-a", str(notes), "--review-b", str(b), "--db",
              str(db), "--session", SESSION, "--name", "g", "--seed", "7", "--labels", str(c_file)]
    one = build_refcheck_gold.build(build_refcheck_gold.parse_args(
        [*common, "--out-dir", str(tmp_path / "one")]))
    two = build_refcheck_gold.build(build_refcheck_gold.parse_args(
        [*common, "--labels", str(d_file), "--source-session", f"review_D={D_SESSION}",
         "--out-dir", str(tmp_path / "two")]))
    keys = ("split", "gold_label", "gold_source", "gold_partial_type", "session_id", "exclude")
    after = {r.id: r for r in two}
    assert len(two) == len(one) + 2
    assert all(getattr(after[r.id], k) == getattr(r, k) for r in one for k in keys)
    assert after[pid(S5, 4)].review_d_verdict == "supported" and after[pid(S5, 4)].review_c_case
    manifest = json.loads((tmp_path / "two" / "g.manifest.json").read_text(encoding="utf-8"))
    assert manifest["by_source"]["review_D"] == 2 and manifest["inputs"][
        "session:review_D"] == D_SESSION
    assert manifest["case_ids"]["D:1"] == manifest["case_ids"]["D:2"] == pid(S7, 7)
    assert manifest["case_ids"]["D:4"] == pid(S3, 4)
    assert set(manifest["annotated_from_labels"]) == {pid(S3, 4), pid(S5, 4)}
    with pytest.raises(SystemExit, match="SOURCE=SESSION"):
        build_refcheck_gold.build(build_refcheck_gold.parse_args(
            [*common, "--source-session", "review_D", "--out-dir", str(tmp_path / "bad")]))


def test_score_recorded_adds_a_review_d_block(tmp_path: Path) -> None:
    db = make_db(tmp_path / "db.sqlite")
    rows = [row(S1, 1, "supported", 1, split="dev", review_d_cases=[3]),
            row(S2, 3, "partially_supported", 3, split="test", review_d_cases=[4, 5]),
            row(S3, 4, "supported", 4, split="test")]
    data = tmp_path / "gold.jsonl"
    data.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    score_recorded.run(score_recorded.parse_args([
        "--dataset", str(data), "--session", SESSION, "--db", str(db),
        "--results-dir", str(tmp_path / "res"), "--run-name", "d"]))
    blocks = json.loads((tmp_path / "res" / "d" / "by_split.json").read_text(encoding="utf-8"))
    assert blocks["subsets"]["review_D"]["n"] == 2 and blocks["blocks"]["test"]["n"] == 2
