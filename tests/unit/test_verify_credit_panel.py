"""V5.6 L1: the legend panel text a figure credit line closes (synthetic legends only)."""

import pytest

from refcheck.stages.verify_claims.credit import credit_panel
from refcheck.stages.verify_claims.credit_legend import (
    PANEL_MAX_CHARS,
    credit_positions,
    is_credit_line,
    sentence_end,
)
from tests.unit.credit_fakes import LEGEND, PANEL_A, PANEL_B, PANEL_C, POE, ROE, strip


@pytest.mark.parametrize(("occurrence", "expected"), [
    (0, strip(PANEL_A)), (1, strip(PANEL_C)), (None, f"{strip(PANEL_A)}. {strip(PANEL_C)}")])
def test_repeated_credit_closes_its_own_panel(occurrence: int | None, expected: str) -> None:
    assert credit_panel(ROE, LEGEND, occurrence) == expected


def test_each_credit_closes_the_panel_since_the_last_label() -> None:
    assert credit_panel(POE, LEGEND) == strip(PANEL_B)
    assert credit_panel("Adapted from Roe et al", LEGEND, 1) == strip(PANEL_C)  # cited_for form


def test_out_of_range_occurrence_never_borrows_another_panel() -> None:
    assert credit_panel(POE, LEGEND, 1) is None
    assert credit_panel(ROE, LEGEND, -1) is None


def test_figure_title_is_never_part_of_the_panel() -> None:
    panel = credit_panel(ROE, LEGEND, 0) or ""
    assert "Local delivery strategies" not in panel and panel.startswith("(A) ")


@pytest.mark.parametrize(("first", "second"), [
    ("(a)", "(b)"), ("A)", "B)"), ("A.", "B."), ("Panel A:", "Panel B:"), ("a,", "b,"),
    ("(A, B)", "(C)"), ("(i)", "(ii)"),
])
def test_label_styles(first: str, second: str) -> None:
    legend = (f"Fig. 4. Hydrogel depots in two graft models. {first} Islet grafts in the kidney "
              f"capsule of diabetic mice stay normoglycaemic for 60 days. Adapted from Doe et al. "
              f"{second} Skin grafts on the dorsum of rats survive longer with the depot than "
              f"without it. Reprinted from ref. 12.")
    assert (credit_panel("Reprinted from ref. 12", legend) or "").startswith(second)
    assert (credit_panel("Adapted from Doe et al.", legend) or "").startswith(first)


def test_panel_mention_inside_a_sentence_does_not_split_the_panel() -> None:
    legend = ("Figure 3: Graft survival. (A) Survival curves of the graft groups. (B) Quantified "
              "graft area for the animals shown in (A), measured weekly by two observers. "
              "Adapted from Roe et al.")
    panel = credit_panel("Adapted from Roe et al.", legend) or ""
    assert panel.startswith("(B) Quantified") and panel.endswith("by two observers")


def test_unlabelled_panels_split_at_the_previous_credit() -> None:
    legend = ("Figure 1: Two delivery routes. Left: a subcutaneous depot next to the graft "
              "releasing the drug for weeks. Adapted from Roe et al. (2019). Right: particles "
              "carried to the draining lymph node after an intravenous injection. Adapted from "
              "Poe et al. (2020).")
    left = credit_panel("Adapted from Roe et al. (2019).", legend) or ""
    right = credit_panel("Adapted from Poe et al. (2020).", legend) or ""
    assert left.startswith("Left: a subcutaneous depot") and "Two delivery" not in left
    assert right.startswith("Right: particles") and right.endswith("intravenous injection")


def test_single_panel_legend_uses_the_text_after_the_title() -> None:
    legend = ("Figure 5. Immune niche around the implant. Macrophages surround the porous "
              "scaffold and switch to a repair phenotype within two weeks. Adapted from Roe "
              "et al.")
    panel = credit_panel("Adapted from Roe et al.", legend)
    assert panel == ("Macrophages surround the porous scaffold and switch to a repair "
                     "phenotype within two weeks")


def test_title_only_legend_is_too_short_to_judge() -> None:
    legend = "Figure 5. Immune niche around the implant. Adapted from Roe et al."
    assert credit_panel("Adapted from Roe et al.", legend) is None


def test_label_addressed_credit_returns_that_panel() -> None:
    legend = ("Figure 6: Two models. (a) Islet grafts in the kidney capsule of diabetic mice "
              "with the depot. (b) Skin grafts on the dorsum of rats with the depot over time. "
              "(a) Reprinted from ref. 12. (b) Reproduced from ref. 13.")
    assert (credit_panel("(a) Reprinted from ref. 12", legend) or "").startswith("(a) Islet")
    assert (credit_panel("(b) Reproduced from ref. 13", legend) or "").startswith("(b) Skin")


def test_windowed_legend_without_its_caption_still_has_labels() -> None:
    window = "…and the graft recipients. " + LEGEND.split("protection. ", 1)[1]
    assert credit_panel(POE, window) == strip(PANEL_B)


@pytest.mark.parametrize("paragraph", [
    "Hydrogels release drugs locally. Adapted from Roe et al. They also degrade slowly.",
    "",
])
def test_credit_outside_a_legend_has_no_panel(paragraph: str) -> None:
    assert credit_panel("Adapted from Roe et al.", paragraph) is None


def test_not_a_credit_line_has_no_panel() -> None:
    assert credit_panel("Hydrogels reduce fibrosis in mice.", LEGEND) is None
    assert credit_panel("Adapted from the protocol of Smith et al., cells were grown",
                        LEGEND) is None


def test_long_panel_is_capped_at_a_word_boundary() -> None:
    legend = "Figure 7: Title here. (A) " + "Graft cells were imaged daily. " * 80 \
        + "Adapted from Roe et al."
    panel = credit_panel("Adapted from Roe et al.", legend) or ""
    assert len(panel) <= PANEL_MAX_CHARS and panel.endswith("…")
    assert panel.startswith("(A) Graft cells")


def test_credit_positions_require_a_segment_start() -> None:
    text = "Cells were adapted from Roe et al. in culture. Adapted from Roe et al."
    assert credit_positions("Adapted from Roe et al.", text) == [text.rindex("Adapted")]


def test_sentence_end_skips_abbreviations() -> None:
    text = "Adapted from Roe et al. (2019). (B) Next panel."
    end = sentence_end(text, 0)
    assert end is not None and text[:end] == "Adapted from Roe et al. (2019)."


def test_credit_line_shape_is_shared_with_dispute() -> None:
    from refcheck.stages.verify_claims import dispute

    assert dispute.is_credit_line is is_credit_line
