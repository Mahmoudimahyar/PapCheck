"""A claim figure the source states differently turns "supported" into a partial (V5.6, L3).

Synthetic text only (number_rule.py, outcome_rules.py): the claim says "more than
3,000 bone grafts" and the source states 48211 bone grafts, nowhere 3,000.
"""

import time

import pytest

from refcheck.models.adjudication import AdjudicateOutput
from refcheck.stages.verify_claims.adjudicate import run_adjudication
from refcheck.stages.verify_claims.number_rule import figure_conflict
from refcheck.stages.verify_claims.outcome_rules import RULE_LAYER
from refcheck.stages.verify_claims.slot_apply import SLOT_LAYER
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.verifier_helpers import PairContext, build_pair_context
from tests.unit.adjudicate_cascade import assert_coherent, haiku, route
from tests.unit.adjudicate_fakes import STATED, answer_all, ctx_with_cocited, enable, fake_call
from tests.unit.verify_fakes import ABSTRACT, make_claim, make_pack, make_ref

SOURCE = ("Introduction\n\nBone loss is common worldwide. In 2021 alone, 48211 bone "
          "grafts were placed worldwide. Regional registries reported 19034 bone "
          "grafts in one region. Each centre recorded 512 bone donors.\n\nResults\n\n"
          "Drug X reduced IL-6 levels by 40% compared with vehicle (p < 0.01).")
LOCKED = "number: source says 48,211; manuscript says 3,000"


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


@pytest.mark.parametrize(("claim", "expected"), [
    ("More than 3,000 bone grafts are placed each year.",
     ("3,000", "48,211", "minor")),  # a true lower bound, a gross understatement
    ("About 3,000 bone grafts are placed each year.", ("3,000", "48,211", "major")),
    ("Fewer than 500,000 bone grafts are placed.", ("500,000", "48,211", "minor")),
    ("Fewer than 200,000 bone grafts are placed.", None),  # a true bound, not gross
    ("Fewer than 6,000 bone grafts are placed.", ("6,000", "48,211", "major")),
    ("Some 48,211 bone grafts were placed.", None),  # stated
    ("About 3,000 grafts were placed.", ("3,000", "48,211", "major")),  # same kind
    ("About 3,000 skull grafts were placed.", None),  # no source figure of kind
    ("About 30,000 bone grafts were placed.", None),  # within a factor 2
    ("Over 3,000 procedures were performed.", None),  # no same-kind source figure
    ("Gels reached 3,000 in total.", None),  # a bare figure never qualifies
])
def test_figure_conflict(claim: str, expected: tuple[str, str, str] | None) -> None:
    found = figure_conflict(claim, SOURCE)
    assert (None if found is None else (found.claim, found.source, found.severity)) == expected


@pytest.mark.parametrize("space", [" ", "\u2009", "\u202f", "\u00a0"])
def test_thousands_written_with_a_space_are_one_figure(space: str) -> None:
    source = f"In total 10{space}000 patients received grafts in the registry."
    assert figure_conflict("Over 10,000 patients received grafts.", source) is None


def test_a_zero_source_figure_is_never_compared() -> None:
    source = "0 patients developed rejection, and the grafts were followed for months."
    assert figure_conflict("Rejection occurred in 12 patients.", source) is None


def test_a_different_object_is_not_the_same_kind() -> None:
    source = ("Gel A lowered graft rejection by 48 percent overall. It also gave a 20% "
              "reduction in IL-6 levels.")
    claim = "Gel A gave a 50% reduction in graft rejection."
    assert figure_conflict(claim, source) is None  # 48 percent rounds to 50%
    other = "Gel A gave a 20% reduction in IL-6 levels and a 70% reduction in TNF levels."
    assert figure_conflict("Gel A gave a 50% reduction in graft rejection.", other) is None


def test_a_total_twice_the_group_size_is_not_flagged() -> None:
    source = "We used 100 mice per group in two groups."
    assert figure_conflict("The trial enrolled 200 mice in total.", source) is None


def test_a_bound_satisfied_by_any_figure_never_cites_the_control() -> None:
    source = "Grafts survived 21 days in controls and 150 days in treated animals."
    assert figure_conflict("Graft survival exceeded 60 days in treated animals.", source) is None
    found = figure_conflict("Graft survival exceeded 20 days in treated animals.",
                            "Grafts survived 4 days in controls and 150 days in treated animals.")
    assert found is not None and (found.source, found.severity) == ("150", "minor")


def test_multiplier_words_scale_the_figure() -> None:
    source = "There are 9,500,000 people living with the disease and 4.1 million people at risk."
    assert figure_conflict("About 9.5 million people live with it.", source) is None
    found = figure_conflict("It affects about 2 million people.", source)
    assert found is not None and found.severity == "major"


def _ctx(text: str, cited_for: str = "", co_cited: int = 1,
         coverage: str = "full_text") -> PairContext:
    claim = make_claim(text, co_cited=co_cited).model_copy(update={"cited_for": cited_for})
    ref = make_ref()
    doc = build_source_document(ref.id, SOURCE, abstract_text=ABSTRACT) \
        if coverage == "full_text" else build_abstract_document(ref.id, SOURCE)
    ctx = build_pair_context(claim, ref, doc, make_pack(coverage=coverage))
    ctx.use_embeddings = False
    return ctx


async def test_supported_with_a_differently_stated_figure_becomes_partial() -> None:
    ctx = _ctx("More than 3,000 bone grafts are placed globally each year.")
    _, result = await route(ctx, {"verifier": [haiku("supported")]}, answer_all(STATED))
    assert result.verdict == "partially_supported" and result.needs_user_review
    assert (result.partial_type, result.partial_severity) == ("specific_detail_mismatch",
                                                              "minor")
    assert result.unsupported_elements == [LOCKED]
    assert "source says 48,211; manuscript says 3,000" in result.author_action
    assert "Number check: the source says 48,211" in result.reasoning
    assert result.consensus_type == "rule"
    # V5.7 #2: "each year" is nowhere in the source, so the slot audit runs (and is cleared)
    assert result.layer_path == ["verifier", SLOT_LAYER, RULE_LAYER]
    assert result.agreement_ratio == 1.0
    assert result.evidence_quotes  # the first check's quotes are kept
    assert_coherent(result)


async def test_not_applied_on_an_abstract_only_source() -> None:
    ctx = _ctx("About 3,000 bone grafts are placed each year.", coverage="abstract_only")
    _, result = await route(ctx, {"verifier": [haiku("supported")]}, answer_all(STATED))
    assert result.verdict == "supported" and RULE_LAYER not in result.layer_path


async def test_not_applied_to_a_multi_citation_sentence_without_its_own_share() -> None:
    whole = _ctx("About 3,000 bone grafts are placed each year.", co_cited=2)
    _, result = await route(whole, {"verifier": [haiku("supported")]}, answer_all(STATED))
    assert result.verdict == "supported"
    narrowed = _ctx("About 3,000 bone grafts are placed each year, and gels help.",
                    cited_for="About 3,000 bone grafts are placed each year",
                    co_cited=2)
    _, result = await route(narrowed, {"verifier": [haiku("supported")]}, answer_all(STATED))
    assert result.verdict == "partially_supported" and result.partial_severity == "major"


async def test_rule_elements_are_never_asked_about() -> None:
    ctx = ctx_with_cocited()
    locked = LOCKED
    calls: list[dict[str, object]] = []

    def respond(elements: list[str]) -> AdjudicateOutput | Exception:
        assert elements == ["IL-6 reduction"]
        return answer_all(STATED)(elements)

    with fake_call(respond, calls):
        adj = await run_adjudication(ctx, ctx.pack, "standard", [locked, "IL-6 reduction"],
                                     None, time.monotonic() + 60)
    assert [(d.element, d.category, d.cleared) for d in adj.decisions] == [
        (locked, "rule", False), ("IL-6 reduction", "stated", True)]
    assert len(calls) == 1
