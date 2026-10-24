"""The colour keys a source PDF's figures show (V5.8 G2), from text colours or OCR.

A key group is one block of figure text ("CD8/CD4/Nucleus" under a panel) with the
colour of each marker-like word in it (figure_key_claims.marker_like):

* text layer (vector figures): PyMuPDF spans of a text block, each span's fill colour
  (figure_colors.int_colour; black text has none);
* raster figures: each page's image area rendered at OCR_DPI, LOCAL Tesseract word
  boxes (source_ocr: optional, REFCHECK_OCR=0 disables it) on the min-channel image
  (coloured text turns dark, so red / green words are read like black ones), and the
  dominant coloured pixel bin inside each word's box (figure_colors.region_colour). A
  word "CD8/CD4/Nucleus" is split at "/", each part judged on its share of the box
  (characters are assumed equally wide, so only the middle of each share is read).

A marker read in two colours within one group has no colour there. Both readings are
cached per PDF page (path, modification time, page): OCR runs once per figure page; the
whole result per (PDF, modification time, markers), failures included, under a per-PDF
lock (``source_groups``).
"""

import logging
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import fitz
from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.figure_colors import int_colour, region_colour
from refcheck.stages.verify_claims.figure_key_claims import marker_key, marker_like
from refcheck.stages.verify_claims.source_ocr import OCR_DPI, ocr_available

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

MIN_IMAGE_PT = 60.0  # images smaller than this (points, either side) are not figures
MIN_OCR_CONF = 30.0
_SPLIT = re.compile(r"[/,;:|]+")
_MARGIN = 0.15  # share of each part's width left out on both sides
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class KeyGroup(BaseModel):
    """One block of figure text: marker key -> colour bin, and how the source writes it."""

    page: int  # 1-based
    colours: dict[str, str] = Field(default_factory=dict)
    shown: dict[str, str] = Field(default_factory=dict)


def _add(readings: dict[str, set[str | None]], shown: dict[str, str], word: str,
         colour: str | None) -> None:
    key = marker_key(word)
    if key and marker_like(word.strip("()[],;:*")):
        readings.setdefault(key, set()).add(colour)
        shown.setdefault(key, word.strip("()[],;:*"))


def _group(page: int, readings: dict[str, set[str | None]], shown: dict[str, str]) -> KeyGroup:
    colours = {k: next(iter(v)) for k, v in readings.items() if len(v) == 1 and None not in v}
    return KeyGroup(page=page, colours={k: c for k, c in colours.items() if c},
                    shown={k: shown[k] for k in colours})


def text_groups(page: fitz.Page) -> list[KeyGroup]:
    """Key groups of the page's text layer (one per text block with a coloured marker)."""
    groups: list[KeyGroup] = []
    for block in page.get_text("dict").get("blocks", []):
        readings: dict[str, set[str | None]] = {}
        shown: dict[str, str] = {}
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                colour = int_colour(int(span.get("color", 0)))
                for part in _SPLIT.split(str(span.get("text", ""))):
                    for word in part.split():
                        _add(readings, shown, word, colour)
        group = _group(page.number + 1, readings, shown)
        if group.colours:
            groups.append(group)
    return groups


def figure_area(page: fitz.Page) -> fitz.Rect | None:
    """The union of the page's figure-sized images, or None."""
    area: fitz.Rect | None = None
    for info in page.get_image_info():
        rect = fitz.Rect(info["bbox"]) & page.rect
        if rect.width >= MIN_IMAGE_PT and rect.height >= MIN_IMAGE_PT:
            area = rect if area is None else area | rect
    return area


def _parts(word: str, box: tuple[int, int, int, int]) -> list[tuple[str, tuple[int, ...]]]:
    """``word`` split at "/" etc., each part with the middle of its share of ``box``."""
    left, top, width, height = box
    out: list[tuple[str, tuple[int, ...]]] = []
    pos = 0
    for part in _SPLIT.split(word):
        start = word.find(part, pos) if part else pos
        pos = start + len(part)
        if not part or not word:
            continue
        x0 = left + width * start / len(word)
        x1 = left + width * pos / len(word)
        pad = (x1 - x0) * _MARGIN
        out.append((part, (int(x0 + pad), top, int(x1 - pad), top + height)))
    return out


def image_groups(image: "Image.Image", page_no: int) -> list[KeyGroup]:
    """Key groups of one rendered figure image (OCR word boxes + pixel colours)."""
    import pytesseract  # type: ignore[import-untyped]
    from PIL import ImageChops

    red, green, blue = image.convert("RGB").split()
    dark = ImageChops.darker(red, ImageChops.darker(green, blue))  # min channel
    data = pytesseract.image_to_data(dark, output_type=pytesseract.Output.DICT)
    blocks: dict[int, tuple[dict[str, set[str | None]], dict[str, str]]] = {}
    for i, word in enumerate(data["text"]):
        if not str(word).strip() or float(data["conf"][i]) < MIN_OCR_CONF:
            continue
        box = (int(data["left"][i]), int(data["top"][i]),
               int(data["width"][i]), int(data["height"][i]))
        readings, shown = blocks.setdefault(int(data["block_num"][i]), ({}, {}))
        for part, (x0, y0, x1, y1) in _parts(str(word), box):
            _add(readings, shown, part, region_colour(image, (x0, y0, x1, y1)))
    groups = [_group(page_no, r, s) for r, s in blocks.values()]
    return [g for g in groups if g.colours]


@lru_cache(maxsize=256)
def _page_groups(path: str, mtime: float, page_no: int, ocr: bool) -> tuple[KeyGroup, ...]:
    """Cached key groups of one page (``mtime`` keys the cache to the file version)."""
    with fitz.open(path) as doc:
        page = doc[page_no]
        groups = text_groups(page)
        area = figure_area(page) if ocr else None
        if area is not None:
            from PIL import Image

            pix = page.get_pixmap(dpi=OCR_DPI, clip=area, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            groups += image_groups(image, page_no + 1)
    return tuple(groups)


def _page_keys(page: fitz.Page) -> set[str]:
    return {marker_key(w) for w in _SPLIT.sub(" ", page.get_text("text")).split()}


def source_groups(pdf_path: Path, markers: set[str]) -> list[KeyGroup]:
    """Key groups of every page whose text (or a neighbour's: a legend may sit on the
    next page) names all ``markers``; [] when the PDF cannot be read. The whole result,
    a failure included, is cached per (PDF, modification time, markers) and computed
    under a per-PDF lock, so concurrent pairs citing one PDF read and OCR it once and the
    second call (outcome_rules, on the event loop) is a cache hit."""
    try:
        mtime = pdf_path.stat().st_mtime
    except OSError as exc:
        logger.warning("Colour key: cannot read %s: %s", pdf_path.name, type(exc).__name__)
        return []
    with _lock_for(str(pdf_path)):
        return list(_cached_groups(str(pdf_path), mtime, frozenset(markers)))


def _lock_for(path: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


@lru_cache(maxsize=256)
def _cached_groups(path: str, mtime: float, markers: frozenset[str]) -> tuple[KeyGroup, ...]:
    name = Path(path).name
    try:
        with fitz.open(path) as doc:
            named = [markers <= _page_keys(page) for page in doc]
    except Exception as exc:  # unreadable / encrypted / missing PDF: no key
        logger.warning("Colour key: cannot read %s: %s", name, type(exc).__name__)
        return ()
    pages = [i for i in range(len(named)) if any(named[max(0, i - 1):i + 2])]
    ocr = ocr_available()
    groups: list[KeyGroup] = []
    for i in pages:
        try:
            groups.extend(_page_groups(path, mtime, i, ocr))
        except Exception as exc:  # OCR / rendering backends raise many error types
            logger.warning("Colour key: page %d of %s failed: %s", i + 1, name,
                           type(exc).__name__)
    return tuple(groups)
