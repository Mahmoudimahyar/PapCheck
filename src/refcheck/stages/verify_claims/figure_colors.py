"""Colour names for figure colour keys (V5.8 G2): text colours, pixel regions, claim words.

A colour key is only read when it is unambiguous, because a read colour can change a
verdict (figure_key.py):

* a colour is one of seven hue bins on the colour wheel, ``WHEEL`` (red, orange,
  yellow, green, cyan, blue, purple); black, white and grey text has no colour
  (``None``): body text, axis labels and white-on-image labels never count;
* a pixel counts when it is saturated (HSV saturation >= MIN_SATURATION) and not dark
  (value >= MIN_VALUE); a region (an OCR word box) is read on its glyph pixels only: the
  ink (dark in the min-channel image the OCR reads, min channel < INK_MAX) must be the
  minority of the box and the rest (the paper) must not itself be coloured (at most
  MAX_GROUND_COLOURED saturated), so a white or black label drawn over a stained
  micrograph never takes the image's colour; it has a colour only when at least
  MIN_PIXELS and MIN_SHARE of its pixels are coloured ink and DOMINANT of those fall in
  one bin;
* a manuscript colour word names one or more bins (``claimed_bins``: "pink" is red or
  purple, "magenta" / "violet" are purple); white / grey / black / brown name none, so
  such a claim is never checked;
* a seen bin contradicts a claimed colour only when it is neither one of its bins nor
  a neighbour on the wheel (``contradicts``): "orange" text is not a contradiction of
  "red", "red" text is one of "green".
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

WHEEL: tuple[str, ...] = ("red", "orange", "yellow", "green", "cyan", "blue", "purple")
# Upper hue bound (degrees) of each bin; hues >= 340 are red again.
_BOUNDS: tuple[tuple[float, str], ...] = (
    (15.0, "red"), (40.0, "orange"), (70.0, "yellow"), (165.0, "green"),
    (200.0, "cyan"), (255.0, "blue"), (340.0, "purple"), (360.0, "red"))
MIN_SATURATION = 0.45
MIN_VALUE = 90  # 0-255
MIN_PIXELS = 12
MIN_SHARE = 0.03
DOMINANT = 0.75
INK_MAX = 160  # min channel below this: ink (coloured or black text turns dark for OCR)
MAX_GROUND_COLOURED = 0.2  # share of saturated background pixels a key label may sit on

COLOUR_WORDS: dict[str, frozenset[str]] = {
    "red": frozenset({"red"}), "orange": frozenset({"orange"}),
    "yellow": frozenset({"yellow"}), "green": frozenset({"green"}),
    "cyan": frozenset({"cyan"}), "blue": frozenset({"blue"}),
    "purple": frozenset({"purple"}), "magenta": frozenset({"purple"}),
    "violet": frozenset({"purple"}), "pink": frozenset({"red", "purple"}),
    "white": frozenset(), "grey": frozenset(), "gray": frozenset(),
    "black": frozenset(), "brown": frozenset(),
}
COLOUR_PATTERN = "|".join(sorted(COLOUR_WORDS, key=len, reverse=True))


def hue_bin(hue: float) -> str:
    """The bin of a hue in degrees [0, 360)."""
    for bound, name in _BOUNDS:
        if hue < bound:
            return name
    return "red"


def _pixel_bin(r: int, g: int, b: int) -> str | None:
    high, low = max(r, g, b), min(r, g, b)
    if high < MIN_VALUE or (high - low) / high < MIN_SATURATION:
        return None
    span = float(high - low)
    if high == r:
        hue = (60.0 * (g - b) / span) % 360.0
    elif high == g:
        hue = 60.0 * (b - r) / span + 120.0
    else:
        hue = 60.0 * (r - g) / span + 240.0
    return hue_bin(hue)


def rgb_colour(r: int, g: int, b: int) -> str | None:
    """The bin of one colour (0-255 channels), None for black / white / grey."""
    return _pixel_bin(r, g, b)


def int_colour(value: int) -> str | None:
    """The bin of a PyMuPDF span colour (sRGB packed as 0xRRGGBB)."""
    return _pixel_bin((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def region_colour(image: "Image.Image", box: tuple[int, int, int, int]) -> str | None:
    """The dominant colour of the GLYPH pixels of ``box`` (left, top, right, bottom) of an
    RGB image, or None when the background is coloured, too few glyph pixels are coloured
    or no bin dominates (module doc)."""
    left, top, right, bottom = box
    if right - left < 2 or bottom - top < 2:
        return None
    pixels = list(image.crop(box).convert("RGB").getdata())
    ink = [p for p in pixels if min(p) < INK_MAX]  # dark in the min-channel OCR image
    paper = [p for p in pixels if min(p) >= INK_MAX]
    if not paper or len(ink) > len(paper):
        return None  # light glyphs on a darker / coloured ground (a label over an image)
    if sum(_pixel_bin(*p) is not None for p in paper) > MAX_GROUND_COLOURED * len(paper):
        return None  # the ground itself is coloured
    counts: dict[str, int] = {}
    for r, g, b in ink:
        name = _pixel_bin(r, g, b)
        if name is not None:
            counts[name] = counts.get(name, 0) + 1
    coloured = sum(counts.values())
    if coloured < MIN_PIXELS or coloured < MIN_SHARE * len(pixels):
        return None
    name, top_count = max(counts.items(), key=lambda item: item[1])
    return name if top_count >= DOMINANT * coloured else None


def claimed_bins(word: str) -> frozenset[str]:
    """The bins a manuscript colour word names (empty: not checkable)."""
    return COLOUR_WORDS.get(word.strip().lower(), frozenset())


def _neighbours(name: str) -> set[str]:
    i = WHEEL.index(name)
    return {WHEEL[(i - 1) % len(WHEEL)], name, WHEEL[(i + 1) % len(WHEEL)]}


def contradicts(claimed_word: str, seen: str) -> bool:
    """``seen`` is neither a bin of ``claimed_word`` nor a wheel neighbour of one."""
    bins = claimed_bins(claimed_word)
    if not bins or seen not in WHEEL:
        return False
    return not any(seen in _neighbours(b) for b in bins)
