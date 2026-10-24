"""Narrative citation-only fragments ("Lee et al. (2002).") join the sentence
they belong to instead of becoming an unverifiable claim of their own."""

from refcheck.models.citation import CitationInstance
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes
from refcheck.stages.detect_citations.sentence_splitter import (
    extract_sentence_context,
)

# A stray period cuts the narrative subject off its verb.
STRAY = (
    "Early studies first tested drugs given systemically. Lee et al. (2002).   "
    "Applied agent Q with nerve grafts in mice to raise fiber counts over "
    "untreated controls (Lee et al., 2002).  However, later work moved to local delivery."
)


def _sentence(text: str, marker: str) -> str:
    pos = text.index(marker)
    sent, _, _ = extract_sentence_context(text, pos, pos + len(marker))
    return sent


def _cits(text: str) -> list[CitationInstance]:
    return [c.model_copy(update={"reference_id": 7}) for c in detect_in_paragraph(text, 0, "R")]


class TestJoinsNextSentence:
    def test_stray_period_fragment_joins_the_subjectless_sentence(self) -> None:
        sent = _sentence(STRAY, "Lee et al. (2002)")
        assert sent.startswith("Lee et al. (2002).")
        assert "Applied agent Q" in sent
        assert "Early studies" not in sent
        assert "However" not in sent

    def test_both_markers_share_the_merged_sentence(self) -> None:
        cits = _cits(STRAY)
        assert {c.is_narrative for c in cits} == {True, False}
        assert len({c.sentence_text for c in cits}) == 1

    def test_no_unit_is_a_bare_citation(self) -> None:
        units = resolve_scopes(_cits(STRAY))
        assert units
        for unit in units:
            assert unit.claim_quality == "ok"
            assert "Applied agent Q" in unit.cited_for

    def test_no_break_space_in_et_al(self) -> None:
        text = STRAY.replace("Lee et al. (2002).", "Lee et al. (2002).")
        assert "Applied agent Q" in _sentence(text, "Lee et al. (2002)")

    def test_fragment_at_paragraph_start(self) -> None:
        text = "Lee and Kim (2010). Showed that agent Q shortened healing in rats."
        assert _sentence(text, "Lee and Kim").endswith("in rats.")

    def test_fragment_after_a_line_break_joins_its_own_line(self) -> None:
        text = "Previous paragraph ends here.\nLee et al. (2002). Used agent Q in mice."
        assert "Used agent Q" in _sentence(text, "Lee et al.")


class TestJoinsPreviousSentence:
    def test_next_sentence_with_a_subject(self) -> None:
        text = (
            "Agent Q shortened healing in rats. Lee et al. (2002). "
            "The hydrogel then released the drug for weeks."
        )
        sent = _sentence(text, "Lee et al.")
        assert sent.startswith("Agent Q shortened healing")
        assert "hydrogel" not in sent

    def test_participle_opener_is_not_a_subjectless_verb(self) -> None:
        text = (
            "Agent Q shortened healing in rats. Lee et al. (2002). "
            "Based on these data, the authors proposed local delivery."
        )
        assert _sentence(text, "Lee et al.").startswith("Agent Q")

    def test_adjective_opener_is_not_a_subjectless_verb(self) -> None:
        text = (
            "Agent Q shortened healing in rats. Lee et al. (2002). "
            "Limited data suggest a similar effect in humans."
        )
        assert _sentence(text, "Lee et al.").startswith("Agent Q")

    def test_fragment_ending_its_line_does_not_jump_the_break(self) -> None:
        text = "Agent Q shortened healing in rats. Lee et al. (2002).\nUsed agent Q in mice."
        sent = _sentence(text, "Lee et al.")
        assert sent.startswith("Agent Q")
        assert "Used agent Q" not in sent


class TestLongNarrativeName:
    """A name too long for the length rule ("Vandermeer et al." keeps 14 characters)."""

    _PREV = "Grafts survived longer in treated rats. "

    def test_back_reference_joins_the_next_sentence(self) -> None:
        for opener in ("They gave agent Q", "The authors gave agent Q", "In their study, agent Q"):
            text = f"{self._PREV}Vandermeer et al. (2002). {opener} for weeks."
            sent = _sentence(text, "Vandermeer")
            assert sent.startswith("Vandermeer et al. (2002).") and "agent Q" in sent

    def test_short_name_with_back_reference_joins_the_next_sentence(self) -> None:
        text = f"{self._PREV}Lee et al. (2002). They gave agent Q for weeks."
        assert _sentence(text, "Lee et al.").startswith("Lee et al. (2002). They gave")

    def test_otherwise_it_stays_out_of_the_previous_sentence(self) -> None:
        text = f"{self._PREV}Vandermeer et al. (2002). Agent Q was given for weeks."
        assert _sentence(text, "Vandermeer") == "Vandermeer et al. (2002)."
        assert _sentence(text, "Grafts") == self._PREV.strip()


class TestOrdinarySentencesUnchanged:
    def test_narrative_sentence_with_its_verb(self) -> None:
        text = "Agent Q shortened healing. Lee (2019) disagreed. Kim (2020) agreed with it."
        assert _sentence(text, "Lee (2019)") == "Lee (2019) disagreed."

    def test_parenthetical_group_still_joins_previous(self) -> None:
        text = "Agent Q shortened healing in rats. (Lee et al., 2002). Used agent Q."
        assert _sentence(text, "(Lee et al.").startswith("Agent Q")
