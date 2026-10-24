"""Unit-aware claim numbers vs. the whole source text (M13, synthetic text only)."""

import pytest

from refcheck.stages.verify_claims.source_numbers import numbers_missing_from_source, quantities


def test_quantities_keep_units_and_ignore_years_markers_and_names() -> None:
    found = [(q.text, q.value, q.unit) for q in quantities(
        "Gels reached 150 kPa and 1.8–120 kPa, less than 50% recovered, IL-6 and CD4 rose "
        "in 2019 [12] (3, 4) (Smith et al., 2020) in 1,200 patients.")]
    assert found == [("150 kPa", 150.0, "kpa"), ("1.8 kPa", 1.8, "kpa"),
                     ("120 kPa", 120.0, "kpa"), ("50%", 50.0, "%"),
                     ("1,200", 1200.0, "")]


def test_percent_words_and_micro_signs_are_unified() -> None:
    assert [q.unit for q in quantities("12 percent and 5 μg/mL and 5 µg/ml")] == \
        ["%", "µg/ml", "µg/ml"]


_SOURCE = ("Results. The gels were tested on page 150 with 120 samples. The modulus was "
           "1.8-12 kPa. About 30.2% of 1200 patients recovered by day 40; "
           "lesions were larger than 4 cm2.")


@pytest.mark.parametrize(("claim", "missing"), [
    ("Optimised gels reach 150 kPa for bone.", ["150 kPa"]),  # 150 only as a page number
    ("Only less than 50% of patients recover.", ["50%"]),
    ("Moduli of 1.8–12 kPa were reported.", []),  # unit carried over the source's range
    ("About 30% of patients recovered.", []),  # claim precision decides
    ("About 35% of patients recovered.", ["35%"]),
    ("Data from 1,200 patients.", []),
    ("Healing took 40 days.", []),  # time units count as plain numbers ("day 40")
    ("Lesions larger than 4 cm² were treated.", []),  # PDFs lose superscripts
    ("In 2018 the trial [7] enrolled patients (Lee et al., 2018).", []),
    ("Gels reach 150 KPA.", ["150 KPA"]),
])
def test_numbers_missing_from_source(claim: str, missing: list[str]) -> None:
    assert numbers_missing_from_source(claim, _SOURCE) == missing


def test_unit_matches_regardless_of_case() -> None:
    assert numbers_missing_from_source("reaches 150 kPa", "a modulus of 150 KPa") == []


def test_no_source_text_flags_nothing() -> None:
    assert numbers_missing_from_source("reaches 150 kPa", "   ") == []


@pytest.mark.parametrize("text", [
    "binds the α-1,3-galactose epitope", "1,25-dihydroxyvitamin D3 levels",
    "1α,25-dihydroxy analogues", "IL-6 and CD4+ T cells", "TGF-β1 and Th17 cells",
    "a 3D scaffold and a 3-D print", "5-HT and 5-fluorouracil", "β-1,4-glucan chains",
    "type-2 diabetes",
])
def test_digits_inside_names_are_not_quantities(text: str) -> None:
    assert quantities(text) == []
    assert numbers_missing_from_source(f"Gels with {text} were used.", "Unrelated text.") == []


@pytest.mark.parametrize(("claim", "source"), [
    ("Risk rises in patients aged ≥65 years.", "risk in patients aged  65 years"),  # dropped
    ("Risk rises in patients aged ≥65 years.", "risk in patients aged Z65 years"),  # mangled
    ("Risk rises in patients aged ≥ 65 years.", "aged ⩾65 years"),
    ("The effect was significant (p ≤ 0.05).", "significant (pr0.05)"),
    ("The effect was significant (p<0.05).", "significant (p r 0.05)"),
    ("Recovery in >50% of patients.", "recovery in ³50% of patients"),
    ("Pore size was 12 ± 3 µm.", "pores of 12 +/- 3 µm"),
    ("About ~30% recovered.", "approximately ∼30% recovered"),
])
def test_comparison_symbols_dropped_or_mangled_by_pdf_extraction(claim: str,
                                                                 source: str) -> None:
    assert numbers_missing_from_source(claim, source) == []


def test_mangled_glyphs_are_only_unglued_on_the_source_side() -> None:
    assert [q.text for q in quantities("an r2 of 0.8")] == ["0.8"]
    assert [q.text for q in quantities("aged Z65", source=True)] == ["65"]
    assert numbers_missing_from_source("aged 70 years", "aged Z65 years") == ["70"]
