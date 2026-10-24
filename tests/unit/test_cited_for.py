"""M2 (producer): each reference is judged on the clause it is cited for.

Regression: scope_resolver gave every citation of a sentence the whole
sentence, so in "A does X (Ref1) and Y (Ref2)." Ref1 was judged on Y too.
extracted_claim must stay the whole scope; cited_for narrows it.
"""

from refcheck.models.citation import VerificationUnit
from refcheck.services.citation_converter import units_to_claims
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes


def _units(text: str) -> list[VerificationUnit]:
    """Detect citations in one paragraph, give each a distinct reference id."""
    cits = detect_in_paragraph(text, para_idx=0, section="Introduction")
    mapped = [c.model_copy(update={"reference_id": i}) for i, c in enumerate(cits, start=1)]
    return resolve_scopes(mapped)


def _by_marker(units: list[VerificationUnit]) -> dict[str, str]:
    return {u.citation_marker: u.cited_for for u in units}


class TestInlineMarkersNarrowScope:
    def test_two_clauses_two_references(self) -> None:
        units = _units(
            "Alginate gels reduce fibrosis (Smith et al., 2020) and improve islet "
            "survival (Jones et al., 2021).",
        )
        got = _by_marker(units)
        assert got["(Smith et al., 2020)"] == "Alginate gels reduce fibrosis"
        assert got["(Jones et al., 2021)"] == "improve islet survival"
        # extracted_claim (scope) is still the whole sentence for both
        assert all("fibrosis" in u.scope_text and "survival" in u.scope_text for u in units)

    def test_list_of_clauses_with_compound_group(self) -> None:
        units = _units(
            "At their simplest, gels act as physical barriers (Hale et al., 2017), tackling "
            "mechanical instability (Mann et al., 2016), weak blood supply or hypoxia "
            "(Hoyt et al., 2022; Bain et al., 2023a), and cell leakage (Mann et al., 2016).",
        )
        got = {(u.citation_marker, u.char_start): u.cited_for for u in units}
        clauses = sorted(set(got.values()))
        assert "At their simplest, gels act as physical barriers" in clauses
        assert "tackling mechanical instability" in clauses
        assert "weak blood supply or hypoxia" in clauses
        assert "cell leakage" in clauses
        hoyt_bain = [u.cited_for for u in units if u.citation_marker.startswith(("(Hoyt", "(Bain"))]
        assert hoyt_bain == ["weak blood supply or hypoxia"] * 2

    def test_end_group_covers_text_after_last_inline_marker(self) -> None:
        units = _units(
            "Gels have tunable stiffness (Pike et al., 2021), and good "
            "cell tolerance (Wade et al., 2019c).",
        )
        assert _by_marker(units)["(Wade et al., 2019c)"] == "good cell tolerance"

    def test_single_end_marker_covers_whole_sentence(self) -> None:
        units = _units("Hydrogels are biocompatible (Smith et al., 2020).")
        assert units[0].cited_for == units[0].scope_text == "Hydrogels are biocompatible"

    def test_mid_sentence_marker_before_contrast_clause(self) -> None:
        units = _units(
            "Alginate degrades in weeks (Lee et al., 2019), but PEG persists for months.",
        )
        assert units[0].cited_for == "Alginate degrades in weeks"

    def test_numbered_brackets(self) -> None:
        units = _units("Tacrolimus is nephrotoxic [3] and increases infection risk [4].")
        got = _by_marker(units)
        assert got["[3]"] == "Tacrolimus is nephrotoxic"
        assert got["[4]"] == "increases infection risk"


class TestNoFalseNarrowing:
    def test_marker_embedded_in_noun_phrase(self) -> None:
        units = _units("Hydrogels (Smith et al., 2020) are widely used for drug delivery.")
        assert units[0].cited_for == units[0].scope_text

    def test_markers_on_subjects_with_shared_predicate(self) -> None:
        """Never narrowed to the bare noun phrase: the shared predicate stays. V5.7 #10
        drops only the OTHER reference's subject (test_cited_for_positional.py)."""
        units = _units(
            "Alginate (Smith et al., 2020) and chitosan (Jones et al., 2021) both reduce "
            "graft inflammation.",
        )
        assert [u.cited_for for u in units] == [
            "Alginate both reduce graft inflammation", "chitosan both reduce graft inflammation"]

    def test_narrative_citation_keeps_its_scope(self) -> None:
        units = _units(
            "Lee et al. (2019) showed that gels persist for months, unlike older "
            "depots (Kerr et al., 2015).",
        )
        narrative = next(u for u in units if u.is_narrative)
        assert narrative.cited_for == narrative.scope_text
        assert narrative.cited_for.startswith("showed that gels persist")

    def test_example_noun_phrase_before_the_predicate_is_not_narrowed(self) -> None:
        """Integration review: "Hydrogels, e.g. alginate (Ref1), reduce ..." narrowed Ref1 to
        the noun phrase because only the sentence END was checked for a predicate."""
        units = _units(
            "Hydrogels, e.g. alginate (Smith et al., 2020), reduce rejection and improve "
            "graft survival (Jones et al., 2021; Brown et al., 2022).",
        )
        smith = next(u for u in units if u.citation_marker.startswith("(Smith"))
        assert smith.cited_for == smith.scope_text
        others = [u.cited_for for u in units if not u.citation_marker.startswith("(Smith")]
        assert others == ["reduce rejection and improve graft survival"] * 2

    def test_leading_context_marker_is_not_narrowed(self) -> None:
        units = _units(
            "In islet transplantation (Lee et al., 2019), hydrogels improve engraftment "
            "and reduce hypoxia (Smith et al., 2020).",
        )
        got = _by_marker(units)
        lee = next(u for u in units if u.citation_marker.startswith("(Lee"))
        assert lee.cited_for == lee.scope_text
        assert got["(Smith et al., 2020)"] == "hydrogels improve engraftment and reduce hypoxia"

    def test_list_items_followed_by_a_later_clause_are_still_narrowed(self) -> None:
        """A verb further on (after "and ..." or ";") does not belong to the list item."""
        units = _units(
            "Cargos include small molecules (Zane et al., 2021), proteins and cytokines "
            "(Mott et al., 2022; Mills et al., 2022), and cell or gene cargos "
            "(Lund et al., 2024); by controlling release, gels keep doses low (Kerr et al., 2019).",
        )
        lei = {u.cited_for for u in units if "Mott" in u.citation_marker}
        assert lei == {"proteins and cytokines"}
        assert [u.cited_for for u in units if u.citation_marker.startswith("(Lund")] == [
            "cell or gene cargos"]
        units = _units(
            "Tents act as shelters (Hale et al., 2017), tackling heavy rain or "
            "snow (Hoyt et al., 2022), and the loss of loose pegs "
            "(Mann et al., 2016).",
        )
        assert _by_marker(units)["(Hoyt et al., 2022)"] == "tackling heavy rain or snow"

    def test_verbless_list_items_are_still_narrowed(self) -> None:
        units = _units(
            "Gels address hypoxia (Hoyt et al., 2022), weak blood supply (Bain et al., 2023), "
            "and cell leakage (Mann et al., 2016).",
        )
        got = _by_marker(units)
        assert got["(Bain et al., 2023)"] == "weak blood supply"
        assert got["(Mann et al., 2016)"] == "cell leakage"

    def test_superscript_units_are_not_markers_in_author_year_text(self) -> None:
        units = _units(
            "Defects larger than 2 cm², which heal poorly, need grafts (Dunn et al., 2024).",
        )
        assert units[0].cited_for == units[0].scope_text


class TestPropagation:
    def test_converter_copies_cited_for_to_claim(self) -> None:
        units = _units(
            "Gels reduce fibrosis (Smith et al., 2020) and aid survival (Jones et al., 2021).",
        )
        claims = units_to_claims(units)
        assert [c.cited_for for c in claims] == ["Gels reduce fibrosis", "aid survival"]
        assert all(c.extracted_claim == units[0].scope_text for c in claims)

    def test_converter_defaults_cited_for_to_scope(self) -> None:
        unit = VerificationUnit(manuscript_text="S.", scope_text="S", citation_marker="[1]",
                                reference_id=1)
        assert units_to_claims([unit])[0].cited_for == "S"
