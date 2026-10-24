"""Figure colour keys of a source PDF and the colour-key rule (V5.8 G2).

Synthetic PDFs only: a key "MK1 / MK2 / DAPI" (invented markers) written as coloured text
(text layer) or drawn into an image (OCR path; skipped without a local Tesseract).
"""

from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from refcheck.stages.verify_claims.figure_key import (
    ColourConflict,
    colour_conflict,
    key_conflict,
)
from refcheck.stages.verify_claims.figure_key_claims import colour_claims
from refcheck.stages.verify_claims.figure_key_source import (
    KeyGroup,
    image_groups,
    source_groups,
)
from refcheck.stages.verify_claims.source_ocr import ocr_available

RED, GREEN, BLUE = (0.9, 0.1, 0.1), (0.1, 0.75, 0.1), (0.1, 0.1, 0.9)
LEGEND = "Figure 3. MK1 and MK2 cells in tissue Z."
SWAPPED = "Staining of MK1⁺ (green) and MK2⁺ (red) cells in tissue Z."
RIGHT = "Staining of MK1⁺ (red) and MK2⁺ (green) cells in tissue Z."
_RGB = {"MK1": (220, 20, 20), "MK2": (20, 180, 20), "DAPI": (20, 20, 220)}


def text_key_pdf(path: Path, colours: tuple[tuple[float, float, float], ...] = (RED, GREEN, BLUE),
                 ) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    x = 72.0
    for word, colour in zip(("MK1", "/MK2", "/DAPI"), colours, strict=True):
        page.insert_text((x, 300), word, fontsize=9, color=colour)
        x += fitz.get_text_length(word, fontsize=9)
    page.insert_text((72, 400), LEGEND, fontsize=9)
    doc.save(str(path))
    return path


def key_image() -> Image.Image:
    image = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(image)
    try:
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.truetype("arial.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    x = 40
    for i, word in enumerate(("MK1", "MK2", "DAPI")):
        if i:
            draw.text((x, 70), "/", fill="black", font=font)
            x += int(draw.textlength("/", font=font))
        draw.text((x, 70), word, fill=_RGB[word], font=font)
        x += int(draw.textlength(word, font=font))
    return image


def test_text_layer_key_is_read_with_span_colours(tmp_path: Path) -> None:
    groups = source_groups(text_key_pdf(tmp_path / "key.pdf"), {"mk1", "mk2"})
    assert [g.colours for g in groups] == [{"mk1": "red", "mk2": "green", "dapi": "blue"}]
    assert groups[0].page == 1


def test_black_text_is_no_key(tmp_path: Path) -> None:
    black = ((0.0, 0.0, 0.0),) * 3
    assert source_groups(text_key_pdf(tmp_path / "black.pdf", black), {"mk1"}) == []


def test_pages_that_never_name_the_markers_are_skipped(tmp_path: Path) -> None:
    assert source_groups(text_key_pdf(tmp_path / "key.pdf"), {"ki67"}) == []


def test_an_unreadable_pdf_has_no_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert source_groups(bad, {"mk1"}) == []
    assert colour_conflict(SWAPPED, bad) is None and colour_conflict(SWAPPED, None) is None


def test_the_whole_read_is_cached_failures_included(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from refcheck.stages.verify_claims import figure_key_source
    pdf, bad = text_key_pdf(tmp_path / "key.pdf"), tmp_path / "bad2.pdf"
    bad.write_bytes(b"not a pdf")
    first = (source_groups(pdf, {"mk1", "mk2"}), source_groups(bad, {"mk1"}))
    monkeypatch.setattr(figure_key_source.fitz, "open", None)  # a second read would fail
    assert (source_groups(pdf, {"mk1", "mk2"}), source_groups(bad, {"mk1"})) == first


def test_a_swapped_key_is_a_conflict(tmp_path: Path) -> None:
    found = colour_conflict(SWAPPED, text_key_pdf(tmp_path / "key.pdf"))
    assert isinstance(found, ColourConflict) and found.page == 1
    assert found.element == ("colour key: manuscript says MK1⁺ green and MK2⁺ red, "
                             "source figure shows MK1⁺ red and MK2⁺ green")
    assert found.decisive and "partially supported" in found.note


def test_the_right_key_is_no_conflict(tmp_path: Path) -> None:
    assert colour_conflict(RIGHT, text_key_pdf(tmp_path / "key.pdf")) is None
    assert colour_conflict("MK1⁺ (orange) cells.", text_key_pdf(tmp_path / "k2.pdf")) is None


def _group(page: int, **colours: str) -> KeyGroup:
    return KeyGroup(page=page, colours=colours, shown={k: k.upper() for k in colours})


def test_any_agreeing_key_clears_the_claim() -> None:
    claims = colour_claims(SWAPPED)
    swapped = _group(2, mk1="red", mk2="green")
    agreeing = _group(5, mk1="green", mk2="red")
    assert key_conflict(claims, [swapped]) is not None
    assert key_conflict(claims, [swapped, agreeing]) is None


def test_a_key_must_cover_every_marker_and_show_two_colours() -> None:
    claims = colour_claims(SWAPPED)
    assert key_conflict(claims, [_group(1, mk1="red")]) is None  # MK2 not in the key
    assert key_conflict(claims, [_group(1, mk1="red", mk2="red")]) is None  # one colour
    assert key_conflict([], [_group(1, mk1="red", mk2="green")]) is None


def test_only_contradicted_markers_are_named_and_one_is_not_decisive() -> None:
    claims = colour_claims("MK1 (red), MK2 (red) and DAPI (blue).")
    found = key_conflict(claims, [_group(3, mk1="red", mk2="green", dapi="blue")])
    assert found is not None and [m.marker for m in found.mismatches] == ["MK2"]
    assert not found.decisive and "verdict is unchanged" in found.note


def test_a_single_marker_claim_is_a_review_note_only() -> None:
    claims = colour_claims("MK1+ cells (green) infiltrated tissue Z.")
    found = key_conflict(claims, [_group(2, mk1="red", dapi="blue")])  # DAPI: 2nd colour
    assert found is not None and not found.decisive
    assert key_conflict(claims, [_group(2, mk1="red")]) is None  # one coloured word


def test_every_marker_contradicted_without_a_swap_is_decisive() -> None:
    claims = colour_claims("MK1 (green) and MK2 (red).")
    found = key_conflict(claims, [_group(1, mk1="blue", mk2="yellow")])
    assert found is not None and found.decisive


def test_a_label_over_a_coloured_image_is_not_a_key_colour() -> None:
    from refcheck.stages.verify_claims.figure_colors import region_colour
    image = Image.new("RGB", (200, 60), (20, 170, 40))  # a green-stained micrograph
    draw = ImageDraw.Draw(image)
    try:
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default(size=40)
    draw.text((10, 5), "MK1", fill="white", font=font)
    assert region_colour(image, (0, 0, 100, 60)) is None
    draw.text((110, 5), "MK2", fill="black", font=font)
    assert region_colour(image, (100, 0, 200, 60)) is None  # black on green: no key colour


ocr = pytest.mark.skipif(not ocr_available(), reason="local Tesseract not installed")


@ocr
def test_raster_key_is_read_with_ocr_word_boxes() -> None:
    groups = image_groups(key_image(), 1)
    colours = {k: v for g in groups for k, v in g.colours.items()}
    assert colours.get("mk1") == "red" and colours.get("mk2") == "green"


@ocr
def test_raster_key_in_a_pdf_page(tmp_path: Path) -> None:
    png = tmp_path / "key.png"
    key_image().save(png)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(72, 100, 522, 210), filename=str(png))
    page.insert_text((72, 300), LEGEND, fontsize=9)
    doc.save(str(tmp_path / "raster.pdf"))
    found = colour_conflict(SWAPPED, tmp_path / "raster.pdf")
    assert found is not None and {m.seen for m in found.mismatches} == {"red", "green"}
    assert colour_conflict(RIGHT, tmp_path / "raster.pdf") is None
