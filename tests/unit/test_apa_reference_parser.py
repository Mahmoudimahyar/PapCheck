"""M10 (parse side): "Authors (Year). Title. Journal Vol, pages. doi" titles.

Regression: the parser stored the journal/volume/pages segment ("Synth Nano 14,
301–309. doi: …") as the title, and is_likely_bad_title() let it through
because it is longer than 25 characters. All strings are synthetic.
"""

import pytest

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.apa_parser import parse_apa_reference, split_apa_authors
from refcheck.stages.parse_docx.author_parser import parse_authors_title
from refcheck.stages.parse_docx.reference_extractor import extract_year, parse_single_reference
from refcheck.stages.parse_docx.title_repairer import (
    detect_and_repair_bad_titles,
    extract_title_from_raw_text,
    is_likely_bad_title,
)
from refcheck.stages.parse_docx.year_parser import extract_year_info

# Shapes of the four V4.9 failures (refs 44, 65, 73, 112), with invented content
_GARBLED = {
    "chapter": (
        "Kepler, M. I., and Tarr, A. (2010). Allograft Choice in Knee Ligament Surgery. "
        "Synth Inj., 210–219. doi: 10.1000/978-3-000-00000-0_58",
        "Allograft Choice in Knee Ligament Surgery",
    ),
    "journal_vol_pages": (
        "Marsh, D. W., Varga, J. J., Strand, J. E., and Benn, D. S. W. (2018). Serum Effects "
        "on Colloidal Stability of a Micellar Carrier. Synth Nano 14, 301–309. "
        "doi: 10.1000/synnano.7b00001",
        "Serum Effects on Colloidal Stability of a Micellar Carrier",
    ),
    "single_word_journal": (
        "Moss, S., Hart, A., and Eaton, R. T. (2016). Clinical Value of Synthetic Cell "
        "Grafts in Type 1 Diabetes. SynthMedicine 9, 140–148. doi: 10.1000/j.synmed.2016.08.001",
        "Clinical Value of Synthetic Cell Grafts in Type 1 Diabetes",
    ),
    "article_number": (
        "Ho, I.-E., Orr, M. R., Pratt, S.-Y., and Pratt, C.-H. (2021). Heat-Responsive Polyester "
        "Gel for Local Drug Delivery in Synthetic Grafts. Hydrogels 5, 117. "
        "doi: 10.1000/gels5020001",
        "Heat-Responsive Polyester Gel for Local Drug Delivery in Synthetic Grafts",
    ),
}


class TestApaTitle:
    @pytest.mark.parametrize("raw,title", list(_GARBLED.values()), ids=list(_GARBLED))
    def test_title_is_the_segment_after_the_year(self, raw: str, title: str) -> None:
        ref = parse_single_reference(1, raw)
        assert ref.title == title
        assert not is_likely_bad_title(ref.title)

    def test_question_mark_title_and_html_tags(self) -> None:
        raw = ("Ap, L., and Fa, G. L. (2020). <p>Do Massive Grafts Survive 10 Years?</p>. "
               "Clin. Synth. 47, 51–59.")
        assert parse_authors_title(raw)[1] == "Do Massive Grafts Survive 10 Years?"

    def test_dotted_acronym_does_not_end_title(self) -> None:
        raw = "Lee, K. (2019). Graft outcomes in U.S. veterans after repair. J. Surg. 4, 1–9."
        assert parse_authors_title(raw)[1] == "Graft outcomes in U.S. veterans after repair"

    def test_vancouver_reference_is_not_taken_as_apa(self) -> None:
        raw = ("[2] A. Kline, I. Nash, Cartilage repair year in review 2024, "
               "Synth. Cartilage, 12 (2024) 101.")
        assert parse_apa_reference(raw) is None
        assert "Cartilage repair year in review" in parse_authors_title(raw)[1]

    def test_group_author(self) -> None:
        parts = parse_apa_reference("World Health Organization (2020). Global report on burns.")
        assert parts is not None and parts.authors == ["World Health Organization"]

    def test_author_list_shapes(self) -> None:
        assert split_apa_authors("de Sousa, A. H., dos Santos Reis, R. B., et al.") == [
            "de Sousa, A. H.", "dos Santos Reis, R. B.",
        ]
        assert split_apa_authors("Smith JA, Jones K") == ["Smith, JA", "Jones, K"]
        assert split_apa_authors("Hand Surgery : Plastic & Reconstructive Surgery") is None


class TestBadTitleDetection:
    @pytest.mark.parametrize("title", [
        "Synth Nano 14, 301–309. doi: 10.1000/synnano.7b00001",
        "Synth Inj., 210–219. doi: 10.1000/978-3-000-00000-0_58",
        "SynthMedicine 9, 140–148. doi: 10.1000/j.synmed.2016.08.001",
        "Hydrogels 5, 117. doi: 10.1000/gels5020001",
        "Front. Synth. 11. doi: 10.1000/fsyn.2024.000001",
        "Biomaterials 999, 100001",
        "A title that somehow carries doi: 10.1000/x.y",
    ])
    def test_journal_citation_titles_are_bad(self, title: str) -> None:
        assert is_likely_bad_title(title)

    @pytest.mark.parametrize("title", [
        "Cartilage repair year in review 2024",
        "Effects of 12 weeks of training on tendon stiffness",
        "Outcomes in patients aged 18–65 after ligament repair",
        "Interleukin 6, 8 and 10 levels in septic transplant recipients",
    ])
    def test_real_titles_with_numbers_are_kept(self, title: str) -> None:
        assert not is_likely_bad_title(title)

    def test_repair_re_extracts_title_from_raw_text(self) -> None:
        raw, title = _GARBLED["journal_vol_pages"]
        refs = [Reference(id=1, raw_text=raw, title="Synth Nano 14, 301–309. doi: 10.1000/x")]
        needs_llm = detect_and_repair_bad_titles(refs)
        assert needs_llm == []
        assert refs[0].title == title
        assert refs[0].repair_applied == "title_re_extracted"

    def test_raw_text_fallback_skips_journal_segments(self) -> None:
        raw = "Marsh D W. Serum effects on micellar carrier stability. Synth Nano 14, 301–309"
        assert extract_title_from_raw_text(raw) == "Serum effects on micellar carrier stability"


class TestYearInfo:
    def test_parenthesised_suffix(self) -> None:
        info = extract_year_info("Doe, D. (2018b). A title. J. 1, 2.")
        assert (info.year, info.suffix) == (2018, "b")

    def test_doi_years_are_ignored(self) -> None:
        """A year inside a DOI is not the publication year."""
        info = extract_year_info("Doe, D. Title. doi: 10.1000/fsyn.2024.1000001")
        assert info.year is None

    def test_decade_is_not_a_suffix(self) -> None:
        assert extract_year_info("Trends since the 1990s in grafting").suffix is None

    def test_extract_year_still_returns_int(self) -> None:
        assert extract_year("Smith J. Cancer. 2020;1:1-5.") == 2020
