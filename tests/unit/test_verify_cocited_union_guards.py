"""Co-cited union check guards: quote relevance, one passage at a time, per-element
interleaving, no retrieval once the budget is spent, and the layer's trace labels."""

import time

import pytest

from refcheck.llm import CostTracker
from refcheck.models.adjudication import CocitedCheck
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.layer_trace import layer_names
from refcheck.stages.verify_claims import cocited_union_apply, cocited_union_pack
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_apply import summarize
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cocited import CoCitedRef
from refcheck.stages.verify_claims.cocited_union_pack import UnionSource, union_sources
from refcheck.stages.verify_claims.cocited_union_rules import decide_union, whole_words_in
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.retrieval_models import EvidencePack, Passage
from refcheck.stages.verify_claims.source_document import build_source_document
from refcheck.stages.verify_claims.verifier_converters import layer_reasoning, layer_vote
from tests.unit.adjudicate_cascade import haiku
from tests.unit.adjudicate_fakes import with_elements
from tests.unit.union_fakes import E_ABSENT, ctx_with_union

E_SCAFFOLD = "the scaffold reduced macrophage infiltration"
P_METHODS = "Statistics used in the present study and in earlier work are described below."
P_RESULT = "Macrophage infiltration was lower around the scaffold than around the bare implant."
P_END = "Mass loss was measured weekly and the scaffold degraded slowly over time"
P_START = "in all treated animals at eight weeks no implant had to be removed."
ABS = "Gel Q was tested on skin wounds in rats. Wounds closed faster with the gel."
FILL = "Wound closure was followed with digital photographs every second day. "
HOUSED = "The animals were housed in standard cages with free access to food. "
COLLAGEN = "Collagen fibres were thicker with Gel Q in the healed dermis."


def _source(*texts: str, number: int = 12) -> list[UnionSource]:
    passages = [Passage(id=f"R{number}-P{i}", unit_idx=i, section="Results", text=t)
                for i, t in enumerate(texts, start=1)]
    pack = EvidencePack(passages=passages, coverage="full_text", retrieval_version="test")
    return [UnionSource(number=number, pack=pack)]


def _cited(element: str, quote: str, pid: str = "R12-P1") -> CocitedCheck:
    return CocitedCheck(element=element, category="cocited", passage_id=pid, quote=quote,
                        note="synthetic")


def test_a_quote_unrelated_to_the_element_never_clears() -> None:
    sources = _source(P_METHODS, P_RESULT)
    generic = decide_union(E_SCAFFOLD, _cited(E_SCAFFOLD, "in the present study and"), sources)
    assert not generic.cleared and generic.number is None
    reworded = decide_union(E_SCAFFOLD, _cited(E_SCAFFOLD, P_RESULT, "R12-P2"), sources)
    assert reworded.cleared and reworded.number == 12  # most content words kept


def test_the_co_cited_title_or_header_never_clears() -> None:
    titled = [s.model_copy(update={"title": P_RESULT}) for s in _source(P_METHODS, P_RESULT)]
    refused = decide_union(E_SCAFFOLD, _cited(E_SCAFFOLD, P_RESULT, "R12-P2"), titled)
    assert not refused.cleared and refused.note.startswith("refused (title/header")
    headed = [s.model_copy(update={"header": f"Journal X 2020\n{P_RESULT}\nA. Author"})
              for s in _source(P_METHODS, P_RESULT)]
    assert not decide_union(E_SCAFFOLD, _cited(E_SCAFFOLD, P_RESULT, "R12-P2"), headed).cleared


def test_a_quote_spliced_across_two_passages_or_cut_mid_word_never_clears() -> None:
    element = "the scaffold degraded slowly in all treated animals"
    spliced = "the scaffold degraded slowly over time in all treated animals"
    assert not decide_union(element, _cited(element, spliced), _source(P_END, P_START)).cleared
    joined = _source(f"{P_END} {P_START}")  # the same words inside ONE passage clear
    assert decide_union(element, _cited(element, spliced), joined).cleared
    partial = "ffold degraded slowly over ti"
    assert not decide_union("the scaffold degraded slowly", _cited(element, partial),
                            _source(P_END)).cleared
    assert whole_words_in("scaffold degraded slowly over time.", P_END)
    assert not whole_words_in("scaffold degraded slowly over ti", P_END)


async def test_every_element_gets_windows_before_any_gets_a_second(
        monkeypatch: pytest.MonkeyPatch) -> None:
    text = ("Abstract\n\n" + ABS + "\n\nIntroduction\n\n"
            + "Skin wounds heal through overlapping phases of repair. " * 6 + "\n\nResults\n\n"
            + "Capillary density in healed skin rose with Gel Q at day seven. " + FILL * 6
            + "Capillary density in healed skin stayed higher with Gel Q at day fourteen. "
            + HOUSED * 6 + COLLAGEN + " " + FILL * 6
            + "\n\nDiscussion\n\nGel Q may support repair of skin wounds. " * 3)
    ctx = ctx_with_union()
    ctx.co_cited = [CoCitedRef(number=2, title="Gel Q")]
    ctx.co_cited_docs = {2: build_source_document(2, text, abstract_text=ABS)}
    monkeypatch.setattr(cocited_union_pack, "UNION_PACK_TOKENS", 160)  # abstract + ~2 windows
    sources = await union_sources(ctx, [E_ABSENT, "thicker collagen fibres in the dermis"], None)
    texts = [p.text for p in sources[0].pack.passages]
    assert any("Capillary density" in t for t in texts)
    assert any(COLLAGEN in t for t in texts)  # the 2nd element is not crowded out


def _outcome() -> tuple[CascadeOutcome, Adjudication]:
    label = with_elements(haiku("partially_supported"), E_ABSENT)
    meta = LayerResult(layer="adjudicate", role="adjudicator", model_id="claude-haiku-5-5")
    adj = Adjudication(meta=meta, decisions=[ElementDecision(element=E_ABSENT,
                                                             category="absent")])
    out = CascadeOutcome(verdict="partially_supported", label_layer=label, layers=[label, meta],
                         layer_path=["verifier", "adjudicate"], decided_by="verifier",
                         consensus_type="verifier", adjudication=summarize(adj))
    return out, adj


@pytest.mark.parametrize(("tracker", "seconds", "kind"), [
    (CostTracker(max_cost=0.0), 100.0, "budget"), (None, 10.0, "timeout")])
async def test_no_retrieval_once_the_budget_or_time_is_spent(
        monkeypatch: pytest.MonkeyPatch, tracker: CostTracker | None, seconds: float,
        kind: str) -> None:
    retrieved: list[list[str]] = []

    async def spy(ctx: object, elements: list[str], tracker: object) -> list[UnionSource]:
        retrieved.append(elements)
        return []

    monkeypatch.setenv("REFCHECK_COCITED_UNION", "on")
    monkeypatch.setattr(cocited_union_apply, "union_sources", spy)
    out, adj = _outcome()
    done = await cocited_union_apply.union_outcome(ctx_with_union(), out, adj, tracker,
                                                   time.monotonic() + seconds)
    assert not retrieved and done.verdict == "partially_supported"
    assert done.layer_path[-1] == "adjudicate_cocited" and done.layers[-1].error_kind == kind
    assert done.adjudication is not None and done.adjudication.union is not None
    assert done.adjudication.union.outcome == "error" and done.adjudication.union.refs == [2, 3]


def test_the_union_layer_has_its_own_trace_label_tier_and_abbreviation() -> None:
    lay = LayerResult(layer="adjudicate_cocited", role="adjudicator", model_id="m",
                      model_display="claude-haiku-5-5", error="timeout")
    entry = layer_reasoning(lay)
    assert entry.model_display == "Element check (co-cited) · claude-haiku-5-5"
    vote = layer_vote(lay)
    assert (vote.abbreviation, vote.tier) == ("AC", 2)
    legacy = VerificationResult(claim_id=1, reference_id=1, model_reasoning=[
        entry, entry.model_copy(update={"model_display": "Element check · m"})])
    assert layer_names(legacy) == ["adjudicate_cocited", "adjudicate"]
