"""Figure credit lines ("Adapted from X et al.") and the panel text they close (V5.6).

A credit inside a figure legend is not a provenance-only claim: it says the panel
it closes ("(A) Islet grafts under the kidney capsule of diabetic mice ...")
depicts the source's work. When that panel text is found, the pair's CITED FOR
becomes "Figure panel adapted from this source: <panel>" so retrieval
(cascade.focus_query), the verifier, the cross-check and the adjudicator all judge
the panel content against the source; the claim's sentence and extracted text stay
as they are (display). Without panel text the credit stays provenance-only
(``provenance_only``): only the source's identity is checked. So does a credit whose
source is abstract-only (verifier_helpers.build_pair_context, ``without_panel``): an
abstract cannot show a panel's model, direction or colour keys.

* ``credit_panel(claim_text, paragraph, occurrence)`` -> the panel description, or
  None (not a credit, not in a legend, or the panel text is too short to judge);
* ``panel_claim(claim, occurrence)`` / ``with_credit_panels(claims)`` -> the claim(s)
  with that CITED FOR (idempotent); ``panel_of(claim)`` reads the panel back;
  ``without_panel(claim)`` undoes it;
* ``provenance_only(ctx)`` -> a credit line without panel text;
* ``figure_credit(ctx)`` -> any figure credit (judged on its panel or provenance only).
"""

from typing import TYPE_CHECKING

from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.credit_legend import (
    clip_panel,
    credit_positions,
    is_credit_line,
    panel_text,
)
from refcheck.stages.verify_claims.credit_position import (
    credit_needle,
    credit_occurrences,
    credit_text,
)

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.verifier_helpers import PairContext

__all__ = ["PANEL_PREFIX", "credit_panel", "figure_credit", "is_credit_line", "panel_claim",
           "panel_of", "provenance_only", "with_credit_panels", "without_panel"]

PANEL_PREFIX = "Figure panel adapted from this source: "


def credit_panel(claim_text: str, paragraph: str, occurrence: int | None = None) -> str | None:
    """The legend panel text a credit line closes (None if none).

    ``occurrence``: which of several identical credits in the paragraph this claim
    is (credit_position; out of range -> None, never another credit's panel);
    unknown -> the panels of all of them (each one was adapted from the same source).
    """
    if not is_credit_line(claim_text):
        return None
    positions = credit_positions(claim_text, paragraph)
    if occurrence is not None:
        positions = positions[occurrence:occurrence + 1] if occurrence >= 0 else []
    panels = list(dict.fromkeys(p for pos in positions if (p := panel_text(paragraph, pos))))
    if len(panels) < 2:
        return panels[0] if panels else None
    return clip_panel(". ".join(panels))


def panel_of(claim: Claim) -> str | None:
    """The panel text a prepared claim (``panel_claim``) is judged on, if any."""
    if claim.cited_for.startswith(PANEL_PREFIX):
        return claim.cited_for[len(PANEL_PREFIX):] or None
    return None


def panel_claim(claim: Claim, occurrence: int | None = None) -> Claim:
    """``claim`` judged on its legend panel (CITED FOR = the panel), else unchanged."""
    if panel_of(claim) is not None or not is_credit_line(credit_text(claim)):
        return claim
    panel = credit_panel(credit_needle(claim), claim.paragraph_text, occurrence)
    if panel is None:
        return claim
    return claim.model_copy(update={"cited_for": PANEL_PREFIX + panel})


def without_panel(claim: Claim) -> Claim:
    """A prepared credit claim back on provenance only: CITED FOR = its credit line (the
    extracted claim or sentence that is one; "" falls back to them), else unchanged."""
    if panel_of(claim) is None:
        return claim
    line = next((t for t in (claim.extracted_claim, claim.manuscript_text)
                 if is_credit_line(t)), "")
    return claim.model_copy(update={"cited_for": line})


def with_credit_panels(claims: list[Claim]) -> list[Claim]:
    """Every claim of a run prepared by ``panel_claim`` (repeated credits disambiguated)."""
    occurrences = credit_occurrences(claims)
    return [panel_claim(claim, occurrences.get(claim.id)) for claim in claims]


def provenance_only(ctx: "PairContext") -> bool:
    """A credit line verified on provenance only (no panel text to check)."""
    if ctx.credit_panel or panel_of(ctx.claim) is not None:
        return False
    return is_credit_line(ctx.claim.cited_for or ctx.claim_text)


def figure_credit(ctx: "PairContext") -> bool:
    """A figure credit line, whether judged on its panel text or on provenance only."""
    return bool(ctx.credit_panel) or panel_of(ctx.claim) is not None or provenance_only(ctx)
