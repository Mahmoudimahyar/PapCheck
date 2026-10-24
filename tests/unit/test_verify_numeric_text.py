"""Name-digit masking (numeric_text.py): names are never quantities, units always are."""

import pytest

from refcheck.stages.verify_claims.gates import extract_quantities, numeric_mismatch
from refcheck.stages.verify_claims.numeric_text import join_digit_groups, mask_name_digits
from refcheck.stages.verify_claims.source_numbers import numbers_missing_from_source, quantities


@pytest.mark.parametrize("text", [
    "IL-6", "CD4+", "alpha-1,3", "1,25-dihydroxy", "5-FU", "6-OHDA", "5-HT", "5-HT1A",
    "3-D", "2-D", "3-dimensional", "3-Dimensional", "3D",
])
def test_name_digits_are_masked(text: str) -> None:
    sentence = f"Gel G with {text} was used."
    assert quantities(sentence) == [] and extract_quantities(sentence) == []
    assert numbers_missing_from_source(sentence, "Unrelated text.") == []


@pytest.mark.parametrize(("text", "value"), [
    ("5 T", 5), ("37 C", 37), ("2-fold", 2), ("3 mm", 3), ("10-week", 10),
    (">=65 years", 65), ("a 7-T scanner", 7), ("kept at 37-C", 37), ("cooled to 10-K", 10),
    ("a 2-L flask", 2), ("a 50-HU threshold", 50), ("6-MV photons", 6),
    ("a 128-dimensional vector", 128), ("a 12-dimensional space", 12), ("a 3-d course", 3),
    ("at week-12", 12), ("the day-28 outcome", 28), ("a 24-HR urine", 24), ("15-ML tubes", 15),
    ("20-MG tablets", 20), ("a 30-HZ tone", 30), ("a 10-KG load", 10), ("a 2-TB disk", 2),
])
def test_quantities_stay_quantities(text: str, value: int) -> None:
    sentence = f"Gel G: {text}."
    assert [q.value for q in quantities(sentence)] == [value]
    assert [q.value for q in extract_quantities(sentence)] == [value]


def test_single_capital_after_a_digit_is_a_unit_not_a_name() -> None:
    assert mask_name_digits("a 7-T scanner and 5-HT") == "a 7-T scanner and x-HT"
    assert mask_name_digits("4-D flow and 5-D") == "x-D flow and 5-D"
    assert numbers_missing_from_source("imaged on a 7-T scanner", "imaged at 3 T") == ["7"]


def test_hyphenated_timepoints_are_figures_or_years() -> None:
    assert numeric_mismatch("Gel G worked at week-12.", ["Gel G worked at week-24."]) == (
        ["12"], ["24"])
    assert numbers_missing_from_source("Healing by day 28.", "healing by day-28") == []
    assert quantities("Gels made pre-2010 and mid-1990s.") == []  # years


@pytest.mark.parametrize("space", [" ", "\u2009", "\u202f", "\u00a0"])
def test_thousands_written_with_a_space_are_one_figure(space: str) -> None:
    source = f"In total 10{space}000 patients received grafts."
    assert numbers_missing_from_source("Over 10,000 patients received grafts.", source) == []
    assert numeric_mismatch("Over 10,000 patients received grafts.", [source]) is None
    assert [q.value for q in quantities(f"Over 10{space}000 patients.")] == [10000]


def test_a_plain_space_in_source_text_keeps_table_cells_too() -> None:
    row = "Cell counts 12 145 167 in three groups."
    assert join_digit_groups(row, plain_space=False) == row
    values = {q.value for q in quantities(row, source=True)}
    assert {12, 145, 167, 12145167} <= values  # the cells and the joined reading
    assert numbers_missing_from_source("A count of 145 cells was reached.", row) == []
