"""Colour claims of legends / sentences and colour bins (V5.8 G2). Synthetic text only."""

import pytest
from PIL import Image

from refcheck.stages.verify_claims.figure_colors import (
    claimed_bins,
    contradicts,
    hue_bin,
    int_colour,
    region_colour,
    rgb_colour,
)
from refcheck.stages.verify_claims.figure_key_claims import colour_claims, marker_key, marker_like


def _pairs(text: str) -> list[tuple[str, str]]:
    return [(marker_key(c.marker), c.colour) for c in colour_claims(text)]


@pytest.mark.parametrize(("text", "expected"), [
    ("Staining of MK1⁺ (green) and MK2⁺ (red) cells in tissue Z at day 3.",
     [("mk1", "green"), ("mk2", "red")]),
    ("CD8+ T cells (in green) surround the graft.", [("cd8", "green")]),
    ("Grafts stained for Ki67 in magenta and GFP in green.",
     [("ki67", "magenta"), ("gfp", "green")]),
    ("FoxP3 cells are shown in red.", [("foxp3", "red")]),
    ("Key: red: CD8; green: CD4.", [("cd8", "red"), ("cd4", "green")]),
    ("Green-labelled CD31 vessels and red-stained NG2 pericytes.",
     [("cd31", "green"), ("ng2", "red")]),
    ("Green signal indicates QDX emission at 650 nm.", [("qdx", "green")]),
    ("CD8/CD4/DAPI (red/green/blue) staining of the graft.",
     [("cd8", "red"), ("cd4", "green"), ("dapi", "blue")]),
    ("PD-L1 (yellow) is expressed by the vesicles.", [("pdl1", "yellow")]),
])
def test_colour_claims(text: str, expected: list[tuple[str, str]]) -> None:
    assert _pairs(text) == expected


@pytest.mark.parametrize("text", [
    "Blood levels with (red) or without (black) the hydrogel.",  # not markers
    "Red blood cells were lysed before staining.",
    "Cells expressing green fluorescent protein were transplanted.",
    "Red indicates tissue background.",  # "tissue" is not a marker name
    "CD8 (green) cells and, in panel B, CD8 (red) cells.",  # one marker, two colours
    "The graft (Fig. 2) was rejected by day 12.",
    "",
])
def test_no_colour_claims(text: str) -> None:
    assert colour_claims(text) == []


def test_marker_names_keep_their_sign_for_display() -> None:
    assert [c.marker for c in colour_claims("MK1⁺ (green) and MK2+ (red)")] == ["MK1⁺", "MK2+"]


@pytest.mark.parametrize(("token", "like"), [
    ("CD8", True), ("GFP", True), ("Ki67", True), ("QDX", True), ("FoxP3", True),
    ("tissue", False), ("with", False), ("Hoechst", False), ("800", False), ("Red", False),
])
def test_marker_like(token: str, like: bool) -> None:
    assert marker_like(token) is like


def test_marker_key_ignores_signs_and_hyphens() -> None:
    assert marker_key("CD8⁺") == marker_key("CD8+") == marker_key("(CD8*") == "cd8"
    assert marker_key("PD-L1") == "pdl1" and marker_key("CD4") != marker_key("CD44")


def test_colour_bins() -> None:
    assert rgb_colour(230, 20, 30) == "red" and rgb_colour(20, 200, 40) == "green"
    assert rgb_colour(30, 40, 230) == "blue" and rgb_colour(240, 230, 20) == "yellow"
    assert rgb_colour(200, 40, 200) == "purple" and rgb_colour(20, 210, 220) == "cyan"
    assert rgb_colour(0, 0, 0) is None and rgb_colour(128, 128, 128) is None
    assert rgb_colour(255, 255, 255) is None and rgb_colour(60, 10, 10) is None  # too dark
    assert int_colour(0xFF0000) == "red" and int_colour(0x000000) is None
    assert hue_bin(355.0) == "red" and hue_bin(30.0) == "orange"


def test_claim_words_and_contradiction() -> None:
    assert claimed_bins("Magenta") == {"purple"} and claimed_bins("white") == frozenset()
    assert contradicts("green", "red") and contradicts("red", "green")
    assert not contradicts("red", "orange")  # wheel neighbours are never a conflict
    assert not contradicts("pink", "purple") and not contradicts("pink", "red")
    assert not contradicts("white", "red")  # an unverifiable claim never conflicts


def test_region_colour_needs_a_dominant_coloured_bin() -> None:
    image = Image.new("RGB", (40, 20), "white")
    image.paste((220, 20, 20), (8, 5, 12, 15))  # a red stroke on paper (left)
    image.paste((20, 200, 20), (28, 5, 32, 15))  # a green stroke on paper (right)
    assert region_colour(image, (0, 0, 20, 20)) == "red"
    assert region_colour(image, (20, 0, 40, 20)) == "green"
    assert region_colour(image, (0, 0, 40, 20)) is None  # no bin dominates
    assert region_colour(Image.new("RGB", (20, 20), "white"), (0, 0, 20, 20)) is None
    assert region_colour(Image.new("RGB", (20, 20), (220, 20, 20)), (0, 0, 20, 20)) is None
