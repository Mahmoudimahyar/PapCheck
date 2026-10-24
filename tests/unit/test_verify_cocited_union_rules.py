"""Co-cited union check: when it runs, the clearing rule and the co-cited passages."""

import time

import pytest

from refcheck.llm import CostTracker
from refcheck.llm.errors import LLMRefusalError
from refcheck.models.adjudication import CocitedCheck
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_apply import summarize
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cocited import CoCitedRef
from refcheck.stages.verify_claims.cocited_union_apply import union_outcome
from refcheck.stages.verify_claims.cocited_union_pack import (
    UNION_PACK_TOKENS,
    union_documents,
    union_sources,
)
from refcheck.stages.verify_claims.cocited_union_rules import decide_union, figures_kept
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_cascade import haiku
from tests.unit.adjudicate_fakes import with_elements
from tests.unit.union_fakes import (
    E_ABSENT,
    REF2_QUOTE,
    REF3_QUOTE,
    cites,
    ctx_with_union,
    fake_union,
    ref2_doc,
)


@pytest.fixture(autouse=True)
def _union_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_COCITED_UNION", "on")


def _outcome(verdict: str = "partially_supported",
             supports: bool = True) -> tuple[CascadeOutcome, Adjudication]:
    label = with_elements(haiku(verdict, supports=supports), E_ABSENT)
    meta = LayerResult(layer="adjudicate", role="adjudicator", model_id="claude-haiku-5-5")
    adj = Adjudication(meta=meta, decisions=[ElementDecision(element=E_ABSENT,
                                                             category="absent")])
    out = CascadeOutcome(verdict=verdict, label_layer=label, layers=[label, meta],
                         layer_path=["verifier", "adjudicate"], decided_by="verifier",
                         consensus_type="verifier", adjudication=summarize(adj))
    return out, adj


async def _run(ctx: PairContext, out: CascadeOutcome, adj: Adjudication,
               tracker: CostTracker | None = None, seconds: float = 100.0,
               ) -> tuple[CascadeOutcome, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []
    with fake_union(cites(REF2_QUOTE), calls):
        done = await union_outcome(ctx, out, adj, tracker, time.monotonic() + seconds)
    return done, calls


async def test_skipped_when_this_reference_does_not_support_its_own_share() -> None:
    out, adj = _outcome(supports=False)
    done, calls = await _run(ctx_with_union(), out, adj)
    assert not calls and done.verdict == "partially_supported"
    assert done.layer_path == out.layer_path
    assert done.adjudication is not None and done.adjudication.union is not None
    assert done.adjudication.union.outcome == "skipped"


@pytest.mark.parametrize(("tracker", "seconds", "kind"), [
    (CostTracker(max_cost=0.0), 100.0, "budget"), (None, 1.0, "timeout")])
async def test_budget_or_time_exhausted_leaves_the_verdict(
        tracker: CostTracker | None, seconds: float, kind: str) -> None:
    out, adj = _outcome()
    done, calls = await _run(ctx_with_union(), out, adj, tracker, seconds)
    assert not calls and done.verdict == "partially_supported"
    assert done.label_layer is out.label_layer and done.notes == out.notes
    assert done.layer_path == ["verifier", "adjudicate", "adjudicate_cocited"]
    assert done.layers[-1].error_kind == kind
    assert done.adjudication is not None and done.adjudication.union is not None
    assert done.adjudication.union.outcome == "error"


async def test_a_failed_call_leaves_the_verdict() -> None:
    out, adj = _outcome()
    with fake_union(lambda e, v: LLMRefusalError("refused", "claude-haiku-5-5")):
        done = await union_outcome(ctx_with_union(), out, adj, None, time.monotonic() + 100)
    assert done.verdict == "partially_supported" and done.layers[-1].error
    assert done.adjudication is not None and done.adjudication.union is not None
    assert done.adjudication.union.outcome == "error"


@pytest.mark.parametrize("verdict", ["not_supported", "contradicted", "supported"])
async def test_never_on_other_verdicts(verdict: str) -> None:
    out, adj = _outcome(verdict)
    done, calls = await _run(ctx_with_union(), out, adj)
    assert done is out and not calls


async def test_duplicates_of_this_reference_and_repeats_are_skipped() -> None:
    ctx = ctx_with_union()
    ctx.co_cited = [CoCitedRef(number=1, title="this one"), CoCitedRef(number=4, title="dup"),
                    CoCitedRef(number=2, title="Gel Q"), CoCitedRef(number=2, title="again")]
    ctx.co_cited_docs = {1: ctx.doc, 4: ctx.doc.model_copy(), 2: ref2_doc()}
    assert [n for n, _, _ in union_documents(ctx)] == [2]
    ctx.co_cited = ctx.co_cited[:2]
    out, adj = _outcome()
    done, calls = await _run(ctx, out, adj)
    assert done is out and not calls


async def test_passages_are_labelled_per_reference_within_the_cap() -> None:
    sources = await union_sources(ctx_with_union(), [E_ABSENT, "IL-6 in human plasma"], None)
    assert [s.number for s in sources] == [2, 3]
    assert all(p.id.startswith(f"R{s.number}-") for s in sources for p in s.pack.passages)
    assert sum(s.pack.total_tokens for s in sources) <= UNION_PACK_TOKENS
    assert any(REF2_QUOTE in p.text for p in sources[0].pack.passages)
    assert [p.id for p in sources[1].pack.passages] == ["R3-A"]


@pytest.mark.parametrize(("element", "quote", "kept"), [
    ("reduced IL-6 by 40%", "drug X reduced IL-6 levels by 40% in mice", True),
    ("reduced IL-6 by 40%", "drug X reduced IL-6 levels by 30% in mice", False),
    ("reduced IL-6 by 40%", "drug X reduced IL-6 levels by 140% in mice", False),
    ("effective in all patients", "the gel was effective in some patients", False),
    ("effective in all patients", "the gel was effective in all patients", True),
    ("IL-6 lowered", "Drug X lowered IL-6 levels in plasma", True),  # IL-6 is a name
])
def test_numbers_and_quantifiers_must_be_quoted(element: str, quote: str,
                                                kept: bool) -> None:
    assert figures_kept(element, quote) is kept


async def test_a_short_quote_or_another_category_never_clears() -> None:
    sources = await union_sources(ctx_with_union(), [E_ABSENT], None)
    pid = next(p.id for p in sources[0].pack.passages if REF2_QUOTE in p.text)
    short = CocitedCheck(element=E_ABSENT, category="cocited", passage_id=pid,
                         quote="Gel Q increased capillary", note="")
    absent = short.model_copy(update={"category": "absent", "quote": REF2_QUOTE})
    good = short.model_copy(update={"quote": REF2_QUOTE})
    assert not decide_union(E_ABSENT, short, sources).cleared
    assert not decide_union(E_ABSENT, absent, sources).cleared
    assert not decide_union(E_ABSENT, None, sources).cleared
    assert decide_union(E_ABSENT, good, sources).number == 2
    other = good.model_copy(update={"quote": REF3_QUOTE})
    assert not decide_union(E_ABSENT, other, sources).cleared
