"""V5.6 (L2): no clearance without a quote -- the verifier's "dismissed" audit.

Synthetic data only.
"""

from unittest.mock import AsyncMock, patch

import pytest

from refcheck.models.verification import Dismissal, EvidenceQuote, JudgeOutput
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import verifier_final
from refcheck.stages.verify_claims.cocited import co_cited_ref
from refcheck.stages.verify_claims.dismissals import audit_dismissals, check
from refcheck.stages.verify_claims.layer_quotes import ValidatedQuote
from refcheck.stages.verify_claims.layers import run_layer
from refcheck.stages.verify_claims.partial_fields import partial_fields, uncovered_elements
from refcheck.stages.verify_claims.verifier_converters import layer_reasoning
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.verify_fakes import (
    RESULT_TEXT,
    judge_output,
    layer,
    llm_result,
    make_claim,
    make_ctx,
    make_pack,
)

_PATCH = "refcheck.stages.verify_claims.layers.call_llm_raw"
COCITED = "Gel Y restored limb function in rats with femoral defects."


def _d(element: str, guard: str, quote: str, passage_id: str = "P1") -> Dismissal:
    return Dismissal.model_validate({"element": element, "guard": guard,
                                     "passage_id": passage_id, "quote": quote})


def _ctx() -> PairContext:
    ctx = make_ctx(make_claim(co_cited=2))
    ctx.co_cited = [co_cited_ref(7, "Gel Y in rats", COCITED)]
    return ctx


def _out(*dismissed: Dismissal, elements: tuple[str, ...] = ()) -> JudgeOutput:
    return judge_output("supported", [("P1", RESULT_TEXT, "supports")]).model_copy(update={
        "dismissed": list(dismissed), "unsupported_elements": list(elements),
        "benign_notes": ["overliteral_wording", "cocited_share"]})  # never trusted alone


def test_wording_needs_a_source_quote_and_an_eligible_element() -> None:
    ctx, pack = _ctx(), make_pack()
    assert check(_d("lowered IL-6", "overliteral_wording", RESULT_TEXT), pack, ctx, []) == "valid"
    assert "not in this source" in check(
        _d("lowered IL-6", "overliteral_wording", "IL-6 fell sharply in treated animals."),
        pack, ctx, [])
    assert "too short" in check(_d("lowered IL-6", "overliteral_wording", "X reduced"),
                                pack, ctx, [])
    for element in ("every year", "via immune rejection", "in patients", "should be used",
                    "by 45%", "always"):  # V5.7 #3: phrases RESULT_TEXT does not state
        why = check(_d(element, "author_framing_or_example", RESULT_TEXT), pack, ctx, [])
        assert why not in ("valid", "not_needed") and "cannot clear" in why, element
    assert check(_d("", "overliteral_wording", RESULT_TEXT), pack, ctx, []) != "valid"


def test_cocited_share_needs_the_co_cited_abstract() -> None:
    ctx, pack = _ctx(), make_pack()
    assert check(_d("restored limb function", "cocited_share", COCITED, "7"),
                 pack, ctx, []) == "valid"
    assert "does not state" in check(_d("restored limb function", "cocited_share",
                                        "Gel Y cured all rats.", "7"), pack, ctx, [])
    assert "co-cited abstract" in check(_d("restored limb function", "cocited_share",
                                           "Gel Y restored limb function in all rats.", "7"),
                                        pack, ctx, [])


def test_cocited_share_not_needed_when_this_source_states_it() -> None:
    ctx, pack = _ctx(), make_pack()
    # The "co-cited" quote is really this source's text ...
    assert check(_d("reduced IL-6", "cocited_share", RESULT_TEXT), pack, ctx, []) == "not_needed"
    # ... or the TEXT of a validated evidence quote of this source states the element.
    stating = [ValidatedQuote(passage_id="P1", text="Gel Y restored limb function in mice.",
                              role="supports", states="")]
    assert check(_d("restored limb function", "cocited_share", COCITED, "7"),
                 pack, ctx, stating) == "not_needed"


def test_a_states_label_alone_never_makes_a_clearance_not_needed() -> None:
    """The model's own ``states`` label is not trusted: the quote text must state it."""
    ctx, pack = _ctx(), make_pack()
    labelled = [ValidatedQuote(passage_id="P1", text=RESULT_TEXT, role="supports",
                               states="healing")]
    verdict = check(_d("impede natural healing", "cocited_share",
                       "Gel Z impedes natural healing in all.", "7"), pack, ctx, labelled)
    assert verdict not in ("valid", "not_needed")


@pytest.mark.parametrize(("element", "guard", "quote"), [
    ("impede natural healing", "cocited_share", "X reduced"),  # short, unrelated: was not_needed
    ("impede natural healing", "cocited_share", "Drug X reduced IL-6 levels by 40%"),
    ("in all transplant recipients worldwide", "secondary_source", "X reduced"),
    ("in all transplant recipients worldwide", "secondary_source", RESULT_TEXT),
    ("lowered IL-6 levels", "secondary_source", "Body weight did not differ between the groups"),
    ("lowered IL-6", "overliteral_wording", "X reduced"),  # a 2-word quote
])
def test_lax_clearances_are_rejected_and_routed(element: str, guard: str, quote: str) -> None:
    ctx, pack = _ctx(), make_pack()
    out = audit_dismissals(_out(_d(element, guard, quote, "7" if guard == "cocited_share"
                                   else "P1")), pack, ctx, [])
    assert out.output.dismissed == [] and out.output.benign_notes == []
    assert uncovered_elements(out.output) == [element] and len(out.rejected) == 1


def test_a_negation_flipped_quote_never_clears() -> None:
    source = "The hydrogel did not prolong graft survival in treated rats."
    ctx, pack = _ctx(), make_pack((source,))
    flipped = "The hydrogel did prolong graft survival in treated rats."
    wording = "overliteral_wording"
    assert check(_d("prolonged survival", wording, flipped), pack, ctx, []) != "valid"
    assert check(_d("prolonged survival", wording, source), pack, ctx, []) == "valid"


def test_secondary_source_needs_a_stating_quote_without_specifics() -> None:
    ctx, pack = _ctx(), make_pack()
    assert check(_d("reduced IL-6 levels", "secondary_source", RESULT_TEXT), pack, ctx,
                 []) == "valid"
    assert "secondary report" in check(_d("reduced IL-6 in mice", "secondary_source",
                                          RESULT_TEXT), pack, ctx, [])


def test_audit_derives_notes_and_reports_rejected_elements() -> None:
    ctx, pack = _ctx(), make_pack()
    out = _out(_d("restored limb function", "cocited_share", COCITED, "7"),
               _d("every year", "overliteral_wording", RESULT_TEXT),
               _d("reduced IL-6", "cocited_share", RESULT_TEXT),
               elements=("restored limb function",))
    audit = audit_dismissals(out, pack, ctx, [])
    assert audit.output.benign_notes == ["cocited_share"]  # the not-needed one adds none
    assert [d.element for d in audit.output.dismissed] == ["restored limb function",
                                                           "reduced IL-6"]
    assert audit.output.unsupported_elements == ["restored limb function", "every year"]
    assert len(audit.rejected) == 1 and "'every year'" in audit.rejected[0]
    assert uncovered_elements(audit.output) == ["every year"]


def test_not_needed_cocited_clearance_records_no_guard_or_author_note() -> None:
    ctx, pack = _ctx(), make_pack()
    audit = audit_dismissals(_out(_d("reduced IL-6", "cocited_share", RESULT_TEXT)),
                             pack, ctx, [])
    verifier = layer("verifier").model_copy(update={"output": audit.output})
    fields = partial_fields("supported", verifier, [verifier], "full_text", [])
    assert fields.guards_applied == [] and fields.author_action == ""
    assert fields.unsupported_elements == []


@pytest.mark.usefixtures("strict")
async def test_run_layer_rejected_clearance_makes_an_unusual_positive() -> None:
    ctx = _ctx()
    out = _out(_d("every year", "overliteral_wording", RESULT_TEXT))
    with patch(_PATCH, AsyncMock(return_value=llm_result(out))):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert result.output is not None and result.output.benign_notes == []
    assert uncovered_elements(result.output) == ["every year"]
    assert verifier_final(result, True, None, ScreenThresholds()) is None
    assert "Clearance not accepted: 'every year'" in layer_reasoning(result).reasoning


@pytest.mark.usefixtures("strict")
async def test_run_layer_context_only_quote_is_trace_not_evidence() -> None:
    ctx = make_ctx()
    quote = EvidenceQuote.model_validate({"passage_id": "P1", "text": RESULT_TEXT,
                                          "role": "supports", "states": ""})
    out = judge_output("supported").model_copy(update={"quotes": [quote]})
    with patch(_PATCH, AsyncMock(return_value=llm_result(out))):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert result.validated_quotes == [] and len(result.context_quotes) == 1
    assert verifier_final(result, True, None, ScreenThresholds()) is None  # unusual positive
    trace = layer_reasoning(result)
    assert trace.evidence_quotes == [] and "Context only, not evidence" in trace.reasoning
