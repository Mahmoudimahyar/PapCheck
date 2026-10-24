"""Synthetic uploaded PDFs and references for the PDF re-match tests (no real papers)."""

from pathlib import Path

import fitz

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference

TITLE_A = "Injectable synthetic hydrogels release tacrolimus locally and prolong rodent limb grafts"
TITLE_B = "Porous alginate capsules protect transplanted islets from cytokine stress in mice"
DOI_A = "10.5555/synth.01234-56"
DOI_B = "10.5555/synth.77777"
PROSE = ("Grafts were monitored for sixty days. Rejection scores were lower in treated "
         "animals than in controls. Drug levels in blood stayed below the toxic range. ") * 12
OTHER_PROSE = ("Meeting abstract. Preliminary data from four animals are summarised here; "
               "the complete study will be reported separately by the consortium. ") * 12


def ref(rid: int, title: str = TITLE_A, doi: str | None = DOI_A, **kw: object) -> Reference:
    base: dict[str, object] = {
        "id": rid, "title": title, "doi": doi, "authors": ["Doe, J.", "Roe, K."], "year": 2021,
    }
    base.update(kw)
    return Reference.model_validate(base)


def article(
    path: Path, title: str = TITLE_A, doi_line: str = f"https://doi.org/{DOI_A}",
    authors: str = "Jane Doe, Kim Roe", year: str = "2021", meta_title: str = "",
    pages: int = 4, page2: str = "", body: str = PROSE,
) -> Path:
    """An article PDF: title in a large font, authors, year, DOI line, then prose pages."""
    doc = fitz.open()
    first = doc.new_page()
    first.insert_textbox(fitz.Rect(40, 40, 560, 140), title, fontsize=16)
    head = f"{authors}\nReceived {year}; published online {year}\n{doi_line}\nAbstract\n"
    first.insert_textbox(fitz.Rect(40, 150, 560, 800), head + body[:1500], fontsize=8)
    for i in range(1, pages):
        page = doc.new_page()
        text = page2 if (i == 1 and page2) else PROSE
        page.insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=8)
    if meta_title:
        doc.set_metadata({"title": meta_title})
    doc.save(str(path))
    doc.close()
    return path


def scanned(path: Path, title: str = TITLE_A) -> Path:
    """A text cover page followed by image-only (text-less) pages."""
    doc = fitz.open()
    cover = doc.new_page()
    cover.insert_textbox(fitz.Rect(40, 40, 560, 800),
                         f"{title}\nJane Doe, Kim Roe\n2021\nhttps://doi.org/{DOI_A}\n{PROSE[:900]}",
                         fontsize=9)
    for _ in range(4):
        page = doc.new_page()
        page.draw_rect(fitz.Rect(40, 40, 560, 800), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    doc.save(str(path))
    doc.close()
    return path


def supplement(path: Path, title: str = TITLE_A) -> Path:
    """Supporting Information: the article title and DOI, then Figure S captions."""
    captions = "\n".join(f"Figure S{i}. Synthetic control panel {i}." for i in range(1, 9))
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(40, 40, 560, 800),
        f"Supporting Information\n{title}\nJane Doe, Kim Roe\n2021\n"
        f"https://doi.org/{DOI_A}\n{captions}\n{PROSE[:600]}", fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


def held(rid: int, path: Path, confirm: bool = False) -> MatchResult:
    """A first-pass match of reference `rid` to `path`."""
    return MatchResult(reference_id=rid, pdf_path=str(path), confidence=0.95,
                       match_method="title_fuzzy", needs_user_confirmation=confirm)


class GateStub:
    """Identity gate stub: a status per file name (default for others); records calls."""

    def __init__(self, default: str = "verified", **by_stem: str) -> None:
        self.default = default
        self.by_stem = by_stem
        self.calls: list[tuple[int, str]] = []

    def __call__(self, reference: Reference, path: Path) -> str:
        self.calls.append((reference.id, path.name))
        return self.by_stem.get(path.stem, self.default)
