"""M4: year-suffix references ("2018a/2018b", "2024a/b/c") must map exactly.

Regression for the V4.9 run: "(2018a)" references were parsed with
year=None and the mapper dropped the letter, so every "Doe et al.,
2018b" landed on 2018a and every "Wade et al., 2024c" on 2024a. All
reference strings below are synthetic.
"""

from refcheck.models.citation import CitationInstance
from refcheck.models.reference import Reference
from refcheck.services.citation_converter import units_to_claims
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.reference_mapper import map_citations_to_references
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes
from refcheck.stages.parse_docx.citation_detector import find_citations_in_text
from refcheck.stages.parse_docx.reference_extractor import parse_single_reference

_RAW = [
    "Doe, D., Orr, R., Lark, J., Dunn, A., et al. (2018a). Enzyme-triggered release of "
    "a model drug from a synthetic gel depot. Synth. Rep. 13, e0200001. doi: 10.1000/a.1",
    "Doe, D. V., Orr, R., Lark, J., Bly, Y., et al. (2018b). Repeated depot dosing "
    "lowers drug exposure in synthetic grafts. Synth. Transpl. 102, 1600–1610. "
    "doi: 10.1000/b.2",
    "Wade, Q., Holt, Y., Lund, L., et al. (2024a). Synthetic graft engineering: current "
    "progress and open problems. Front. Synth. 15. doi: 10.1000/fsyn.2024.111",
    "Wade, Q., Holt, Y., Lund, L., et al. (2024b). Synthetic graft engineering: current "
    "progress and open problems. Front. Synth. 15. doi: 10.1000/fsyn.2024.111",
    "Wade, Y., Holt, R., Ives, Y., and Moss, R. (2024c). Particle-linked shielding gel "
    "for donor grafts. Synth. Commun. 15, 5100. doi: 10.1000/c.3",
    "Sous, P. K., Dove, R., and Drake, T. (2022). Coated cell clusters evade rejection in "
    "model mice. Synth. J. Transpl. 22, 2500–2510. doi: 10.1000/d.4",
    "de Sousa, A. G., de Melo, J. D., and Bento, T. S. (2023). Matrix-derived "
    "hydrogels for tissue repair. Hydrogels 9, 100. doi: 10.1000/e.5",
]


def _refs() -> list[Reference]:
    refs = [parse_single_reference(i, raw) for i, raw in enumerate(_RAW, start=1)]
    # parse_manuscript() marks 4 as a duplicate of 3 (same DOI)
    refs[3] = refs[3].model_copy(update={"duplicate_of": 3})
    return refs


def _cit(author: str, year: str | None, authors: list[str] | None = None) -> CitationInstance:
    return CitationInstance(
        raw_marker=f"({author} et al., {year})", style="author_year_parenthetical",
        paragraph_index=0, char_start=0, char_end=10,
        authors=authors or [author], year=year,
    )


def _map(cit: CitationInstance, refs: list[Reference] | None = None) -> CitationInstance:
    return map_citations_to_references([cit], refs or _refs())[0]


class TestReferenceYearSuffix:
    def test_suffix_parsed_into_year_and_letter(self) -> None:
        refs = _refs()
        assert (refs[0].year, refs[0].year_suffix) == (2018, "a")
        assert (refs[1].year, refs[1].year_suffix) == (2018, "b")
        assert (refs[4].year, refs[4].year_suffix) == (2024, "c")
        assert (refs[5].year, refs[5].year_suffix) == (2022, None)

    def test_apa_authors_keep_initials_with_surname(self) -> None:
        refs = _refs()
        assert refs[2].authors[0] == "Wade, Q."
        assert refs[4].authors[0] == "Wade, Y."
        assert refs[4].authors[-1] == "Moss, R."


class TestSuffixMapping:
    def test_2018b_maps_to_2018b_not_first_author_match(self) -> None:
        assert _map(_cit("Doe", "2018b")).reference_id == 2
        assert _map(_cit("Doe", "2018a")).reference_id == 1

    def test_2024c_maps_to_other_first_author_with_same_surname(self) -> None:
        """Wade Y. 2024c is not Wade Q. 2024a even though both are "Wade, 2024"."""
        out = _map(_cit("Wade", "2024c"))
        assert out.reference_id == 5
        assert out.mapping_method == "exact_author_year"
        assert not out.mapping_ambiguous

    def test_2024a_and_2024b_map_to_their_own_entries(self) -> None:
        assert _map(_cit("Wade", "2024a")).reference_id == 3
        assert _map(_cit("Wade", "2024b")).reference_id == 4

    def test_no_suffix_with_several_candidates_is_flagged_not_silent(self) -> None:
        out = _map(_cit("Doe", "2018"))
        assert out.mapping_ambiguous
        assert out.candidate_reference_ids == [1, 2]
        assert out.mapping_confidence <= 0.5

    def test_duplicates_collapse_before_ambiguity(self) -> None:
        """2024a/2024b are one work; only Wade Y. 2024c is a real alternative."""
        out = _map(_cit("Wade", "2024"))
        assert out.mapping_ambiguous
        assert out.candidate_reference_ids == [3, 5]

    def test_coauthor_disambiguates_without_suffix(self) -> None:
        out = _map(_cit("Wade", "2024", authors=["Wade", "Moss"]))
        assert out.reference_id == 5
        assert not out.mapping_ambiguous

    def test_suffix_order_when_list_prints_no_letters(self) -> None:
        refs = [r.model_copy(update={"year_suffix": None, "raw_text": ""}) for r in _refs()[:2]]
        out = _map(_cit("Doe", "2018b"), refs)
        assert out.reference_id == 2
        assert "suffix_order" in out.mapping_method

    def test_unknown_suffix_is_flagged(self) -> None:
        out = _map(_cit("Doe", "2018c"))
        assert out.mapping_ambiguous
        assert set(out.candidate_reference_ids) == {1, 2}

    def test_suffix_read_from_raw_text_when_field_missing(self) -> None:
        """References persisted before year_suffix existed still map by letter."""
        refs = [r.model_copy(update={"year_suffix": None}) for r in _refs()]
        assert _map(_cit("Wade", "2024c"), refs).reference_id == 5


class TestNoSilentFallback:
    def test_year_mismatch_never_fuzzy_matches_another_surname(self) -> None:
        """"Sous et al., 2021" must not land on "de Sousa, 2023" (fuzzy 89%)."""
        out = _map(_cit("Sous", "2021"))
        assert out.reference_id == 6
        assert out.mapping_method == "author_only_year_mismatch"
        assert out.mapping_ambiguous

    def test_particle_surname_maps(self) -> None:
        assert _map(_cit("de Sousa", "2023")).reference_id == 7


class TestDetectionKeepsAuthorsAndLetters:
    def test_particle_surname_is_an_author(self) -> None:
        cits = detect_in_paragraph("Gels aid repair (de Sousa et al., 2023).", 0, "Intro")
        assert cits[0].authors == ["de Sousa"]

    def test_particle_inside_compound_group(self) -> None:
        text = "Gels aid repair (Smith, 2020; de Sousa et al., 2023b)."
        cits = detect_in_paragraph(text, 0, "Intro")
        assert [(c.authors, c.year) for c in cits] == [(["Smith"], "2020"), (["de Sousa"], "2023b")]

    def test_word_ending_in_particle_is_not_part_of_name(self) -> None:
        """"while Weller et al. (2018)" once became author "le Weller" (unmappable)."""
        text = "Gels degrade fast, while Weller et al. (2018) reported slow loss."
        narrative = [c for c in detect_in_paragraph(text, 0, "Intro") if c.is_narrative]
        assert narrative[0].authors == ["Weller"]

    def test_docx_level_citation_regex_keeps_suffix(self) -> None:
        found = find_citations_in_text("Gels aid repair (Doe et al., 2018b).")
        assert [c.raw_text for c in found] == ["(Doe et al., 2018b)"]


class TestAmbiguityReachesClaims:
    def test_flag_and_candidates_survive_scope_and_conversion(self) -> None:
        text = "Depots cut toxicity (Doe et al., 2018). Gels persist (Doe et al., 2018b)."
        cits = map_citations_to_references(detect_in_paragraph(text, 0, "Intro"), _refs())
        claims = units_to_claims(resolve_scopes(cits))
        assert [(c.reference_ids, c.mapping_ambiguous) for c in claims] == [
            ([1], True), ([2], False),
        ]
        assert claims[0].candidate_reference_ids == [1, 2]
