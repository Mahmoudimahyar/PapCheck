"""V5.8 round-2 rules (G6) inside the element check, the union check, the cascade and the
eval's type metric (synthetic texts, every model call faked)."""

import sys
from pathlib import Path

import pytest

from refcheck.models.adjudication import ElementCheck
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision, decide
from refcheck.stages.verify_claims.cocited_union import UnionRun, union_targets
from refcheck.stages.verify_claims.cocited_union_apply import combined, union_note, with_rules
from refcheck.stages.verify_claims.cocited_union_rules import UnionDecision
from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.adjudicate_fakes import STATED_QUOTE, WORDING_QUOTE, ctx_with_cocited
from tests.unit.test_verify_cascade import _route, haiku, luna_confirm
from tests.unit.verify_fakes import layer, make_claim, make_ctx, screen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))
from eval_guards import type_matches  # noqa: E402

OFF = "REFCHECK_V57_DISABLE"
ON = "REFCHECK_V57_ENABLE"


def _check(category: str, quote: str | None = None, note: str = "",
           passage_id: str | None = "P1") -> ElementCheck:
    return ElementCheck(element="e", category=category, passage_id=passage_id,  # type: ignore[arg-type]
                        quote=quote, note=note)


def test_hedged_stated_answer_keeps_the_element() -> None:
    ctx = ctx_with_cocited()
    hedged = _check("stated", STATED_QUOTE, "does not explicitly say it; paraphrase-level")
    found = decide("IL-6 reduction", hedged, ctx, ctx.pack)
    assert not found.cleared and found.category == "overstated"
    assert decide("IL-6 reduction", _check("stated", STATED_QUOTE), ctx, ctx.pack).cleared


def test_quote_edge_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = ctx_with_cocited()
    answer = _check("stated", "a " + STATED_QUOTE + " and")
    assert decide("IL-6 reduction", answer, ctx, ctx.pack).cleared
    monkeypatch.setenv(OFF, "21")
    assert not decide("IL-6 reduction", answer, ctx, ctx.pack).cleared


def test_framing_scaffold_of_the_cited_span(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = make_ctx(claim=make_claim("Healing with drug X proceeds in three phases."))
    found = decide("three phases", _check("absent", passage_id=None), ctx, ctx.pack)
    assert found.cleared and found.category == "framing"
    assert not decide("three phases", None, make_ctx(), make_ctx().pack).cleared
    monkeypatch.setenv(OFF, "23")
    assert not decide("three phases", _check("absent", passage_id=None), ctx, ctx.pack).cleared


def test_overstated_without_a_trigger_is_rechecked_as_wording(
        monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = ctx_with_cocited()
    answer = _check("overstated", WORDING_QUOTE, "slightly stronger wording", passage_id="A")
    found = decide("drug X is anti-inflammatory", answer, ctx, ctx.pack)
    assert found.cleared and found.category == "wording"
    assert not decide("drug X is always anti-inflammatory", answer, ctx, ctx.pack).cleared
    stronger = answer.model_copy(update={"note": "the claim says it reverses inflammation"})
    assert not decide("drug X is anti-inflammatory", stronger, ctx, ctx.pack).cleared
    monkeypatch.setenv(OFF, "27")
    assert not decide("drug X is anti-inflammatory", answer, ctx, ctx.pack).cleared


async def test_screen_tie_break_in_the_cascade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "off")
    script = {"verifier": [haiku("not_supported")], "confirm": [luna_confirm("supported")]}
    out, _ = await _route(script, scr=screen(0.9, topic=0.9))
    assert out.verdict == "partially_supported"  # #20 is experimental: off by default
    monkeypatch.setenv(ON, "20")
    script = {"verifier": [haiku("not_supported")], "confirm": [luna_confirm("supported")]}
    out, _ = await _route(script, scr=screen(0.9, topic=0.9))
    assert out.verdict == "partially_supported"  # the cross-check quoted nothing it supports
    quoted = layer("confirm", "supported", provider="openai", model_id="gpt-6-luna")
    script = {"verifier": [haiku("not_supported")], "confirm": [quoted]}
    out, _ = await _route(script, scr=screen(0.9, topic=0.9))
    assert (out.verdict, out.consensus_type) == ("supported", "disputed")
    assert out.needs_review and any(n.startswith("Screen tie-break") for n in out.notes)
    script = {"verifier": [haiku("not_supported")], "confirm": [luna_confirm("supported")]}
    out, _ = await _route(script, scr=screen(0.5, topic=0.9))
    assert out.verdict == "partially_supported"


def _adj(*decisions: ElementDecision) -> Adjudication:
    return Adjudication(meta=LayerResult(layer="adjudicate", role="adjudicator"),
                        decisions=list(decisions))


def test_union_targets_degree_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    adj = _adj(ElementDecision(element="a", category="absent"),
               ElementDecision(element="b", category="overstated"),
               ElementDecision(element="c", category="contradicted"))
    assert [d.element for d in union_targets(adj)] == ["a"]  # #29 is opt-in
    monkeypatch.setenv(ON, "29")
    assert [d.element for d in union_targets(adj)] == ["a", "b"]
    monkeypatch.setenv(OFF, "29")
    assert [d.element for d in union_targets(adj)] == ["a"]


def test_union_rules_clear_scaffolds_and_twins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ON, "24")
    twin = "macrophage polarisation toward M2 phenotype"
    adj = _adj(ElementDecision(element=twin, category="stated", cleared=True, quote="q1 q2"),
               ElementDecision(element="polarisation of macrophage phenotype toward M2",
                               category="absent"),
               ElementDecision(element="three phases", category="absent"),
               ElementDecision(element="macrophage polarisation toward M2 phenotype always",
                               category="overstated"),
               ElementDecision(element="capillary density", category="absent"))
    run = UnionRun(meta=LayerResult(layer="adjudicate_cocited", role="adjudicator"),
                   decisions=[UnionDecision(element=d.element) for d in adj.surviving])
    ruled = with_rules(run, adj, "Repair proceeds in three phases")
    assert [(d.element, d.rule) for d in ruled.cleared] == [
        ("polarisation of macrophage phenotype toward M2", "twin"), ("three phases", "framing")]
    assert ruled.cleared[0].quote is None  # a twin never lends its quote
    both = combined(adj, ruled)
    assert [(d.element, d.category) for d in both.cleared] == [
        (twin, "stated"), ("polarisation of macrophage phenotype toward M2", "stated"),
        ("three phases", "framing")]
    assert both.cleared[1].quote is None and both.cleared[1].validated is None
    assert [d.element for d in both.surviving] == [
        "macrophage polarisation toward M2 phenotype always", "capillary density"]
    assert "same point" in union_note(ruled.cleared[0])


def test_f15_coverage_limited_matches_missing_element_with_evidence_gap() -> None:
    assert type_matches("missing_element", "coverage_limited", ["evidence_gap"])
    assert not type_matches("missing_element", "coverage_limited", [])
    assert type_matches("evidence_gap", "coverage_limited")
    assert not type_matches("missing_element", "scope_overgeneralized", ["evidence_gap"])
