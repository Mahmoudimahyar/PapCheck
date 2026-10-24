"""Deterministic sub-type corrections the models miss (V5.7 #11 bundle, extended in V5.8).

Each rule restates a taxonomy v1.1 rule (prompts/partial_taxonomy.json) on signals the
pipeline already has; none changes a verdict, an element or a model request. Measured
with a free offline cache replay on the gold DEV split (the test split held out); off
with REFCHECK_V57_DISABLE=11 like the rest of the #11 bundle.

Element adjudicator side (adjudicate_result.py):

* own share unsupported -> tangential_source (R6, ``own_share_unsupported``): on a full
  text, the shown partial is the cross-check's reading (label role "confirm": the
  verifier itself judged the citation negative or found no supporting quote), the
  element adjudicator (its own call, not the co-cited full-text union check) cleared
  elements ONLY as stated by another reference cited in the same sentence ("cocited")
  and every survivor is merely absent, overstated or a co-cited clearance whose quote
  failed - none "broadened" (the predicate for a narrower subject is
  scope_overgeneralized), "contradicted" (a different specific) or a failed claim that
  this source states it. This reference then states none of the checked elements: the
  citation belongs to the other reference(s), while the cross-check's side element
  keeps the verdict partial (a "weak partial").
* exclusive terms -> certainty_overstated (``exclusive_only``): every survivor is an
  absolute or exclusive term ("X alone", "the sole cause", "guarantees", "always",
  "exactly") the source contradicts or does not reach; the taxonomy types "X alone"
  as certainty_overstated, not unsupported_inference / specific_detail_mismatch.
* an unwitnessed specific (``unwitnessed_specific``): the cross-check typed the pair
  specific_detail_mismatch but every survivor is merely absent and none names a figure,
  so no specific is in question: the survivors' own type (missing_element) is used.

Shown-result side (partial_fields.py, ``corrected_type``):

* a cross-check partial keeps the routed verifier's tangential_source (the verifier
  found the core unsupported for every subject, with no supporting quote; the
  cross-check's side element makes it a weak partial, the taxonomy's own reading);
* a "not relevant" verdict softened to not_supported by a cross-check that found the
  predicate for a narrower subject (its type scope_overgeneralized) is typed scope (R6:
  "the same predicate for a narrower subject is scope", never tangential);
* a verifier layer without a taxonomy type (a re-check that gave only a legacy
  problem_type) inherits the latest earlier verifier run's genuine type instead of the
  legacy mapping (an explicit classification beats a mapped one).
"""

import re
from typing import TYPE_CHECKING

from refcheck.models.partial_types import is_genuine
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.adjudicate import LAYER as ADJUDICATOR_LAYER

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.adjudicate import Adjudication
    from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
    from refcheck.stages.verify_claims.layers import LayerResult

TANGENTIAL = "tangential_source"
CERTAINTY = "certainty_overstated"
SPECIFIC = "specific_detail_mismatch"
SCOPE = "scope_overgeneralized"
# The taxonomy's absolute / exclusive terms (certainty_overstated definition).
_EXCLUSIVE = re.compile(r"\b(alone|sole|solely|exclusive|exclusively|guarantee[sd]?|"
                        r"guaranteeing|ensures?|ensured|ensuring|eliminat(?:e|es|ed|ing)|"
                        r"always|exactly)\b", re.IGNORECASE)
# survivors that leave this reference's share unstated ("cocited": its quote failed)
_SHARE_SURVIVORS = frozenset({"absent", "overstated", "cocited"})
_DEGREE = frozenset({"contradicted", "overstated"})
_FIGURE = re.compile(r"\d")


def own_share_unsupported(adj: "Adjudication", label: "LayerResult",
                          abstract_only: bool) -> bool:
    """R6 on the adjudicator's decisions (module doc)."""
    cleared, surviving = adj.cleared, adj.surviving
    return v57.enabled(11) and not abstract_only and label.role == "confirm" \
        and adj.meta.layer == ADJUDICATOR_LAYER and bool(cleared) and bool(surviving) \
        and all(d.category == "cocited" for d in cleared) \
        and all(d.category in _SHARE_SURVIVORS for d in surviving)


def exclusive_only(surviving: list["ElementDecision"]) -> bool:
    """Every survivor is an absolute / exclusive term the source does not reach."""
    return v57.enabled(11) and bool(surviving) and all(
        d.category in _DEGREE and _EXCLUSIVE.search(d.element) for d in surviving)


def unwitnessed_specific(kept: str, surviving: list["ElementDecision"],
                         cross_check: bool) -> bool:
    """The cross-check's specific_detail_mismatch with only absent, figure-free survivors."""
    return v57.enabled(11) and cross_check and kept == SPECIFIC and bool(surviving) \
        and all(d.category == "absent" and not _FIGURE.search(d.element) for d in surviving)


def _last(layers: list["LayerResult"], role: str) -> "LayerResult | None":
    found = [lay for lay in layers if lay.role == role and lay.axis is not None]
    return found[-1] if found else None


def _verifier_tangential(label: "LayerResult", layers: list["LayerResult"]) -> bool:
    routed = _last(layers, "verifier")
    return label.role == "confirm" and routed is not None and routed.output is not None \
        and routed.verdict == "not_supported" and routed.output.partial_type == TANGENTIAL \
        and not routed.quotes("supports")


def _narrower_subject(verdict: str, layer: "LayerResult",
                      layers: list["LayerResult"]) -> bool:
    confirm = _last(layers, "confirm")
    return verdict == "not_supported" and layer.verdict == "not_relevant" \
        and confirm is not None and confirm.output is not None \
        and confirm.axis == "positive" and confirm.output.partial_type == SCOPE


def inherited_type(layer: "LayerResult", layers: list["LayerResult"]) -> str | None:
    """The latest earlier verifier run's genuine type for an untyped verifier layer."""
    if layer.role != "verifier" or layer.output is None or is_genuine(layer.output.partial_type):
        return None
    earlier = layers[:layers.index(layer)] if layer in layers else []
    typed = [lay.output.partial_type for lay in earlier
             if lay.role == "verifier" and lay.output is not None
             and is_genuine(lay.output.partial_type)]
    return typed[-1] if typed else None


def corrected_type(genuine: str, verdict: str, layer: "LayerResult | None",
                   layers: list["LayerResult"]) -> str:
    """The shown result's type after the partial_fields-side rules (module doc)."""
    if not v57.enabled(11) or layer is None:
        return genuine
    if verdict == "partially_supported" and _verifier_tangential(layer, layers):
        return TANGENTIAL
    if _narrower_subject(verdict, layer, layers):
        return SCOPE
    return inherited_type(layer, layers) or genuine
