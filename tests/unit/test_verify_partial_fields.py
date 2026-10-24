"""Partial sub-type fields on results (taxonomy v1.1) and co-cited reference plumbing."""

import pytest

from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation
from refcheck.models.partial_types import GUARD_LABELS
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.cocited import MAX_COCITED, co_cited_map
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.partial_fields import partial_fields
from tests.unit.verify_fakes import layer, make_ctx, make_ref

_ON = ScreenThresholds()


def typed(lay: LayerResult, ptype: str = "none", elements: tuple[str, ...] = (),
          notes: tuple[str, ...] = (), problem: str = "none") -> LayerResult:
    assert lay.output is not None
    out = lay.output.model_copy(update={"partial_type": ptype, "problem_type": problem,
                                        "unsupported_elements": list(elements),
                                        "benign_notes": list(notes)})
    return lay.model_copy(update={"output": out})


def test_partial_uses_model_type_severity_and_names_the_element() -> None:
    lay = typed(layer("verifier", "partially_supported", severity="major"),
                "scope_overgeneralized", ("in humans",), ("overliteral_wording",))
    f = partial_fields("partially_supported", lay, [lay], "full_text", [])
    assert (f.partial_type, f.partial_severity) == ("scope_overgeneralized", "major")
    assert "('in humans')" in f.author_action and f.unsupported_elements == ["in humans"]
    # A benign note names no cleared element: never shown as a clearing on a partial.
    assert f.guards_applied == [] and f.notes == []


@pytest.mark.parametrize(("problem", "verdict", "expected"), [
    ("numeric_mismatch", "partially_supported", "specific_detail_mismatch"),
    ("overgeneralized", "partially_supported", "scope_overgeneralized"),
    ("none", "partially_supported", "missing_element"),
    ("none", "not_supported", "tangential_source"),
    ("none", "not_relevant", "tangential_source"),
    ("none", "contradicted", "specific_detail_mismatch"),
])
def test_untyped_layer_falls_back_to_the_legacy_map(problem: str, verdict: str,
                                                     expected: str) -> None:
    lay = typed(layer("verifier", verdict), problem=problem)
    f = partial_fields(verdict, lay, [lay], "full_text", [])
    assert f.partial_type == expected and f.partial_severity in ("minor", "major")


def test_abstract_only_absence_is_coverage_limited() -> None:
    lay = typed(layer("verifier", "partially_supported", severity="major"),
                "missing_element", ("the 12-month result",))
    f = partial_fields("partially_supported", lay, [lay], "abstract_only", [])
    assert (f.partial_type, f.partial_severity) == ("coverage_limited", "minor")
    assert f.author_action.startswith("Upload the full text")
    contra = typed(layer("verifier", "partially_supported", role_quote="contradicts"),
                   "specific_detail_mismatch")
    assert partial_fields("partially_supported", contra, [contra], "abstract_only",
                          []).partial_type == "specific_detail_mismatch"
    full = typed(layer("verifier", "partially_supported"), "coverage_limited")
    assert partial_fields("partially_supported", full, [full], "full_text",
                          []).partial_type == "missing_element"


def test_supported_with_cocited_share_gets_the_placement_note() -> None:
    lay = typed(layer("verifier"), notes=("cocited_share", "secondary_source"))
    f = partial_fields("supported", lay, [lay], "full_text", ["evidence_recheck"])
    assert f.partial_type is None and f.partial_severity is None
    assert f.guards_applied == ["evidence_recheck", "cocited_share"]
    assert f.author_action == GUARD_LABELS["cocited_share"][1] and len(f.notes) == 2


def test_softened_dispute_keeps_the_verifier_type_unless_shown_by_the_cross_check() -> None:
    verifier = typed(layer("verifier", "not_supported", role_quote="closest"),
                     "tangential_source", ("clears wound bacteria",))
    confirm_sup = typed(layer("confirm", "supported", provider="anthropic"))
    f = partial_fields("partially_supported", confirm_sup, [verifier, confirm_sup],
                       "full_text", [])
    assert f.partial_type == "tangential_source"
    confirm_part = typed(layer("confirm", "partially_supported", provider="anthropic"),
                         "certainty_overstated")
    missing = typed(layer("verifier", "not_supported", role_quote="closest"),
                    "missing_element", ("clears wound bacteria",))
    f = partial_fields("partially_supported", confirm_part, [missing, confirm_part],
                       "full_text", [])
    assert f.partial_type == "certainty_overstated"
    # V5.8 (subtype_rules.py): the verifier's tangential_source is kept on the weak partial
    f = partial_fields("partially_supported", confirm_part, [verifier, confirm_part],
                       "full_text", [])
    assert f.partial_type == "tangential_source"


def test_build_result_maps_fields_and_appends_guard_notes() -> None:
    ctx = make_ctx()
    lay = typed(layer("verifier", "partially_supported", severity="minor"),
                "missing_element", ("restored limb function",), ("author_framing_or_example",))
    out = CascadeOutcome(verdict="partially_supported", label_layer=lay, decided_by="verifier",
                         consensus_type="verifier", tier=2, layers=[lay],
                         layer_path=["verifier"])
    result = build_result(ctx, None, out, _ON, 1)
    assert (result.partial_type, result.partial_severity) == ("missing_element", "minor")
    assert result.unsupported_elements == ["restored limb function"]
    assert result.guards_applied == []  # benign notes clear only a supported verdict
    assert "Author framing / example:" not in result.reasoning
    assert "restored limb function" in result.author_action


def _claim(claim_id: int, ref_id: int, sentence: str, paragraph: int = 0) -> Claim:
    return Claim(id=claim_id, manuscript_text=sentence, reference_ids=[ref_id],
                 location=ClaimLocation(paragraph_index=paragraph, char_start=0, char_end=1))


def test_co_cited_map_groups_claims_of_one_sentence() -> None:
    sentence = "Mesh is used in cranial repair [1] and orbital floors [2]."
    claims = [_claim(1, 1, sentence), _claim(2, 2, sentence), _claim(3, 3, "Other text [3]."),
              _claim(4, 4, sentence, paragraph=5)]
    refs = {1: make_ref(1, title="Cranial mesh"),
            2: make_ref(2, title="Orbital mesh", abstract_text="Orbital floors were repaired."),
            3: make_ref(3), 4: make_ref(4, title="Same text, other paragraph")}
    out = co_cited_map(claims, refs)
    assert [(c.number, c.title, c.abstract) for c in out[(1, 1)]] == [
        (2, "Orbital mesh", "Orbital floors were repaired.")]
    assert [c.number for c in out[(2, 2)]] == [1] and out[(2, 2)][0].abstract is None
    assert (3, 3) not in out and (4, 4) not in out


def test_co_cited_map_caps_and_skips_duplicates() -> None:
    sentence = "Many refs [1-6]."
    claims = [_claim(i, i, sentence) for i in range(1, 7)]
    refs = {i: make_ref(i, title=f"T{i}") for i in range(1, 7)}
    refs[2] = make_ref(2, title="dup of 1", duplicate_of=1)
    others = co_cited_map(claims, refs)[(1, 1)]
    assert len(others) == MAX_COCITED and 2 not in [c.number for c in others]
    # The reverse direction too: ref 2 (a duplicate of 1) does not list ref 1.
    assert 1 not in [c.number for c in co_cited_map(claims, refs)[(2, 2)]]


@pytest.mark.parametrize(("verdict", "coverage", "expected"), [
    ("contradicted", "abstract_only", "specific_detail_mismatch"),
    ("not_supported", "abstract_only", "tangential_source"),
    ("not_relevant", "full_text", "tangential_source"),
])
def test_coverage_limited_is_never_a_negative_type(verdict: str, coverage: str,
                                                   expected: str) -> None:
    lay = typed(layer("verifier", verdict, role_quote="contradicts", severity="minor"),
                "coverage_limited", ("the 12-month result",))
    f = partial_fields(verdict, lay, [lay], coverage, [])
    assert (f.partial_type, f.partial_severity) == (expected, "major")
    assert not f.author_action.startswith("Upload the full text")


_ABSTRACT_180 = "We enrolled 180 patients and followed them for 2 years."


@pytest.mark.parametrize(("source", "expected", "severity"), [
    (_ABSTRACT_180, "specific_detail_mismatch", "major"),  # the abstract states another count
    ("Mortality fell in the treated group.", "coverage_limited", "minor"),  # merely absent
    ("", "specific_detail_mismatch", "major"),  # nothing to compare: keep the model's type
])
def test_abstract_only_specific_is_coverage_limited_only_when_merely_absent(
        source: str, expected: str, severity: str) -> None:
    lay = typed(layer("verifier", "partially_supported", severity="major"),
                "specific_detail_mismatch", ("240 patients",))
    f = partial_fields("partially_supported", lay, [lay], "abstract_only", [],
                       claim_part="Drug X lowered mortality in 240 patients.",
                       source_text=source)
    assert (f.partial_type, f.partial_severity) == (expected, severity)
