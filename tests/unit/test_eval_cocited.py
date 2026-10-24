"""Eval plumbing of the co-cited union check: sources, CLI, report, dry run (no network)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_cocited  # noqa: E402
import eval_dry_run  # noqa: E402
import run_eval  # noqa: E402
from eval_cli import parse_args  # noqa: E402
from eval_gold import gold_item  # noqa: E402
from eval_models import EvalConfig, ItemRecord  # noqa: E402
from eval_partial import compute_partial, partial_line  # noqa: E402
from eval_report import union_line  # noqa: E402
from eval_roles import apply_overrides  # noqa: E402
from gold_db import DbClaim, DbReference, SessionData  # noqa: E402

from refcheck.stages.verify_claims.cocited_union import cocited_union_enabled  # noqa: E402
from refcheck.stages.verify_claims.source_document import build_abstract_document  # noqa: E402
from refcheck.stages.verify_claims.verifier_helpers import ResolvedSource  # noqa: E402
from tests.unit.test_eval_gold_run import gold_row, make_pdf, write_rows  # noqa: E402

ABSTRACT_8 = ("Drug X was safe in a phase one trial of healthy adult volunteers. No serious "
              "adverse events were recorded during four weeks of daily oral dosing.")
# Co-cited reference 8 stating the claim's first words (the element the union check gets).
LEND_ABSTRACT = "Drug X reduces inflammation in mice given one oral dose. " + ABSTRACT_8
ABSTRACT_9 = ("Drug X lowered fever in children with a common viral infection. Body "
              "temperature fell within two days and no child needed hospital care.")


def _session(session: str) -> SessionData:
    return SessionData(session_id=session, claims=[DbClaim(number=1, sentence="s", claim="c",
                                                           refs=[9])],
                       references={9: DbReference(number=9, title="Fever",
                                                  abstract=ABSTRACT_9)})


async def test_co_cited_sources_come_from_other_gold_rows_then_the_db(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row = gold_row(session_id="sess_a", co_cited_refs=[
        {"ref": 8, "title": "Safety"}, {"ref": 9, "title": "Fever"},
        {"ref": 6, "title": "In this run"}, {"ref": 5, "title": "Nowhere"}])
    other = gold_row(id="v49-other", ref=8, session_id="sess_a", split="test",
                     abstract=ABSTRACT_8, exclude=True)  # excluded rows still lend sources
    pool = write_rows(tmp_path / "all.jsonl", row, other)
    asked: list[str] = []

    def fake_load(session: str, db_path: Path, with_verifications: bool) -> SessionData:
        asked.append(session)
        return _session(session)

    monkeypatch.setattr(eval_cocited, "load_session", fake_load)
    own = build_abstract_document(6, ABSTRACT_8)
    resolved = {"ref6": ResolvedSource(doc=own, coverage="abstract_only")}
    docs = await eval_cocited.resolve_cocited_sources(
        [gold_item(row)], resolved, "abstract", pool)
    assert sorted(docs) == [6, 8, 9] and docs[6] is own  # 5: in no row and not in the DB
    assert ABSTRACT_8 in docs[8].full_text and ABSTRACT_9 in docs[9].full_text
    assert asked == ["sess_a"]  # the row's own session
    await eval_cocited.resolve_cocited_sources([gold_item(row)], resolved, "abstract", pool,
                                               session="sess_cli")
    assert asked[-1] == "sess_cli"  # --session overrides it


def test_gold_pool_prefers_a_row_with_a_pdf(tmp_path: Path) -> None:
    rows = [gold_row(id="a", ref=8, abstract="x y z"),
            gold_row(id="b", ref=8, pdf_path=str(tmp_path / "p.pdf"))]
    pool = eval_cocited.gold_pool(write_rows(tmp_path / "g.jsonl", *rows))
    assert pool[("", 8)].id == "b"


def test_cli_flags_reach_the_app_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = parse_args(["--cocited-union", "off", "--session", "sess_x"])
    assert (cfg.cocited_union, cfg.session) == ("off", "sess_x")
    monkeypatch.setenv("REFCHECK_COCITED_UNION", "on")
    apply_overrides(cfg)
    assert not cocited_union_enabled()
    assert parse_args([]).cocited_union is None and EvalConfig().session == ""


def test_report_lines() -> None:
    line = union_line({"cleared": 3, "partial": 1, "held": 2, "unchanged": 4, "skipped": 5})
    assert line.startswith("union check: ran 10, cleared fully 3, partially 1, held 2")
    assert "skipped by precondition 5" in line

    def rec(gold: str, verdict: str, ptype: str = "") -> ItemRecord:
        return ItemRecord(id=f"{gold}{verdict}{ptype}", dataset="d", gold_label=gold,
                          gold_binary="ok", mode="cascade", verdict=verdict,
                          partial_type=ptype)
    metrics = compute_partial([rec("supported", "partially_supported", "coverage_limited"),
                               rec("supported", "partially_supported", "missing_element"),
                               rec("supported", "supported"),
                               rec("partially_supported", "partially_supported",
                                   "coverage_limited")])
    assert metrics is not None
    assert (metrics.over_harsh, metrics.over_harsh_excl_coverage) == ("2/3", "1/2")
    assert (metrics.coverage_limited, metrics.coverage_limited_gold_supported) == (2, 1)
    assert "without coverage_limited 1/2=50.0%" in partial_line(metrics)


def test_dry_run_union_answer_quotes_the_first_co_cited_passage() -> None:
    variables = {"elements": ["e one", "e two"], "sources": [
        {"number": 12, "passages": ["[R12-P1] (Results, p.4) " + ABSTRACT_8]}]}
    out = eval_dry_run.canned_union(variables)
    assert [c.category for c in out.elements] == ["cocited", "absent"]
    assert out.elements[0].passage_id == "R12-P1"
    assert out.elements[0].quote and out.elements[0].quote in ABSTRACT_8


async def test_dry_run_on_gold_rows_runs_the_union_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = make_pdf(tmp_path / "paper.pdf")
    rows = [gold_row(id="v49-main", pdf_path=str(pdf), cited_for="", gold_label="supported",
                     gold_binary="ok", tool_misread_type="cocited_share"),
            gold_row(id="v49-lend", ref=8, abstract=LEND_ABSTRACT, exclude=True)]
    data = write_rows(tmp_path / "gold.jsonl", *rows)
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("REFCHECK_COCITED_UNION", "on")
    # the V5.7 slot audit (#2) also audits a supported verdict the union cleared (one more
    # adjudicator call); this test is about the union check alone
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "2")
    cfg = eval_dry_run.parse_cli(["--dataset", str(data), "--dry-run", "--run-name", "u",
                                  "--results-dir", str(tmp_path), "--adjudicate", "on"], None)
    result = await run_eval.run(cfg)
    assert result.meta.cocited_union and result.headline.cocited_union == {"cleared": 1}
    record = ItemRecord.model_validate_json(
        (tmp_path / "u" / "items.jsonl").read_text(encoding="utf-8"))
    assert record.layer_path[-2:] == ["adjudicate", "adjudicate_cocited"]
    assert record.verdict == "supported" and "cocited_share" in record.guards_applied
    assert record.layers[-1].layer == "adjudicate_cocited"
