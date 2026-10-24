"""V5.7 #14 (experimental, REFCHECK_SUBJECT_PREPEND=on): subjectless cited_for.

Regression pattern: "In short, tents act as shelters (R1), tackling heavy rainfall
(R2), ..." cites R2 for "tackling heavy rainfall"; the agent ("tents") is in R1's
clause, so a verifier judges "heavy rainfall is a problem".
Synthetic text only.
"""

import pytest

from refcheck.models.citation import VerificationUnit
from refcheck.stages.detect_citations.cited_subject import (
    JOINER,
    sentence_subject,
    verb_initial,
    with_subject,
)
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes

BARRIERS = ("In short, tents act as shelters (Hale et al., 2017), tackling "
            "heavy rainfall (Mann et al., 2016), and cold drafts (Ames et al., 2019).")


def _units(text: str) -> list[VerificationUnit]:
    cits = detect_in_paragraph(text, para_idx=0, section="Introduction")
    return resolve_scopes([c.model_copy(update={"reference_id": i})
                           for i, c in enumerate(cits, start=1)])


def _cited(text: str, marker: str) -> str:
    return next(u.cited_for for u in _units(text) if u.citation_marker.startswith(marker))


@pytest.fixture
def subject_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_SUBJECT_PREPEND", "on")


class TestSwitch:
    def test_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REFCHECK_SUBJECT_PREPEND", raising=False)
        assert _cited(BARRIERS, "(Mann") == "tackling heavy rainfall"

    @pytest.mark.usefixtures("subject_on")
    def test_disable_list_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_V57_DISABLE", "14")
        assert _cited(BARRIERS, "(Mann") == "tackling heavy rainfall"


@pytest.mark.usefixtures("subject_on")
class TestPrepended:
    def test_participle_clause_gets_the_agent(self) -> None:
        assert _cited(BARRIERS, "(Mann") == f"tents{JOINER}tackling heavy rainfall"

    def test_coordinated_predicate_gets_the_subject(self) -> None:
        got = _cited("Tacrolimus is nephrotoxic [3] and increases infection risk [4].", "[4]")
        assert got == f"Tacrolimus{JOINER}increases infection risk"

    def test_clauses_with_a_subject_and_list_items_unchanged(self) -> None:
        assert _cited(BARRIERS, "(Hale") == "In short, tents act as shelters"
        assert _cited(BARRIERS, "(Ames") == "cold drafts"

    def test_whole_sentence_is_never_prefixed(self) -> None:
        unit = _units("Hydrogels reduce scarring (Smith et al., 2020).")[0]
        assert unit.cited_for == unit.scope_text


class TestNotPrepended:
    @pytest.mark.parametrize("clause,sentence", [
        ("making them good carriers",  # anaphoric subject
         "These properties allow gels to mimic tissue, making them good carriers"),
        ("promote regulatory T cells",  # coordinated with an infinitive, not "allows"
         "Local delivery allows gels to build a niche or promote regulatory T cells"),
        ("encapsulating islets improves survival",  # gerund subject with its own verb
         "Gels lower IL-6, and encapsulating islets improves survival"),
        ("signaling defects",  # an -ing noun
         "Gels address hypoxia, signaling defects"),
        ("increases in IL-6",  # a plural noun, not a verb
         "Gels lower IL-6, increases in IL-6"),
    ])
    def test_unchanged(self, clause: str, sentence: str) -> None:
        assert with_subject(clause, sentence) == clause


class TestHelpers:
    def test_subject_skips_frame_and_adverbs(self) -> None:
        found = sentence_subject("In mice, hydrogels also act as barriers")
        assert found is not None and (found.text, found.verb) == ("hydrogels", "act")

    @pytest.mark.parametrize("sentence", [
        "Combining these features",  # opens with a verb / no tensed verb
        "They reduce scarring",  # pronoun
        "Hydrogel scaffolds",  # no verb at all
    ])
    def test_no_subject(self, sentence: str) -> None:
        assert sentence_subject(sentence) is None

    def test_verb_initial(self) -> None:
        assert verb_initial("thereby reducing graft loss")
        assert verb_initial("improve islet survival")
        assert not verb_initial("including colon cancer")
        assert not verb_initial("hydrogels improve survival")
