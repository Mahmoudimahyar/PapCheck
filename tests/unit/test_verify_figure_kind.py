"""An abstract that states a claim's figure differently is a mismatch, not mere absence.

Synthetic text only (figure_kind.py, source_numbers.figures_only_absent).
"""

import pytest

from refcheck.stages.verify_claims.figure_kind import (
    label_before,
    normalize_word,
    nouns_around,
)
from refcheck.stages.verify_claims.partial_fields import partial_fields
from refcheck.stages.verify_claims.source_numbers import figures_only_absent
from tests.unit.verify_fakes import layer


@pytest.mark.parametrize(("claim", "source", "absent"), [
    ("Drug X lowered mortality (HR 0.72).", "Drug X lowered mortality (HR 0.85).", False),
    ("Drug X was tested in 240 patients.", "We treated 180 adult patients.", False),
    ("The effect was significant (p < 0.001).", "The effect was significant (p = 0.03).",
     False),
    ("Patients aged 65 years were enrolled.", "Patients aged 58 yr were enrolled.", False),
    ("Healing took 40 days.", "Wounds healed by day 28.", False),
    ("Healing took 40 days.", "Wounds healed in 28 d.", False),
    ("Drug X was tested in 240 patients.", "Mortality fell in the treated group.", True),
    ("Drug X lowered mortality (HR 0.72).", "We enrolled 180 patients.", True),
    ("Drug X was tested in 240 patients.", "Gel Y was tested in 12 mice.", True),
])
def test_figures_only_absent(claim: str, source: str, absent: bool) -> None:
    assert figures_only_absent(claim, source) is absent


def test_labels_nouns_and_abbreviations() -> None:
    assert label_before("mortality (HR ", 14) == "hr"
    assert label_before("significant (p <= ", 18) == "p"
    assert label_before("tested in ", 10) == ""  # ordinary words are never labels
    text = "in 180 adult patients were"
    assert nouns_around(text, 3, 6) == ["adult", "patient"]
    assert nouns_around("by day 28.", 7, 9) == ["day"]
    assert [normalize_word(w) for w in ("yrs", "Years", "d", "days", "class")] == \
        ["year", "year", "day", "day", "class"]


@pytest.mark.parametrize(("claim", "source"), [
    ("Drug X lowered mortality (HR 0.72).", "Drug X lowered mortality (HR 0.85, 95% CI 0.7-0.9)."),
    ("Drug X was tested in 240 patients.", "Drug X was tested in 180 adult patients."),
])
def test_abstract_stating_another_figure_keeps_the_mismatch(claim: str, source: str) -> None:
    lay = layer("verifier", "partially_supported", severity="major")
    assert lay.output is not None
    lay = lay.model_copy(update={"output": lay.output.model_copy(update={
        "partial_type": "specific_detail_mismatch", "unsupported_elements": ["the figure"]})})
    f = partial_fields("partially_supported", lay, [lay], "abstract_only", [],
                       claim_part=claim, source_text=source)
    assert (f.partial_type, f.partial_severity) == ("specific_detail_mismatch", "major")
    assert not f.author_action.startswith("Upload the full text")
