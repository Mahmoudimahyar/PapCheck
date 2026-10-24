"""Eval cited_for parity hooks (scripts/eval/eval_parity.py): only a row a V5.7 rule
narrows gets a new cited_for, and only those rows are screened again. Synthetic text."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_models import EvalItem, ScreenRecord  # noqa: E402
from eval_parity import ci_cited_for, fresh_screens, gold_row_cited_for  # noqa: E402

from tests.unit.test_eval_gold_run import gold_row  # noqa: E402

LIST_RAW = ("Such links were found in many conditions, including colitis [<|other_cit|>], "
            "hepatitis [<|other_cit|>], and arthritis [<|cit|>].")
LIST_SENTENCE = ("As light frames (Hale et al., 2017) with folding poles (Smith et al., "
                 "2020) and low cost (Bain et al., 2024), modern tents protect hikers.")
LIST_SCOPE = ("As light frames with folding poles and low cost, modern tents protect "
              "hikers")


def ci_item(item_id: str, raw: str) -> EvalItem:
    return EvalItem(id=item_id, claim=raw, context="", claim_raw=raw, source_id="s",
                    source_title="t", source_text="x", gold_label="supported",
                    gold_binary="ok", dataset="citation_integrity")


def test_ci_row_gets_only_a_narrowed_cited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    narrowed = ci_item("a", LIST_RAW)
    assert ci_cited_for(narrowed) == "Such links were found in many conditions, including arthritis"
    assert ci_cited_for(ci_item("b", "Gels reduce IL-6 in mice [<|cit|>].")) == ""
    assert ci_cited_for(ci_item("c", "")) == ""
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "10")
    assert ci_cited_for(narrowed) == ""


def test_gold_row_keeps_its_stored_value_unless_narrowed() -> None:
    row = gold_row(sentence=LIST_SENTENCE, claim=LIST_SCOPE, cited_for=LIST_SCOPE)
    assert gold_row_cited_for(row) == "with folding poles, modern tents protect hikers"
    assert gold_row_cited_for(gold_row()) == gold_row().cited_for


def test_fresh_screens_drops_only_changed_items() -> None:
    items = [ci_item("a", LIST_RAW), ci_item("b", "Gels reduce IL-6 in mice [<|cit|>].")]
    screens = {"a": ScreenRecord(s=0.9), "b": ScreenRecord(s=0.8)}
    assert set(fresh_screens(items, screens)) == {"b"}
