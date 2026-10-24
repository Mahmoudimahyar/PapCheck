"""Unit tests for eval rows -> production objects (no network: BM25-only retrieval)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_data  # noqa: E402
from eval_cli import parse_pairs  # noqa: E402
from eval_models import EvalItem  # noqa: E402

ABSTRACT = ("Background: inflammation drives tissue damage in many organs. Methods: we "
            "randomised 120 mice to drug X or vehicle for four weeks. Results: drug X reduced "
            "inflammation markers in treated mice compared with vehicle. Conclusion: drug X "
            "is anti-inflammatory in mice.")
BODY = ("## Abstract\n\n" + ABSTRACT + "\n\n## Introduction\n\n"
        + "Inflammation is a common pathway in many diseases and has been studied widely. " * 10
        + "\n\n## Results\n\nDrug X reduced IL-6 levels compared with vehicle in all mice. "
        + "Body weight did not differ between the groups during the study period. " * 8
        + "\n\n## Discussion\n\nThese results suggest drug X has anti-inflammatory effects. "
        + "Further work is needed to confirm these findings in other models. " * 6)


def ci_item(**extra: object) -> EvalItem:
    base: dict[str, object] = {
        "id": "ci-1", "claim": "Drug X reduces inflammation in mice [7] and #.",
        "claim_raw": "Drug X reduces inflammation in mice [<|cit|>] and #.",
        "context": "Inflammation matters. Drug X reduces inflammation in mice [7] and #. More.",
        "source_id": "PMC1", "source_title": "Drug X in mice", "source_text": BODY,
        "source_type": "full_text", "source_abstract": ABSTRACT,
        "source_retrieved": "Drug X reduced IL-6 levels compared with vehicle in all mice.",
        "gold_label": "supported", "gold_binary": "ok", "dataset": "citation_integrity",
    }
    base.update(extra)
    return EvalItem.model_validate(base)


def sf_item(**extra: object) -> EvalItem:
    base: dict[str, object] = {
        "id": "sf-1", "claim": "Drug X is anti-inflammatory in mice.", "source_id": "S2:1",
        "source_text": ABSTRACT, "source_type": "abstract", "gold_label": "not_supported",
        "gold_binary": "problem", "dataset": "scifact", "context": ""}
    base.update(extra)
    return EvalItem.model_validate(base)


def test_resolve_dataset_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("smoke.jsonl", "scifact.dev.bal.jsonl", "ci_test.jsonl", "scifact.jsonl"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(eval_data, "EVAL_DIR", tmp_path)
    assert eval_data.resolve_dataset("smoke", "dev") == tmp_path / "smoke.jsonl"
    assert eval_data.resolve_dataset("scifact", "dev.bal") == tmp_path / "scifact.dev.bal.jsonl"
    assert eval_data.resolve_dataset("ci", "test") == tmp_path / "ci_test.jsonl"
    assert eval_data.resolve_dataset("scifact", "all") == tmp_path / "scifact.jsonl"
    explicit = tmp_path / "ci_test.jsonl"
    assert eval_data.resolve_dataset(str(explicit), "ignored") == explicit
    with pytest.raises(FileNotFoundError):
        eval_data.resolve_dataset("scifact", "test")


def test_load_items_limit_and_synthetic_filter(tmp_path: Path) -> None:
    rows = [sf_item(id="a", synthetic=True), sf_item(id="b"), sf_item(id="c")]
    path = tmp_path / "x.jsonl"
    path.write_text("\n".join(r.model_dump_json() for r in rows) + "\n\n", encoding="utf-8")
    assert [i.id for i in eval_data.load_items(path)] == ["a", "b", "c"]
    assert [i.id for i in eval_data.load_items(path, limit=1, skip_synthetic=True)] == ["b"]


def test_co_cited_count_from_placeholders() -> None:
    assert eval_data.co_cited_count(ci_item()) == 2
    assert eval_data.co_cited_count(ci_item(claim="A finding [3].", claim_raw="x")) == 1
    multi = ci_item(claim="A finding [3].", claim_raw="A finding [<|multi_cit|>].")
    assert eval_data.co_cited_count(multi) == 2


def test_abstract_rows_become_abstract_only_documents() -> None:
    doc = eval_data.build_document(sf_item(), 1, "auto")
    assert doc.coverage == "abstract_only"
    assert doc.chunks and doc.chunks[0].kind == "abstract"


def test_full_text_rows_use_the_production_source_builder() -> None:
    doc = eval_data.build_document(ci_item(), 3, "auto")
    assert doc.coverage == "full_text" and doc.ref_id == 3
    assert doc.has_abstract_chunk and doc.abstract_source == "reference"
    assert len(doc.chunks) > 3
    retrieved = eval_data.build_document(ci_item(), 3, "retrieved")
    assert "IL-6" in retrieved.full_text and "Introduction" not in retrieved.full_text
    assert eval_data.build_document(ci_item(), 3, "abstract").coverage == "abstract_only"


def test_build_documents_one_per_source() -> None:
    docs, ref_ids = eval_data.build_documents([ci_item(), ci_item(id="ci-2"), sf_item()], "auto")
    assert set(docs) == {"PMC1", "S2:1"}
    assert ref_ids == {"PMC1": 1, "S2:1": 2}


async def test_build_context_runs_production_retrieval_offline() -> None:
    item = ci_item()
    doc = eval_data.build_document(item, 1, "auto")
    ctx = await eval_data.build_context(item, 5, 1, doc, use_embeddings=False, tracker=None)
    assert ctx.claim.id == 5 and ctx.ref.id == 1 and ctx.claim.co_cited_count == 2
    assert ctx.pack.passages[0].id == "A"
    assert ctx.pack.retrieval_version.endswith(":bm25")
    assert "[7]" not in ctx.claim_text and "#" not in ctx.claim_text
    assert ctx.prev_sentence == "Inflammation matters."


def test_template_hashes_are_stable() -> None:
    assert eval_data.screen_template_hash() == eval_data.screen_template_hash()
    assert len(eval_data.screen_template_hash()) == 16
    assert set(eval_data.prompt_hashes()) == {"screen_claim", "verify_claim", "judge_claim"}


def test_prompt_hashes_cover_the_taxonomy(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """The verifier/judge rubric is rendered from the taxonomy: a change must show in runs."""
    for name in ("screen_claim.md", "verify_claim.md", "judge_claim.md", "verify_taxonomy.md",
                 "partial_taxonomy.json"):
        (tmp_path / name).write_bytes((eval_data.PROMPTS_DIR / name).read_bytes())
    monkeypatch.setattr(eval_data, "PROMPTS_DIR", tmp_path)
    before = eval_data.prompt_hashes()
    with (tmp_path / "partial_taxonomy.json").open("a", encoding="utf-8") as fh:
        fh.write("\n")
    after = eval_data.prompt_hashes()
    assert after["screen_claim"] == before["screen_claim"]
    assert after["verify_claim"] != before["verify_claim"]
    assert after["judge_claim"] != before["judge_claim"]


def test_parse_pairs_roles() -> None:
    assert parse_pairs(["verifier=claude-haiku-5-5", "judge=x"], "cascade", "--model") == {
        "verifier": "claude-haiku-5-5", "judge": "x"}
    assert parse_pairs(["gpt-6-luna"], "verifier", "--model") == {"verifier": "gpt-6-luna"}
    with pytest.raises(SystemExit):
        parse_pairs(["gpt-6-luna"], "cascade", "--model")
    with pytest.raises(SystemExit):
        parse_pairs(["bogus=x"], "verifier", "--model")
