"""Unit tests for the tool-"supported" review sampler (synthetic pairs, DB and PDFs only)."""

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import sample_supported  # noqa: E402
from gold_models import pair_id  # noqa: E402
from sample_supported_draw import (  # noqa: E402
    MAX_ABSTRACT_ONLY,
    MAX_PER_REF,
    Candidate,
    CaseLoad,
    allocate,
    draw_sample,
    make_batches,
)
from sample_supported_text import paper_text, title_found  # noqa: E402

SESSION = "sess_test"
SECTIONS = ("1. Intro", "2. Methods", "3. Results")


def make_pool(n: int = 60, abstract_only: int = 3) -> list[Candidate]:
    return [Candidate(pair_id=f"p{i}", claim_number=i, ref=i % 25, sentence_key=f"s{i // 2}",
                      section=SECTIONS[i % 3] if i % 7 else SECTIONS[0], multi=i % 3 == 0,
                      abstract_only=i < abstract_only) for i in range(n)]


def test_allocate_respects_floors_caps_and_total() -> None:
    quota = allocate({"a": 90.0, "b": 8.0, "c": 2.0}, 20, {"c": 2}, {"a": 90, "b": 8, "c": 2})
    assert sum(quota.values()) == 20
    assert quota["c"] == 2 and quota["a"] > quota["b"]


def test_draw_sample_is_deterministic_and_stratified() -> None:
    pool = make_pool()
    sample, plan = draw_sample(pool, 20, seed=7)
    again, _ = draw_sample(pool, 20, seed=7)
    assert [c.pair_id for c in sample] == [c.pair_id for c in again]
    assert len(sample) == 20 and len({c.pair_id for c in sample}) == 20
    assert max(Counter(c.ref for c in sample).values()) <= MAX_PER_REF
    assert {c.pair_id for c in pool if c.abstract_only} <= {c.pair_id for c in sample}
    assert set(plan.forced) == {"p0", "p1", "p2"}
    assert 8 <= sum(c.multi for c in sample) <= 12
    assert {c.section for c in sample} == set(SECTIONS)


def test_draw_sample_caps_forced_abstract_only() -> None:
    sample, plan = draw_sample(make_pool(abstract_only=12), 20, seed=3)
    assert len(plan.forced) == MAX_ABSTRACT_ONLY
    assert len(sample) == 20


def test_make_batches_keeps_reference_together_and_sizes_equal() -> None:
    cases = [CaseLoad(case=i, ref=i // 2, chars=100) for i in range(1, 11)]
    batches = make_batches(cases, {r: 1000 * r for r in range(6)}, 2)
    assert sorted(len(b) for b in batches) == [5, 5]
    batch_of = {case: i for i, b in enumerate(batches) for case in b}
    pairs = [(c.case, d.case) for c in cases for d in cases if c.ref == d.ref and c.case < d.case]
    split = [p for p in pairs if batch_of[p[0]] != batch_of[p[1]]]
    assert len(split) <= 1  # at most the last group is split to keep sizes equal


def _pdf(path: Path, lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=9)
    doc.save(path)
    doc.close()
    return path


def test_paper_text_reuses_matching_text_and_notes_problems(tmp_path: Path) -> None:
    title = "Synthetic hydrogel improves widget survival"
    body = [title, "Methods and results of a synthetic study."] * 30
    pdf = _pdf(tmp_path / "paper.pdf", body)
    old, out = tmp_path / "old", tmp_path / "out"
    old.mkdir()
    out.mkdir()
    (old / "ref3.txt").write_text(f"{title}\nreused text", encoding="utf-8")
    reused = paper_text(3, str(pdf), title, out, [old])
    assert reused.origin == "reused old" and (out / "ref3.txt").read_text(
        encoding="utf-8").endswith("reused text")
    fresh = paper_text(4, str(pdf), title, out, [old])
    assert fresh.origin == "extracted" and fresh.chars > 0
    assert paper_text(5, None, title, out, []).notes == ["no PDF linked: abstract only"]
    supp = paper_text(6, str(_pdf(tmp_path / "x_si_001.pdf", body)), title, out, [])
    assert any("supplementary" in n for n in supp.notes)
    assert title_found(title, "SYNTHETIC HYDRO-\nGEL improves widget survival") is True
    assert title_found(title, "An unrelated paper about rockets") is False


def make_db(path: Path, gold_sentence: str) -> Path:
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
            cost_usd, latency_ms, evidence_quotes_json);""")
    for num in range(1, 13):
        sentence = gold_sentence if num == 1 else f"Synthetic finding {num} holds (A, 2020)."
        con.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (SESSION, num, sentence, sentence, json.dumps([num]), "P " * 900,
                     SECTIONS[num % 3], "factual", "ok", 1, ""))
        con.execute('INSERT INTO "references" VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (SESSION, num, f"Paper {num}", '["A, B."]', 2020, None, None,
                     f"Abstract {num}.", "pubmed", "verified", None))
        verdict = "partially_supported" if num == 12 else "supported"
        con.execute("INSERT INTO verifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (SESSION, num, num, verdict, 0.9, "fine", "abstract_only" if num == 2
                     else "full_text", 0, None, "verifier", "verifier",
                     '["screen", "verifier"]', "[]", 0.9, 0.0, 10, json.dumps([f"q{num}"])))
    con.commit()
    con.close()
    return path


def test_run_writes_cases_and_batches(tmp_path: Path) -> None:
    gold_sentence = "Synthetic finding 1 holds (A, 2020)."
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps({"id": pair_id(gold_sentence, 1), "sentence": gold_sentence,
                                "ref": 1}) + "\n", encoding="utf-8")
    out = tmp_path / "review_supported"
    args = sample_supported.parse_args([
        "--db", str(make_db(tmp_path / "t.db", gold_sentence)), "--session", SESSION,
        "--gold", str(gold), "--out-dir", str(out), "--reuse-dirs", "--n", "6",
        "--batches", "2"])
    info = sample_supported.run(args)
    cases = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    assert [c["case"] for c in cases] == list(range(1, 7))
    assert info.excluded_in_gold == 1 and info.plan.pool == 10
    assert all(c["ref"] not in (1, 12) for c in cases)
    assert any(c["ref"] == 2 and "abstract_only" in c["stratum"] for c in cases)
    assert all(len(c["paragraph"]) <= 1500 and c["tool_quotes"] for c in cases)
    batches = json.loads((out / "batches.json").read_text(encoding="utf-8"))
    assert sorted(n for b in batches for n in b["cases"]) == list(range(1, 7))
