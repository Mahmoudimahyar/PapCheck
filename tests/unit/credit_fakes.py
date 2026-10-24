"""Synthetic figure legends and credit-line claims for the V5.6 credit-panel tests."""

from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation

PANEL_A = ("(A) Fluorescence images of a donor-to-recipient mouse skin graft treated with a "
           "single depot injection, showing release over 30 days.")
PANEL_B = ("(B) Schematic of antibody-coated particles homing to the draining lymph nodes of "
           "the graft recipients.")
PANEL_C = ("(C) Serum drug levels after one injection with or without an inflammatory "
           "challenge on day 5 (**P < 0.01).")
TITLE = "Figure 2: Local delivery strategies for graft protection."
ROE = "Adapted from Roe et al. (2019)."
POE = "Reproduced with permission from Poe et al. (2020), Copyright 2020 Elsevier."
LEGEND = f"{TITLE} {PANEL_A} {ROE} {PANEL_B} {POE} {PANEL_C} {ROE} This picture was drawn."


def strip(panel_sentence: str) -> str:
    """A panel sentence as credit_panel returns it (no closing period, no legend
    statistics such as PANEL_C's "(**P < 0.01)": legend_boilerplate.py)."""
    return panel_sentence.replace(" (**P < 0.01)", "").rstrip(".")


def credit_claim(claim_id: int = 1, sentence: str = ROE, paragraph: str = LEGEND,
                 base: int | None = None, nth: int = 0, ref_id: int = 1) -> Claim:
    """A credit-line claim; ``base`` = offset of ``paragraph`` in the detector paragraph.

    ``nth``: which occurrence of ``sentence`` the claim's marker sits in (its char_start
    is that occurrence's offset + ``base``, like the detector's marker offset).
    """
    location = None
    if base is not None:
        start = -1
        for _ in range(nth + 1):
            start = paragraph.index(sentence, start + 1)
        marker = start + len("Adapted from ") + base
        location = ClaimLocation(paragraph_index=7, char_start=marker, char_end=marker + 20)
    cited_for = sentence.split(" (")[0].rstrip(".")
    return Claim(id=claim_id, manuscript_text=sentence, extracted_claim=sentence,
                 cited_for=cited_for, paragraph_text=paragraph, reference_ids=[ref_id],
                 location=location)
