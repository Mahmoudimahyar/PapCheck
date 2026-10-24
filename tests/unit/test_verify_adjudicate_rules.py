"""Element adjudicator: the clearing rule (exact quotes, disqualifiers) and answer matching."""

import pytest

from refcheck.models.adjudication import ElementCheck
from refcheck.stages.verify_claims.adjudicate_rules import decide, is_locked, match_checks
from refcheck.stages.verify_claims.clear_rules import disqualifier
from tests.unit.adjudicate_fakes import (
    ABSENT,
    COCITED,
    FABRICATED,
    FRAMING,
    FRAMING_NO_QUOTE,
    STATED,
    WORDING,
    WORDING_QUOTE,
    Answer,
    ctx_with_cocited,
)

E1, E2 = "commonly used in ankle braces", "in elderly runners"


def check(answer: Answer, element: str = "element") -> ElementCheck:
    category, passage_id, quote, note = answer
    return ElementCheck(element=element, category=category, passage_id=passage_id,  # type: ignore[arg-type]
                        quote=quote, note=note)


def test_stated_needs_a_quote_found_exactly_in_the_pack() -> None:
    ctx = ctx_with_cocited()
    ok = decide("IL-6 reduction", check(STATED), ctx, ctx.pack)
    assert ok.cleared and ok.validated is not None and ok.validated.passage_id == "P1"
    assert not decide("IL-6 reduction", check(FABRICATED), ctx, ctx.pack).cleared
    no_quote = ("stated", "P1", None, "P1 states it.")
    assert not decide("x", check(no_quote), ctx, ctx.pack).cleared
    too_short = ("stated", "P1", "Drug X reduced IL-6", "")  # 4 words: 5 are needed
    assert not decide("x", check(too_short), ctx, ctx.pack).cleared
    wrong_id = ("stated", "P9", STATED[2], "")  # wrong passage id: the whole pack is searched
    assert decide("x", check(wrong_id), ctx, ctx.pack).cleared


@pytest.mark.parametrize("quote", [
    "Drug X increased IL-6 levels by 40% compared with vehicle",  # one word inverted
    "Drug X reduced IL-6 levels by 40% compared with placebo",  # one word substituted
    "Drug X reduced IL-6 levels by 45% compared with vehicle",  # another figure
])
def test_a_one_word_change_never_clears(quote: str) -> None:
    ctx = ctx_with_cocited()
    for category, passage_id in (("stated", "P1"), ("wording", "P1")):
        answer = (category, passage_id, quote, "near match")
        assert not decide("IL-6 reduction", check(answer), ctx, ctx.pack).cleared
    changed = ("cocited", "2", "Gel Q raised macrophage counts in rat skin wounds", "")
    assert not decide("macrophages", check(changed), ctx, ctx.pack).cleared


def test_cocited_clears_only_from_a_shown_abstract() -> None:
    ctx = ctx_with_cocited()
    assert decide("macrophages", check(COCITED), ctx, ctx.pack).cleared
    from_title = ("cocited", "3", "Drug X lowers IL-6 everywhere", "title says so")
    assert not decide("IL-6", check(from_title), ctx, ctx.pack).cleared
    in_source_only = ("cocited", "2", STATED[2], "")  # this source's text, not reference 2's
    assert not decide("IL-6", check(in_source_only), ctx, ctx.pack).cleared
    ctx.co_cited = []
    assert not decide("macrophages", check(COCITED), ctx, ctx.pack).cleared


def test_framing_and_wording_need_an_exact_quote() -> None:
    ctx = ctx_with_cocited()
    framing = decide("two stages", check(FRAMING), ctx, ctx.pack)
    assert framing.cleared and framing.validated is not None  # the factual core it wraps
    assert not decide("two stages", check(FRAMING_NO_QUOTE), ctx, ctx.pack).cleared
    invented = ("framing", "P1", FABRICATED[2], "The author's agenda.")
    assert not decide("two stages", check(invented), ctx, ctx.pack).cleared
    wording = decide("anti-inflammatory", check(WORDING), ctx, ctx.pack)
    assert wording.cleared and wording.validated is not None
    assert wording.validated.text == WORDING_QUOTE
    no_note = ("framing", "P1", STATED[2], "  ")
    assert not decide("two stages", check(no_note), ctx, ctx.pack).cleared
    note_only = ("wording", None, None, "The source says 'lowers' for 'reduces'.")
    assert not decide("lowers", check(note_only), ctx, ctx.pack).cleared
    for answer in (ABSENT, ("broadened", None, None, "mice only"),
                   ("overstated", None, None, "hedged"),
                   ("contradicted", None, None, "other figure")):
        assert not decide("x", check(answer), ctx, ctx.pack).cleared
    missing = decide("x", None, ctx, ctx.pack)
    assert not missing.cleared and missing.category == "absent"


@pytest.mark.parametrize("element", [
    "widely used", "in all patients", "most runners", "for 60 days", "a 45% reduction",
    "p < 0.05", "performed every year", "due to immune rejection", "a future need for gels",
    "in human patients", "an IL-6-specific effect", "thereby activating macrophages",
])
def test_disqualified_elements_are_never_framing_or_wording(element: str) -> None:
    ctx = ctx_with_cocited()
    assert disqualifier(element) is not None
    assert not decide(element, check(FRAMING), ctx, ctx.pack).cleared
    assert not decide(element, check(WORDING), ctx, ctx.pack).cleared
    assert decide(element, check(STATED), ctx, ctx.pack).cleared  # a quote may state it


def test_a_disqualifier_the_clearing_quote_states_does_not_refuse(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """V5.7 #3: diff-based; the framing quote states "40%" (STATED_QUOTE)."""
    ctx = ctx_with_cocited()
    assert decide("a 40% reduction", check(FRAMING), ctx, ctx.pack).cleared
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "3")  # V5.6: any number refuses
    assert not decide("a 40% reduction", check(FRAMING), ctx, ctx.pack).cleared


def test_names_with_digits_and_plain_words_are_not_disqualified() -> None:
    for element in ("lowers IL-6", "two-stage scheme", "commonly used in ankle braces",
                    "CD4+ cells", "a second approach"):
        assert disqualifier(element) is None, element


@pytest.mark.parametrize("element", [
    "lineage: Building on these results (the cited work, 2016, predates ..., 2018)",
    "number: source says 48,211; manuscript says 3,000",
])
def test_rule_elements_are_never_cleared(element: str) -> None:
    ctx = ctx_with_cocited()
    assert is_locked(element)
    for answer in (STATED, WORDING, FRAMING, COCITED, None):
        decision = decide(element, check(answer, element) if answer else None, ctx, ctx.pack)
        assert not decision.cleared and decision.category == "rule"


def test_elements_match_by_identity_not_position() -> None:
    same = [check(WORDING, E1), check(ABSENT, E2)]
    assert match_checks([E1, E2], same) == same
    reworded = [check(ABSENT, "Elderly runner")]
    matched = match_checks([E1, E2], reworded)
    assert matched[0] is None and matched[1] is reworded[0]
    unrelated = [check(WORDING, "a"), check(ABSENT, "b")]
    assert match_checks([E1, E2], unrelated) == [None, None]


def test_duplicated_dropped_or_reordered_answers_never_clear_another_element() -> None:
    duplicated = [check(FRAMING, E1), check(FRAMING, E1)]  # E2 dropped, E1 twice
    assert match_checks([E1, E2], duplicated) == [duplicated[0], None]
    reordered = [check(ABSENT, E2), check(FRAMING, E1)]
    assert match_checks([E1, E2], reordered) == [reordered[1], reordered[0]]
    nested = ["IL-6 levels", "IL-6 levels in mice"]  # token-set 100 both ways
    swapped = [check(ABSENT, nested[1]), check(FRAMING, nested[0])]
    assert match_checks(nested, swapped) == [swapped[1], swapped[0]]
    ctx = ctx_with_cocited()
    decisions = [decide(e, c, ctx, ctx.pack)
                 for e, c in zip([E1, E2], match_checks([E1, E2], duplicated), strict=True)]
    assert [d.cleared for d in decisions] == [True, False]
    assert decisions[1].category == "absent"


def test_front_matter_never_clears() -> None:
    """V5.6 (E1): a title quote must not become a stored "stated" evidence quote."""
    ctx = ctx_with_cocited()
    ctx.ref = ctx.ref.model_copy(update={"title": STATED[2]})  # the title is in the pack
    decision = decide("IL-6 reduction", check(STATED), ctx, ctx.pack)
    assert not decision.cleared and decision.validated is None
    assert decision.note.startswith("refused (title/header is not evidence)")
    wording = decide("IL-6 reduction", check(WORDING), ctx, ctx.pack)
    assert wording.cleared  # another quote still clears
    ctx.co_cited = [c.model_copy(update={"title": COCITED[2]}) for c in ctx.co_cited]
    assert not decide("macrophages", check(COCITED), ctx, ctx.pack).cleared
