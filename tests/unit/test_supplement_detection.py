"""M7: a Supporting-Information PDF is never accepted as the cited article."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs import match_pdfs
from refcheck.stages.match_pdfs.supplement_detector import (
    is_supplement_pdf,
    looks_like_supplement,
    supplement_file_name,
)
from refcheck.stages.verify_claims.source_document import load_source_document
from refcheck.stages.verify_claims.source_pdf import clear_pdf_cache
from refcheck.stages.verify_claims.text_quality import (
    describe_quality,
    is_supplement_text,
    s_caption_dominant,
)
from refcheck.stages.verify_claims.verifier_helpers import resolve_source

_TITLE = "Core-shell nanocarriers regulate the immune microenvironment of meniscus grafts"
_AUTHORS = "Jane Doe, Kim Roe, Lee Poe\nDepartment of Synthetic Tests, Example University"
_SI_BODY = "\n".join(
    f"Figure S{i}. Synthetic characterisation panel {i} of the nanocarrier." for i in range(1, 9)
) + "\nTable S1. Primer sequences used for qPCR."
_PROSE = ("Meniscus grafts were implanted in rabbits for twelve weeks. Inflammation decreased "
          "in treated joints. Cartilage regeneration improved compared with controls. ") * 10
_MAIN = (f"{_TITLE}\n{_AUTHORS}\nAbstract\n{_PROSE}\nIntroduction\n{_PROSE}\n"
         "Figure 1. Study design and graft implantation.\n"
         "Figure 2. Histology after twelve weeks.\nResults\n"
         f"{_PROSE} (Figure S2)\nFigure S3 shows the release curve.\nDiscussion\n{_PROSE}")
_ABSTRACT = ("Total meniscus replacement faces chronic inflammation and oxidative stress. A "
             "core-shell nanocarrier releasing two drugs regulated the immune microenvironment "
             "and improved cartilage regeneration in a rabbit model of meniscus replacement.")


def _pdf(path: Path, text: str, title: str = "") -> Path:
    """Synthetic PDF; `title` is set in a large font on page 1 (as journals do)."""
    doc = fitz.open()
    chunks = [text[i:i + 2500] for i in range(0, len(text), 2500)]
    for i, chunk in enumerate(chunks):
        page = doc.new_page()
        top = 40
        if title and i == 0:
            page.insert_textbox(fitz.Rect(40, 40, 560, 120), title, fontsize=16)
            top = 130
        page.insert_textbox(fitz.Rect(40, top, 560, 800), chunk, fontsize=8)
    doc.save(str(path))
    doc.close()
    return path


class TestTextSignals:
    def test_si_with_article_title_page_detected(self) -> None:
        si = f"{_TITLE}\n{_AUTHORS}\n*Corresponding author.\n{_SI_BODY}"
        assert s_caption_dominant(si)
        assert describe_quality(si) == (0.2, "likely_supplement")

    def test_main_article_mentioning_s_figures_not_flagged(self) -> None:
        assert not s_caption_dominant(_MAIN)
        assert describe_quality(_MAIN)[1] == "ok"

    def test_preprint_with_appended_supplement_not_flagged(self) -> None:
        assert not s_caption_dominant(_MAIN + "\n" + _SI_BODY)  # keeps its Introduction

    def test_markdown_article_with_s_captions_not_flagged(self) -> None:
        # e.g. a PMC full text whose figure list includes "Figure S1 …" captions
        prose = _PROSE.replace(". ", ".\n")  # hard-wrapped lines, as in real text
        markdown = (f"# {_TITLE}\n## Abstract\n{prose}\n## Introduction\n{prose}\n"
                    "Figure 1. Design.\nFigure 2. Histology.\n" + _SI_BODY)
        assert not s_caption_dominant(markdown)
        assert describe_quality(markdown)[1] == "ok"

    def test_file_name_hint_needs_content_support(self) -> None:
        assert is_supplement_text(f"{_TITLE}\nFigure S1. Panel.", "nn5c00001_si_001.pdf")
        assert is_supplement_text(f"{_TITLE}\n{_PROSE}", "41467_2024_MOESM1_ESM.pdf")
        assert not is_supplement_text(_MAIN, "Li Si - 2020 - Core shell nanocarriers.pdf")

    @pytest.mark.parametrize("name", [
        "nn5c00001_si_001.pdf", "mmc1.pdf", "41467_2024_MOESM1_ESM.pdf", "Data_Sheet_1.PDF",
        "Supplementary_Material.pdf", "paper-supp.pdf",
    ])
    def test_supplement_file_names(self, name: str) -> None:
        assert supplement_file_name(Path(name))

    @pytest.mark.parametrize("name", [
        "Wang et al. - 2025 - Core-shell nanocarriers.pdf", "tumor suppression review.pdf",
        "Simpson 2019.pdf",
    ])
    def test_article_file_names(self, name: str) -> None:
        assert not supplement_file_name(Path(name))

    def test_match_stage_rules_agree(self) -> None:
        si = f"{_TITLE}\n{_AUTHORS}\n{_SI_BODY}"
        assert looks_like_supplement(si, si, name_hint=False)
        assert not looks_like_supplement(_MAIN, _MAIN, name_hint=False)
        assert looks_like_supplement("Supporting Information\n" + _TITLE, _TITLE, False)


class TestVerifyStage:
    def test_si_pdf_falls_back_to_abstract(self, tmp_path: Path) -> None:
        clear_pdf_cache()
        si = _pdf(tmp_path / "nn5c00001_si_001.pdf", f"{_TITLE}\n{_AUTHORS}\n{_SI_BODY}")
        ref = Reference(id=108, title=_TITLE, pdf_path=si, abstract_text=_ABSTRACT,
                        abstract_source="semantic_scholar", source_status="found")
        doc = load_source_document(ref)
        assert doc is not None and doc.coverage == "abstract_only"
        assert doc.quality_reason == "likely_supplement"
        src = asyncio.run(resolve_source(ref.model_copy(update={"abstract_text": None})))
        assert src.doc is None and src.cannot_verify_reason == "pdf_supplement"


class TestMatchStage:
    def _refs(self) -> list[Reference]:
        return [Reference(id=108, title=_TITLE, doi="10.5555/nano.4c16158")]

    def test_article_preferred_over_supplement(self, tmp_path: Path) -> None:
        # Both print the article DOI and "a_..." sorts first: before M7 the SI won.
        doi = "doi: 10.5555/nano.4c16158"
        si = _pdf(tmp_path / "a_nn5c00001_si_001.pdf", f"{_AUTHORS}\n{doi}\n{_SI_BODY}",
                  title=_TITLE)
        main = _pdf(tmp_path / "wang2025.pdf", f"{doi}\n{_MAIN}", title=_TITLE)
        assert is_supplement_pdf(si) and not is_supplement_pdf(main)
        with patch("refcheck.stages.match_pdfs.matcher._lookup_doi_title", return_value=""):
            results = match_pdfs(self._refs(), tmp_path)
        chosen = [r for r in results if r.reference_id == 108]
        assert len(chosen) == 1 and Path(chosen[0].pdf_path or "").name == "wang2025.pdf"

    def test_supplement_alone_needs_confirmation(self, tmp_path: Path) -> None:
        _pdf(tmp_path / "nn5c00001_si_001.pdf", f"{_AUTHORS}\n{_SI_BODY}", title=_TITLE)
        with patch("refcheck.stages.match_pdfs.matcher._lookup_doi_title", return_value=""):
            results = match_pdfs(self._refs(), tmp_path)
        assert len(results) == 1 and results[0].needs_user_confirmation
        assert results[0].confidence <= 0.75
