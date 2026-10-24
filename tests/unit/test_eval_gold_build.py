"""Unit tests for the manuscript gold builder (synthetic reviews + a synthetic read-only DB)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import build_refcheck_gold  # noqa: E402
from gold_db import load_session  # noqa: E402
from gold_merge import build_rows  # noqa: E402
from gold_models import LabelOverride, normalize_sentence, pair_id  # noqa: E402
from gold_reviews import CaseRow, _a_verdict, load_review_a, load_review_b  # noqa: E402
from gold_split import apply_labels, assign_splits  # noqa: E402

SESSION = "sess_test"
S1 = "Drug X reduces inflammation in mice (Smith, 2020; Lee, 2021)."
S2 = "Y is common in transplant recipients (Lee, 2021b)."
S3 = "Z improves graft survival (Kim, 2019)."
S4 = "W is safe in rats (Kim, 2019)."
REASONING = [{"model_name": "screen-model", "model_display": "Decisions API · screen",
              "verdict": "possible_problem", "reasoning": "P(support)=0.2"},
             {"model_name": "verifier-model", "model_display": "Verifier · verifier-model",
              "verdict": "partially_supported",
              "reasoning": "Mice only. [severity minor, problem overgeneralized]"}]
# (claim_number, sentence, refs, cited_for, co_cited)
CLAIMS = [(1, S1, [1], "Drug X reduces inflammation in mice", 2), (2, S1, [2], "", 2),
          (3, S2, [3], "", 1), (4, S3, [4], "", 1), (5, S4, [4], "", 1)]
# (ref, title, doi, pdf_path, duplicate_of)
REFS = [(1, "Drug X in mice", "10.1/a", None, None), (2, "Review of Y", "10.1/b", "C:/x/b.pdf",
                                                      None),
        (3, "Review of Y", "10.1/b", None, 2), (4, "Z trial", None, None, None)]
# (claim, ref, verdict, consensus, layer_path)
VERDICTS = [(1, 1, "partially_supported", "verifier"), (2, 2, "partially_supported",
                                                         "disputed"),
            (3, 3, "partially_supported", "confirmed"), (4, 4, "supported", "verifier")]


def make_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE claims (session_id, claim_number, manuscript_text, extracted_claim,
            reference_ids_json, paragraph_text, section_heading, claim_type, claim_quality,
            co_cited_count, cited_for);
        CREATE TABLE "references" (session_id, ref_number, title, authors_json, year, doi,
            pdf_path, abstract_text, abstract_source, identity_status, duplicate_of);
        CREATE TABLE verifications (session_id, claim_id, reference_id, verdict, confidence,
            reasoning, source_coverage, needs_user_review, cannot_verify_reason, decided_by,
            consensus_type, layer_path_json, model_reasoning_json, screen_p_support,
            cost_usd, latency_ms);""")
    for num, sent, refs, cited_for, co in CLAIMS:
        con.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (SESSION, num, sent, sent.split(" (")[0], json.dumps(refs),
                     f"Intro text. {sent} More.", "1. Intro", "factual", "ok", co, cited_for))
    for ref, title, doi, pdf, dup in REFS:
        con.execute('INSERT INTO "references" VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (SESSION, ref, title, '["Smith, A."]', 2020, doi, pdf,
                     f"Abstract of {title}.", "pubmed", "verified", dup))
    for claim, ref, verdict, consensus in VERDICTS:
        con.execute("INSERT INTO verifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (SESSION, claim, ref, verdict, 0.6, "r", "full_text", 0, None, "verifier",
                     consensus, '["screen", "verifier"]', json.dumps(REASONING), 0.2, 0.001,
                     1000))
    con.commit()
    con.close()
    return path


def write_reviews(root: Path) -> tuple[Path, Path, Path]:
    a, b = root / "review", root / "review_partial"
    a.mkdir()
    b.mkdir()
    a_cases = [{"case": 1, "claim_id": 9, "ref": 1, "sentence": "  drug x REDUCES inflammation"
                " in mice (Smith, 2020; Lee, 2021). "},
               {"case": 2, "claim_id": 10, "ref": 3, "sentence": S2},
               {"case": 3, "claim_id": 11, "ref": 4, "sentence": S3 + " Extra words (Kim)."},
               {"case": 4, "claim_id": 12, "ref": 4, "sentence": S4}]
    manual = [{"case": 1, "manual": "partially_supported"}, {"case": 2, "manual":
                                                              "not_supported"},
              {"case": 3, "manual": "supported"}, {"case": 4, "manual": "wrong_paper"}]
    (a / "cases.json").write_text(json.dumps(a_cases), encoding="utf-8")
    (a / "manual_gold.json").write_text(json.dumps(manual), encoding="utf-8")
    notes = root / "notes.json"
    notes.write_text(json.dumps({"1": ["partially_supported", "Mice only.", "Say mice."]}),
                     encoding="utf-8")
    b_cases = [{"case": 10, "claim_id": 1, "ref": 1, "sentence": S1},
               {"case": 11, "claim_id": 3, "ref": 3, "sentence": S2},
               {"case": 12, "claim_id": 2, "ref": 2, "sentence": S1}]
    rev = {"10": {"confidence": "medium"}, "11": {"confidence": "high"},
           "12": {"confidence": "medium", "full_text_used": False}}
    final = {"10": {"outcome": "CORRECT", "verdict": "partially_supported", "status": "agreed"},
             "11": {"outcome": "CORRECT", "verdict": "partially_supported", "status": "agreed"},
             "12": {"outcome": "TOO_HARSH", "verdict": "supported", "status": "confirmed"}}
    (b / "cases.json").write_text(json.dumps(b_cases), encoding="utf-8")
    (b / "review_results.json").write_text(json.dumps({"rev": rev, "sec": {}, "final": final}),
                                           encoding="utf-8")
    (b / "harsh_categories.json").write_text(
        json.dumps({"12": "Over-literal about wording or hedging"}), encoding="utf-8")
    return a, notes, b


def test_pair_id_ignores_case_space_and_dash_variants() -> None:
    assert pair_id("A  b\u2013c.", 3) == pair_id(" a b-c. ", 3) != pair_id("a b-c.", 4)
    assert normalize_sentence("X\u00a0 Y") == "x y"


def test_review_a_remap_marks_wrong_paper_pairs_invalid() -> None:
    moved = _a_verdict(CaseRow(case=32, claim_id=1, ref=105, sentence="s"), "supported", [])
    same_paper = _a_verdict(CaseRow(case=34, claim_id=1, ref=105, sentence="s"),
                            "partially_supported", [])
    assert moved.ref == 107 and not moved.valid and moved.label == ""
    assert same_paper.ref == 106 and same_paper.valid
    tool_ok = _a_verdict(CaseRow(case=1, claim_id=1, ref=2, sentence="s"),
                         "partially_supported_tool_ok", [])
    assert tool_ok.label == "partially_supported" and tool_ok.confidence == "low"


def test_build_rows_merges_reviews(tmp_path: Path) -> None:
    session = load_session(SESSION, make_db(tmp_path / "db.sqlite"), with_verifications=False)
    a, notes, b = write_reviews(tmp_path)
    rows, missing = build_rows(load_review_a(a, notes) + load_review_b(b), session)
    by_id = {r.id: r for r in rows}
    assert not missing and len(rows) == 5
    agree = by_id[pair_id(S1, 1)]
    assert agree.gold_source == "both" and agree.gold_confidence == "high"
    assert agree.cited_for == "Drug X reduces inflammation in mice" and agree.co_cited_count == 2
    assert [(c.ref, c.title) for c in agree.co_cited_refs] == [(2, "Review of Y")]
    assert "Mice only." in agree.notes and agree.review_a_case == 1
    disagree = by_id[pair_id(S2, 3)]
    assert disagree.needs_adjudication and disagree.gold_label == "partially_supported"
    assert disagree.pdf_path == "C:/x/b.pdf"  # duplicate entry inherits the original's PDF
    harsh = by_id[pair_id(S1, 2)]
    assert harsh.gold_binary == "ok" and harsh.gold_basis == "abstract"
    assert harsh.tool_misread_type == "over_literal_about_wording_or_hedging"
    contained = by_id[pair_id(S3, 4)]
    assert contained.gold_source == "review_A" and contained.claim_number == 4
    wrong = by_id[pair_id(S4, 4)]
    assert wrong.exclude and wrong.gold_label == "cannot_judge"


def test_splits_keep_papers_together_and_labels_override(tmp_path: Path) -> None:
    session = load_session(SESSION, make_db(tmp_path / "db.sqlite"), with_verifications=False)
    a, notes, b = write_reviews(tmp_path)
    rows, _ = build_rows(load_review_a(a, notes) + load_review_b(b), session)
    first, again = assign_splits(rows, seed=7), assign_splits(rows, seed=7)
    assert [r.split for r in first] == [r.split for r in again]
    same_doi = {r.split for r in first if r.doi == "10.1/b"}
    assert len(same_doi) == 1
    labels = {pair_id(S2, 3): LabelOverride(gold_label="not_supported"),
              pair_id(S1, 1): LabelOverride(gold_partial_type="co_cited_share"),
              pair_id(S3, 4): LabelOverride(gold_label="cannot_judge"), "v49-nope": LabelOverride()}
    out, unknown = apply_labels(first, labels)
    by_id = {r.id: r for r in out}
    assert unknown == ["v49-nope"]
    fixed = by_id[pair_id(S2, 3)]
    assert fixed.gold_source == "adjudicated" and not fixed.needs_adjudication
    before = {r.id: r.split for r in first}
    assert fixed.gold_binary == "problem" and all(r.split == before[r.id] for r in out)
    assert by_id[pair_id(S1, 1)].gold_partial_type == "co_cited_share"
    assert by_id[pair_id(S1, 1)].gold_source == "both"
    assert by_id[pair_id(S3, 4)].exclude


def test_build_cli_writes_splits_and_manifest(tmp_path: Path) -> None:
    db = make_db(tmp_path / "db.sqlite")
    a, notes, b = write_reviews(tmp_path)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({pair_id(S2, 3): {"gold_label": "not_supported"}}),
                      encoding="utf-8")
    out = tmp_path / "out"
    rows = build_refcheck_gold.build(build_refcheck_gold.parse_args([
        "--review-a", str(a), "--notes-a", str(notes), "--review-b", str(b), "--db", str(db),
        "--session", SESSION, "--labels", str(labels), "--out-dir", str(out), "--name", "g"]))
    lines = (out / "g.jsonl").read_text(encoding="utf-8").splitlines()
    dev = (out / "g.dev.jsonl").read_text(encoding="utf-8").splitlines()
    test = (out / "g.test.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(rows) == 5 and len(dev) + len(test) == 5
    manifest = json.loads((out / "g.manifest.json").read_text(encoding="utf-8"))
    assert manifest["n_excluded"] == 1 and manifest["needs_adjudication"] == []
    assert manifest["labels_sha"] and manifest["by_source"]["adjudicated"] == 1
    assert manifest["labels_files"] == [str(labels)] and manifest["added_from_labels"] == {}
    assert manifest["case_ids"]["B:12"] == pair_id(S1, 2)
