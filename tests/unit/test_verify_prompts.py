"""Prompt contract for M3 (partial vs. not_supported rubric) and M2 (cited_for scope).

Regressions for the V4.9 review: models answered not_supported although part of
the cited content was supported (rubric did not define the boundary), and every
co-cited reference was judged against the whole sentence.
"""

from unittest.mock import AsyncMock, patch

import pytest

from refcheck.llm.templates import render_template
from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.cascade import ensure_expanded
from refcheck.stages.verify_claims.layers import cited_for, layer_variables
from refcheck.stages.verify_claims.screen import build_screen_input
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables
from tests.unit.verify_fakes import make_claim, make_ctx

_SENTENCE = "Patches deliver drug D locally and avoid systemic toxicity."


def _claim(part: str) -> Claim:
    return make_claim(_SENTENCE, co_cited=2).model_copy(update={"cited_for": part})


@pytest.mark.parametrize("template", ["verify_claim", "judge_claim", "verify_claim_strict",
                                      "judge_claim_strict"])
def test_rubric_defines_the_partial_not_supported_boundary(template: str) -> None:
    system = render_template(template, system_variables())
    assert "NONE of the content this reference is cited for is supported" in system
    assert "at least one substantive element" in system
    assert ("If at least one element is stated, the verdict is partially_supported or "
            "supported") in system
    # ...but the supported/partial boundary stays strict (oversimplification is a problem)
    assert "answer supported ONLY if every element is stated" in system
    assert "Scope and certainty words count here" in system
    assert "problem_type overgeneralized, quote P1 (supports)" in system
    assert "not HOW strictly" in system
    # synthetic boundary examples: partial (compound), not_supported, co-cited part
    assert "compound_part_only" in system and "so NOT not_supported" in system
    assert "None of the cited content is stated" in system
    assert 'CITED FOR: "avoid systemic toxicity"' in system
    # schema field names unchanged; never a field called "reasoning"
    strict_fields = ('"states"', '"dismissed"', '"guard"')  # V5.6 strict clearance only
    for field in ('"verdict"', '"severity"', '"problem_type"', '"confidence"', '"quotes"',
                  '"explanation"', '"missing"', '"partial_type"', '"unsupported_elements"',
                  '"benign_notes"', *strict_fields):
        assert (field in system) is (template.endswith("_strict") or field not in strict_fields)
    assert '"reasoning"' not in system


@pytest.mark.parametrize("template", ["verify_claim_strict", "judge_claim_strict"])
def test_quote_and_clearance_rules_v56(template: str) -> None:
    system = render_template(template, system_variables())
    # E2/E4: each quote says what it states; context-only quotes are not evidence
    assert "Quote the finding" in system and "only gives context" in system
    assert "List each element no quote states" in system
    # E1 + figure panels (P-CREDIT passes the panel text as CITED FOR)
    assert "figure-panel description adapted from the source" in system
    assert "donor→recipient direction" in system
    assert "the title or author block is never evidence" in system
    # L2: no clearance without a quote; wording/framing never clears these elements
    assert "No quote, no clearance" in system and "exact verbatim quote (5+ words)" in system
    assert "Wording, framing or a secondary report never clears a time frame" in system


def test_judge_system_prompt_repeats_the_boundary_check() -> None:
    system = render_template("judge_claim", system_variables())
    assert "before answering not_supported, check every substantive element" in system


@pytest.mark.parametrize("template", ["verify_claim", "judge_claim"])
def test_cited_for_part_is_what_the_model_judges(template: str) -> None:
    ctx = make_ctx(_claim("avoid systemic toxicity [4]"))
    user = render_template(template, layer_variables(ctx.claim, ctx, ctx.pack, "standard"))
    assert "CITED FOR (judge this part): avoid systemic toxicity\n" in user  # marker removed
    assert f"Citing sentence: {_SENTENCE}" in user and "other references may support" in user
    assert "CLAIM TO CHECK" not in user
    assert user.index("[P1]") < user.index("CITED FOR")


@pytest.mark.parametrize("part", ["", _SENTENCE, _SENTENCE.rstrip(".") + " [1]"])
def test_whole_sentence_scope_keeps_claim_to_check(part: str) -> None:
    ctx = make_ctx(_claim(part))
    assert cited_for(ctx.claim, ctx.claim_text) == ""
    user = render_template("verify_claim", layer_variables(ctx.claim, ctx, ctx.pack, "standard"))
    assert f"CLAIM TO CHECK: {_SENTENCE}" in user and "CITED FOR" not in user


def test_screen_input_uses_the_cited_part_with_sentence_as_context() -> None:
    narrowed = build_screen_input(make_ctx(_claim("avoid systemic toxicity")))
    assert narrowed.startswith("CLAIM (from an unpublished manuscript; citation markers "
                               "removed): avoid systemic toxicity\nFULL SENTENCE")
    assert _SENTENCE in narrowed
    whole = build_screen_input(make_ctx(_claim("")))
    assert whole.startswith(f"CLAIM (from an unpublished manuscript; citation markers "
                            f"removed): {_SENTENCE}\nCONTEXT (previous sentence")
    assert "FULL SENTENCE" not in whole


async def test_expanded_retrieval_leads_with_the_cited_part() -> None:
    ctx = make_ctx(_claim("avoid systemic toxicity"))
    ctx.expanded = None
    fake = AsyncMock(return_value=ctx.pack)
    with patch("refcheck.stages.verify_claims.cascade.expanded_pack", fake):
        await ensure_expanded(ctx, None)
    assert fake.await_args is not None
    assert fake.await_args.args[0] == f"avoid systemic toxicity {_SENTENCE}"
