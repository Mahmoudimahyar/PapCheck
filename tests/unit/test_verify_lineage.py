"""Lineage connectives (lineage.py) and the deterministic outcome rule (V5.6, L4).

Synthetic text only: a sentence that opens with "Building on these results" while
citing work OLDER than the work cited in the previous sentence.
"""

import pytest

from refcheck.stages.verify_claims.lineage import (
    citation_years,
    lineage_action,
    lineage_conflict,
    lineage_connective,
)
from refcheck.stages.verify_claims.outcome_rules import RULE_LAYER, apply_outcome_rules
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, route
from tests.unit.adjudicate_fakes import (
    STATED,
    answer_all,
    ctx_with_cocited,
    enable,
    with_elements,
)
from tests.unit.verify_fakes import make_claim, make_ref

PREV = "Gel Q protected islets in large animals for months (Rivera et al., 2019)."
SENTENCE = "Building on these results, gel Q protected human cells in mice (Ito et al., 2015)."


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


@pytest.mark.parametrize(("sentence", "connective"), [
    (SENTENCE, "Building on these results"),
    ("Based on these findings, the team tested gel Q.", "Based on these findings"),
    ("Following this, gel Q was coated.", "Following this"),
    ("Extending this work, Ito et al. coated gel Q.", "Extending this work"),
    ("Subsequently, gel Q was coated.", "Subsequently"),
    ("In a follow-up study, gel Q was coated.", "In a follow-up study"),
    ("Later, gel Q was coated.", "Later"),
    ("Building upon this approach, gel Q was coated.", "Building upon this approach"),
    ("Gel Q, building on this, was coated.", None),  # not at the start
    ("Gel Q was later coated.", None),
    ("Building on their earlier work, Ito et al. coated gel Q.", "Building on their earlier work"),
    ("Later studies coated gel Q.", "Later studies"),
    ("Later-stage grafts were rejected faster.", None),  # a compound, not a connective
    ("Afterward-treated grafts were rejected faster.", None),
    ("Later grafts were rejected faster.", None),
    ("Following this protocol, grafts were scored blindly.", None),  # not a result noun
    ("Based on that definition, rejection was graded.", None),
])
def test_lineage_connective(sentence: str, connective: str | None) -> None:
    assert lineage_connective(sentence) == connective


def test_citation_years_are_author_year_citations_only() -> None:
    text = ("In 2018, gels were used (Rivera et al., 2019; Lee and Kim, 2021) and "
            "Park (2017) agreed; 2020 patients were enrolled [12].")
    assert citation_years(text) == [2019, 2021, 2017]


@pytest.mark.parametrize("text", [
    "Over 2020 grafts were analysed.", "Approximately 2050 patients were enrolled.",
    "Particles were coated with DSPE-PEG 2000.", "Particles carried DSPE-PEG (2000).",
    "Grafts were collected in December 2019.", "Grafts were collected (December 2019).",
])
def test_counts_reagents_and_dates_are_not_citations(text: str) -> None:
    assert citation_years(text) == []


def test_a_count_next_to_a_citation_never_sets_the_prior_year() -> None:
    prev = "Over 2020 grafts were analysed (Smith et al., 2010)."
    assert citation_years(prev) == [2010]
    assert lineage_conflict("Building on these results, gel B was tested.", prev, 2012) is None


@pytest.mark.parametrize(("year", "prev", "conflict"), [
    (2015, PREV, True),  # older than the work it builds on
    (2019, PREV, False),  # same year: possible
    (2022, PREV, False),
    (None, PREV, False),  # unknown year
    (2015, "Gel Q protected islets in large animals [4].", False),  # numbered: no year
])
def test_lineage_conflict(year: int | None, prev: str, conflict: bool) -> None:
    found = lineage_conflict(SENTENCE, prev, year)
    assert (found is not None) == conflict
    if found is not None:
        assert found.element.startswith("lineage: Building on these results")
        assert "(2015) predates the work it is said to build on (2019)" in found.note


def _lineage_ctx(year: int = 2015) -> PairContext:
    ctx = ctx_with_cocited()
    claim = make_claim("Building on these results, gel Q protected human cells in mice.")
    ctx.claim = claim.model_copy(update={"manuscript_text": SENTENCE})
    ctx.prev_sentence = PREV
    ctx.ref = make_ref(year=year)
    return ctx


async def test_supported_with_an_impossible_lineage_becomes_a_minor_partial() -> None:
    out, result = await route(_lineage_ctx(), {"verifier": [haiku("supported")]},
                              answer_all(STATED))
    assert result.verdict == "partially_supported" and result.partial_severity == "minor"
    assert result.partial_type == "specific_detail_mismatch" and result.needs_user_review
    assert result.unsupported_elements[0].startswith("lineage: ")
    assert "predates the work it is said to build on" in result.reasoning
    assert result.layer_path[-1] == RULE_LAYER and "adjudicate" not in result.layer_path
    assert result.author_action == ("Rephrase or reorder 'Building on these results': the "
                                    "cited work (2015) predates the work it is said to build "
                                    "on (2019).")
    assert result.model_reasoning[-1].model_display.startswith("Rule check")
    assert result.votes[-1].abbreviation == "R"
    assert_coherent(result)


def test_lineage_action_only_for_a_lineage_element() -> None:
    assert lineage_action("dose in rats") is None and lineage_action(None) is None


async def test_a_possible_lineage_changes_nothing() -> None:
    _, result = await route(_lineage_ctx(2021), {"verifier": [haiku("supported")]},
                            answer_all(STATED))
    assert result.verdict == "supported" and RULE_LAYER not in result.layer_path


async def test_the_adjudicator_clearing_everything_cannot_drop_the_lineage_element() -> None:
    partial = with_elements(haiku("partially_supported"), "IL-6 reduction")
    calls: list[dict[str, object]] = []
    out, result = await route(_lineage_ctx(), {"verifier": [partial],
                                               "confirm": [luna("partially_supported")]},
                              answer_all(STATED), calls)
    assert calls and calls[0]["variables"]["elements"] == ["IL-6 reduction"]  # type: ignore[index]
    assert result.verdict == "partially_supported"
    assert result.unsupported_elements == [out.label_layer.output.unsupported_elements[0]]  # type: ignore[union-attr]
    assert result.unsupported_elements[0].startswith("lineage: ")
    assert result.layer_path[-2:] == ["adjudicate", RULE_LAYER]
    assert_coherent(result)


async def test_a_partial_keeps_its_type_and_gains_the_lineage_element() -> None:
    partial = with_elements(haiku("partially_supported"), "in human patients",
                            ptype="scope_overgeneralized", severity="major")
    _, result = await route(_lineage_ctx(), {"verifier": [partial],
                                             "confirm": [luna("partially_supported")]},
                            answer_all(("absent", None, None, "not stated")))
    assert result.partial_type == "scope_overgeneralized" and result.partial_severity == "major"
    assert result.unsupported_elements[0] == "in human patients"
    assert result.unsupported_elements[-1].startswith("lineage: ")
    assert result.layer_path.count(RULE_LAYER) == 1


def test_rules_never_touch_a_negative_verdict() -> None:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome
    lay = haiku("not_supported", supports=False)
    out = CascadeOutcome(verdict="not_supported", label_layer=lay, layers=[lay],
                         layer_path=["verifier"])
    assert apply_outcome_rules(_lineage_ctx(), out) == out


def test_a_demoted_supported_drops_its_supported_notes_and_consensus() -> None:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome
    lay = haiku("supported")
    note = ("Element check: every element the first check called unsupported was cleared, "
            "so the verdict is supported instead of partially supported.")
    kept = "Element check: 'in mice' - a wording difference only."
    out = CascadeOutcome(verdict="supported", label_layer=lay, layers=[lay],
                         layer_path=["verifier", "adjudicate"], decided_by="verifier",
                         consensus_type="adjudicated", notes=[note, kept])
    after = apply_outcome_rules(_lineage_ctx(), out)
    assert after.verdict == "partially_supported" and after.consensus_type == "rule"
    assert note not in after.notes and kept in after.notes
    screen = out.model_copy(update={"consensus_type": "screen_clear", "decided_by": "screen"})
    assert apply_outcome_rules(_lineage_ctx(), screen).consensus_type == "rule"
    disputed = out.model_copy(update={"consensus_type": "disputed"})
    assert apply_outcome_rules(_lineage_ctx(), disputed).consensus_type == "disputed"
