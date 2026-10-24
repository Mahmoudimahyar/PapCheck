"""Unit tests for running manuscript gold rows through the production path (no network)."""

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_runner  # noqa: E402
import run_eval  # noqa: E402
from eval_data import build_context, item_claim, item_reference, load_items  # noqa: E402
from eval_gold import production_query, resolve_gold_sources, split_sources  # noqa: E402
from eval_models import EvalConfig  # noqa: E402
from gold_models import GoldRow  # noqa: E402

from refcheck.llm.cost_tracker import CostTracker  # noqa: E402
from refcheck.models.verification import JudgeOutput  # noqa: E402
from refcheck.stages.verify_claims import cascade  # noqa: E402
from refcheck.stages.verify_claims.calibration import ScreenThresholds  # noqa: E402
from refcheck.stages.verify_claims.layers import LayerResult  # noqa: E402
from tests.unit.verify_fakes import ABSTRACT, FULL_TEXT, layer, screen  # noqa: E402

SENTENCE = "Drug X reduces inflammation in mice and is safe in humans (Smith, 2020; Lee, 2021)."


def gold_row(**extra: object) -> GoldRow:
    base: dict[str, object] = {
        "id": "v49-test", "sentence": SENTENCE, "claim": SENTENCE.split(" (")[0],
        "cited_for": "Drug X reduces inflammation in mice", "paragraph": "Intro. " + SENTENCE,
        "section": "2. Results", "claim_type": "factual", "co_cited_count": 2,
        "co_cited_refs": [{"ref": 8, "title": "Safety of drug X"}], "ref": 7,
        "ref_title": "Drug X in mice", "ref_authors": ["Smith, J."], "ref_year": 2020,
        "abstract": ABSTRACT, "abstract_source": "pubmed", "gold_label": "partially_supported",
        "gold_binary": "problem", "gold_partial_type": "co_cited_share",
        "tool_misread_type": "", "gold_source": "both", "gold_confidence": "high"}
    base.update(extra)
    return GoldRow.model_validate(base)


def write_rows(path: Path, *rows: GoldRow) -> Path:
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    return path


def make_pdf(path: Path) -> Path:
    doc = fitz.open()
    for block in FULL_TEXT.split("\n\n"):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), block, fontsize=9)
    doc.save(path)
    doc.close()
    return path


def test_load_items_converts_gold_rows_and_skips_excluded(tmp_path: Path) -> None:
    path = write_rows(tmp_path / "g.jsonl", gold_row(),
                      gold_row(id="v49-x", gold_label="cannot_judge", exclude=True))
    items = load_items(path)
    assert [i.id for i in items] == ["v49-test"]
    item = items[0]
    assert item.gold_row is not None and item.source_id == "ref7"
    assert item.gold_partial_type == "co_cited_share" and item.gold_confidence == "high"


def test_gold_claim_carries_the_manuscript_fields(tmp_path: Path) -> None:
    item = load_items(write_rows(tmp_path / "g.jsonl", gold_row()))[0]
    claim = item_claim(item, 3, 7)
    assert claim.cited_for == "Drug X reduces inflammation in mice"
    assert claim.co_cited_count == 2 and claim.section_heading == "2. Results"
    assert claim.manuscript_text == SENTENCE and claim.reference_ids == [7]
    assert production_query(claim).startswith("Drug X reduces inflammation in mice ")
    ref = item_reference(item, 1)
    assert ref.id == 7 and ref.abstract_source == "pubmed" and ref.pdf_path is None


async def test_sources_use_the_production_loader(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "paper.pdf")
    items = load_items(write_rows(
        tmp_path / "g.jsonl", gold_row(id="a", pdf_path=str(pdf)), gold_row(id="b", ref=8),
        gold_row(id="c", ref=9, abstract=None)))
    assert [i.source_id for i in items] == ["ref7", "ref8", "ref9"]
    docs, unsourced = split_sources(await resolve_gold_sources(items, "auto"))
    assert docs["ref7"].coverage == "full_text" and docs["ref7"].chunks
    assert docs["ref8"].coverage == "abstract_only"
    assert list(unsourced) == ["ref9"] and unsourced["ref9"].cannot_verify_reason
    abstract_docs, _ = split_sources(await resolve_gold_sources(items, "abstract"))
    assert abstract_docs["ref7"].coverage == "abstract_only"
    ctx = await build_context(items[0], 1, 7, docs["ref7"], False, None)
    assert ctx.claim.cited_for and ctx.expanded is not None and ctx.pack.passages


async def test_unsourced_gold_pairs_make_no_llm_call(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no LLM path for an unsourced pair")

    monkeypatch.setattr(run_eval, "evaluate_item", forbidden)
    path = write_rows(tmp_path / "g.jsonl", gold_row(abstract=None))
    items = load_items(path)
    cfg = EvalConfig(dataset="g", mode="cascade", use_embeddings=False)
    docs, ref_ids, unsourced, cocited = await run_eval.prepare_sources(items, cfg, path)
    assert cocited == {}  # the adjudicator (and so the union check) is off in tests
    records = await run_eval.run_items(items, docs, ref_ids, cfg, ScreenThresholds(),
                                       CostTracker(), tmp_path / "items.jsonl", unsourced)
    assert records[0].verdict == "cannot_verify" and records[0].decided_by == "none"
    assert records[0].gold_partial_type == "co_cited_share"
    assert (tmp_path / "items.jsonl").read_text(encoding="utf-8").count("\n") == 1


async def test_cascade_on_a_gold_row_records_the_partial_classification(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    contexts: list[object] = []
    verdict = layer("verifier", "partially_supported", severity="minor")
    assert verdict.output is not None
    typed = JudgeOutput.model_validate({**verdict.output.model_dump(),
                                        "problem_type": "compound_part_only",
                                        "partial_type": "missing_element"})
    confirm = layer("confirm", "partially_supported")

    async def fake_layer(role: str, pack: object, claim: object, ctx: object, template: str,
                         **kw: object) -> LayerResult:
        seen.append(claim)
        contexts.append(ctx)
        if kw["layer"] == "verifier":
            return verdict.model_copy(update={"output": typed})
        return confirm

    async def fake_screen(ctx: object, tracker: object = None) -> object:
        return screen(0.2)

    monkeypatch.setattr(cascade, "run_layer", fake_layer)
    monkeypatch.setattr(eval_runner, "run_screen", fake_screen)
    item = load_items(write_rows(tmp_path / "g.jsonl", gold_row(id="v49-a")))[0]
    docs, _ = split_sources(await resolve_gold_sources([item], "auto"))
    cfg = EvalConfig(mode="cascade", use_embeddings=False)
    rec = await eval_runner.evaluate_item(item, 1, 7, docs["ref7"], cfg, ScreenThresholds(),
                                          CostTracker())
    claim = seen[0]
    assert getattr(claim, "cited_for", "") == "Drug X reduces inflammation in mice"
    assert rec.verdict == "partially_supported" and rec.coverage == "abstract_only"
    # abstract only: the product reports an element absent from the abstract as coverage
    assert (rec.severity, rec.problem_type, rec.partial_type, rec.partial_severity) == (
        "minor", "compound_part_only", "coverage_limited", "minor")
    assert rec.layers[0].partial_type == "missing_element" and rec.guards_applied == []
    assert rec.gold_partial_type == "co_cited_share"
    co_cited = getattr(contexts[0], "co_cited", [])
    assert [(c.number, c.title) for c in co_cited] == [(8, "Safety of drug X")]


def test_gold_co_cited_reads_an_abstract_when_the_gold_has_one() -> None:
    from types import SimpleNamespace

    from eval_gold import gold_co_cited

    assert [(c.number, c.abstract) for c in gold_co_cited(gold_row())] == [(8, None)]
    extended = gold_row().model_copy(update={"co_cited_refs": [
        SimpleNamespace(ref=8, title="Safety", abstract="Drug X was safe."),
        SimpleNamespace(ref=7, title="self", abstract=None)]})
    assert [(c.number, c.abstract) for c in gold_co_cited(extended)] == [(8, "Drug X was safe.")]
