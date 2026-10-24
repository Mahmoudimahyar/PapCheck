"""V5.7 #5: the co-cited union check's loose about-check, only for EXACT quotes."""

import pytest

from refcheck.models.adjudication import CocitedCheck
from refcheck.stages.verify_claims.cocited_union_pack import UnionSource
from refcheck.stages.verify_claims.cocited_union_rules import decide_union
from refcheck.stages.verify_claims.retriever import EvidencePack, Passage

TEXT = ("Zwitterionic coatings reduce the foreign body reaction (FBR) by decreasing "
        "fibrosis around alginate capsules in rats.")
QUOTE = "Zwitterionic coatings reduce the foreign body reaction (FBR) by decreasing fibrosis"


def _sources() -> list[UnionSource]:
    pack = EvidencePack(passages=[Passage(id="R2-P1", unit_idx=1, section="Results",
                                          text=TEXT)],
                        coverage="full_text", total_tokens=30, retrieval_version="test")
    return [UnionSource(number=2, title="Coatings in rats", pack=pack)]


def _check(quote: str) -> CocitedCheck:
    return CocitedCheck(element="x", category="cocited", passage_id="R2-P1", quote=quote,
                        note="Reference 2 states it.")


@pytest.mark.parametrize(("element", "cleared"), [
    ("FBR reduction goal", True),  # meta word dropped, abbreviation expanded
    ("lower fibrotic overgrowth of capsules in pigs", False),  # too little overlap
])
def test_loose_about_check_on_an_exact_quote(element: str, cleared: bool) -> None:
    assert decide_union(element, _check(QUOTE), _sources()).cleared is cleared


def test_a_non_exact_quote_needs_the_strict_check() -> None:
    near = "Zwitterionic coatings lower the foreign body reaction (FBR) by decreasing fibrosis"
    assert not decide_union("FBR reduction goal", _check(near), _sources()).cleared


def test_switch_off_restores_the_strict_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "5")
    assert not decide_union("FBR reduction goal", _check(QUOTE), _sources()).cleared
