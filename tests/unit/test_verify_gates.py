"""Code gates, numeric checks and screen calibration loading (V5 cascade)."""

import json
from pathlib import Path

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds, load_thresholds
from refcheck.stages.verify_claims.gates import (
    extract_quantities,
    has_negation_cue,
    has_non_year_digits,
    numeric_mismatch,
    quality_ok,
    word_count,
)


class TestDigitsGate:
    @pytest.mark.parametrize("text", [
        "Exercise improves mood (Smith et al., 2010).",
        "Since the 1990s, obesity has increased [12].",
        "Exercise improves mood [3-5, 9].",
        "Statins lower cholesterol in 2019 cohorts.",
    ])
    def test_years_and_citation_markers_are_ignored(self, text: str) -> None:
        assert not has_non_year_digits(text)

    @pytest.mark.parametrize("text", [
        "Drug X reduced mortality by 30%.",
        "IL-6 rises after surgery.",
        "COVID-19 causes anosmia.",
        "The odds ratio was 2.5.",
    ])
    def test_quantitative_claims_have_digits(self, text: str) -> None:
        assert has_non_year_digits(text)


class TestNegationGate:
    @pytest.mark.parametrize("text", [
        "Drug X did not reduce mortality.", "There is no association.",
        "Mice without the gene survived.", "Treatment failed to improve survival.",
        "Unlike earlier reports, we found an effect.", "Neither dose worked.",
        "Cells cannot divide.", "Patients lacking the enzyme", "It doesn't work.",
    ])
    def test_negation_cues(self, text: str) -> None:
        assert has_negation_cue(text)

    def test_plain_claim_has_no_negation(self) -> None:
        assert not has_negation_cue("Exercise improves mood in older adults.")
        assert not has_negation_cue("Knowledge of notation matters.")  # 'not' inside a word


def test_word_count_and_quality() -> None:
    assert word_count("a b  c") == 3
    assert quality_ok("ok", 1.0)
    assert not quality_ok("no_sections", 0.6)
    assert not quality_ok("ok", 0.5)


class TestNumbers:
    def test_extract_skips_names_and_years(self) -> None:
        values = [q.text for q in extract_quantities(
            "In 2019, IL-6 fell by 30% in 1,200 CD4 cells (COVID-19) [12].")]
        assert values == ["30%", "1,200"]

    def test_mismatch_flagged(self) -> None:
        result = numeric_mismatch("Drug X reduced mortality by 30%.",
                                  ["a non-significant 12% reduction in mortality (p=0.08)"])
        assert result is not None
        assert result[0] == ["30%"]
        assert "12%" in result[1]

    def test_rounding_matches(self) -> None:
        assert numeric_mismatch("mortality fell by 30%", ["a 30.2% reduction"]) is None

    def test_different_kind_is_not_compared(self) -> None:
        # The claim's count has no plain-number counterpart in the quote.
        assert numeric_mismatch("30% fewer deaths in 500 patients", ["a 30.2% reduction"]) is None

    def test_no_numbers_no_flag(self) -> None:
        assert numeric_mismatch("Drug X works", ["Drug X reduced IL-6 by 40%"]) is None
        assert numeric_mismatch("Drug X cut deaths by 40%", ["Drug X works"]) is None


class TestCalibration:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        for name in ("REFCHECK_SCREEN_T_ACCEPT", "REFCHECK_SCREEN_ENABLED",
                     "REFCHECK_PRIVACY_PROFILE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("REFCHECK_SCREEN_CALIBRATION", str(tmp_path / "screen.json"))
        self.path = tmp_path / "screen.json"

    def test_defaults_without_file(self) -> None:
        t = load_thresholds()
        assert t == ScreenThresholds()
        assert t.t_accept == 0.97 and t.injection_max == 0.2 and t.enabled
        assert t.t_contra == 0.5 and t.t_topic == 0.5

    def test_file_values_and_policy(self) -> None:
        self.path.write_text(json.dumps({"t_accept": 0.985, "policy": {"t_contra": 0.3},
                                         "coverage": 0.41, "alpha": 0.03}))
        t = load_thresholds()
        assert t.t_accept == 0.985 and t.t_contra == 0.3 and t.t_topic == 0.5
        assert t.source == str(self.path)

    def test_auto_clear_flag_from_file(self) -> None:
        self.path.write_text(json.dumps({"t_accept": 1.0, "enabled": True, "auto_clear": False}))
        t = load_thresholds()
        assert t.enabled and not t.auto_clear
        assert ScreenThresholds().auto_clear

    def test_invalid_file_falls_back(self) -> None:
        self.path.write_text("{not json")
        assert load_thresholds().source == "default"
        self.path.write_text(json.dumps({"t_accept": 7}))
        assert load_thresholds().t_accept == 0.97

    def test_env_override_and_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_SCREEN_T_ACCEPT", "0.9")
        assert load_thresholds().t_accept == 0.9
        monkeypatch.setenv("REFCHECK_SCREEN_T_ACCEPT", "oops")
        assert load_thresholds().t_accept == 0.97
        monkeypatch.setenv("REFCHECK_SCREEN_ENABLED", "false")
        assert not load_thresholds().enabled

    def test_anthropic_only_disables_screen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
        assert not load_thresholds().enabled


def test_numeric_mismatch_accepts_a_figure_stated_right_around_the_quote() -> None:
    quotes = ["Drug X reduced mortality by 12%."]
    claim = "Drug X reduced mortality by 30% in elderly patients."
    assert numeric_mismatch(claim, quotes) is not None
    # near_text = the source text around the quotes (another arm of the quoted result)
    assert numeric_mismatch(claim, quotes, "Table 2: a 30.1% reduction in elderly.") is None
    assert numeric_mismatch(claim, quotes, "No such figure here.") is not None
    # names are never quantities on either side
    assert numeric_mismatch("α-1,3 linked sugars rose by 40%", ["sugars rose by 40%"]) is None
    assert numeric_mismatch("aged ≥65 years", ["aged Z65 years"]) is None
