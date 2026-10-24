"""The partial-verdict taxonomy is rendered into the rubric from partial_taxonomy.json,
and the co-cited references of the sentence are shown to the verifier (V5.4)."""

import json
from pathlib import Path

import pytest

from refcheck.llm.templates import render_template
from refcheck.models.partial_types import GENUINE_PRECEDENCE
from refcheck.stages.verify_claims.cocited import COCITED_ABSTRACT_TOKENS, co_cited_ref
from refcheck.stages.verify_claims.layers import layer_variables
from refcheck.stages.verify_claims.source_models import estimate_tokens
from refcheck.stages.verify_claims.taxonomy_prompt import (
    TAXONOMY_PATH,
    assign_sentence,
    definition_head,
    system_variables,
    taxonomy_prompt,
)
from tests.unit.verify_fakes import make_claim, make_ctx

_TAXONOMY = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
_TYPES = {t["id"]: t for t in _TAXONOMY["types"]}


@pytest.mark.parametrize("template", ["verify_claim", "judge_claim"])
def test_rubric_renders_guards_rules_and_genuine_types_from_the_json(template: str) -> None:
    system = render_template(template, system_variables())
    # guards in order; evidence_gap is the pipeline's re-check (model lists elements)
    order = [system.index(f"G{i} {g}") for i, g in enumerate(
        ("evidence_gap", "cocited_share", "author_framing_or_example", "overliteral_wording"),
        start=1)]
    assert order == sorted(order) and '"unsupported_elements"' in system
    assert " > ".join(GENUINE_PRECEDENCE) in system
    for type_id in GENUINE_PRECEDENCE:  # decision rule + first synthetic example, verbatim
        assert assign_sentence(_TYPES[type_id]["decision_rule"]) in system
        assert _TYPES[type_id]["examples"][0] in system
    for rule in ("R1", "R3", "R4", "R5", "R6", "R7"):
        assert f"{rule} {_TAXONOMY['rules_v1_1'][rule]}" in system
    assert "R2 " not in system  # eval labelling rule only
    assert "coverage_limited" in system and "benign_notes" in system
    # the V5.3 boundaries and decision order stay
    assert "answer supported ONLY if every element is stated" in system
    assert "unless a guard below clears it" in system


def test_rendering_follows_the_taxonomy_file(tmp_path: Path) -> None:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    for item in data["types"]:
        if item["id"] == "missing_element":
            item["examples"][0] = "Synthetic marker example ZZQ."
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    system = render_template("verify_claim", {"section": "system",
                                              "taxonomy": taxonomy_prompt(path)})
    assert "Synthetic marker example ZZQ." in system


def test_condensing_helpers() -> None:
    assert definition_head("A thing is wrong: details follow.") == "A thing is wrong."
    assert definition_head("No split here") == "No split here."
    rule = "Split it. After that, assign if X holds. Otherwise not."
    assert assign_sentence(rule) == "After that, assign if X holds."
    entry = taxonomy_prompt().genuine[GENUINE_PRECEDENCE.index("missing_element")]
    assert entry.severity == "minor"  # the R7 aside is covered by rule R7


def test_taxonomy_addition_stays_compact() -> None:
    with_taxonomy = render_template("verify_claim", system_variables())
    without = render_template("verify_claim", {"section": "system"})
    assert "# Partial verdicts" not in without
    assert (len(with_taxonomy) - len(without)) / 4 < 2100  # ~1,800 o200k tokens


@pytest.mark.parametrize("template", ["verify_claim", "judge_claim"])
def test_co_cited_block_shows_titles_and_abstracts(template: str) -> None:
    ctx = make_ctx(make_claim(co_cited=3))
    ctx.co_cited = [co_cited_ref(7, "Mesh for orbital floors", "Orbital floor repair " * 300),
                    co_cited_ref(9, "Cost of composites", None)]
    user = render_template(template, layer_variables(ctx.claim, ctx, ctx.pack, "standard"))
    block = user[user.index("CO-CITED REFERENCES (same sentence"):user.index("Claim type:")]
    assert "[7] Mesh for orbital floors — Abstract: Orbital floor repair" in block
    assert "[9] Cost of composites (title only)" in block
    assert len(block) < 1400  # abstract truncated to ~250 tokens (COCITED_ABSTRACT_TOKENS)
    assert estimate_tokens(ctx.co_cited[0].abstract or "") <= COCITED_ABSTRACT_TOKENS + 1
    assert user.index("[P1]") < user.index("CO-CITED") < user.index("CLAIM TO CHECK")


def test_no_co_cited_block_without_co_cited_refs() -> None:
    ctx = make_ctx(make_claim(co_cited=2))
    user = render_template("verify_claim", layer_variables(ctx.claim, ctx, ctx.pack, "standard"))
    assert "CO-CITED REFERENCES" not in user and "cites 2 references together" in user


def test_recheck_pack_kind_is_named_in_the_prompt() -> None:
    ctx = make_ctx()
    user = render_template("verify_claim", layer_variables(ctx.claim, ctx, ctx.pack, "recheck"))
    assert "plus passages searched for each element in question" in user
