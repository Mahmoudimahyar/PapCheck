"""Optional OCR for image-only PDF pages (pytesseract + the tesseract binary).

Nothing is installed: OCR runs only when the pytesseract package imports AND a
tesseract executable is found (TESSERACT_CMD, PATH, or the standard Windows
install folders). REFCHECK_OCR=0 disables it. Every failure degrades to "no
OCR text", so a scanned PDF is then reported as pdf_scanned instead.
"""

import logging
import os
import shutil
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

OCR_DPI = 300
_DISABLED_VALUES = ("0", "false", "no", "off")
_WINDOWS_DIRS = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")


def ocr_enabled() -> bool:
    """False when REFCHECK_OCR is set to 0/false/no/off."""
    return os.getenv("REFCHECK_OCR", "1").strip().lower() not in _DISABLED_VALUES


def find_tesseract() -> str | None:
    """Path of a tesseract executable, or None (never installs anything)."""
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for var in _WINDOWS_DIRS:
        base = os.getenv(var, "")
        for sub in ("Tesseract-OCR", os.path.join("Programs", "Tesseract-OCR")):
            candidate = Path(base) / sub / "tesseract.exe" if base else None
            if candidate is not None and candidate.is_file():
                return str(candidate)
    return None


def ocr_available() -> bool:
    """True when OCR is enabled, pytesseract imports and the binary is found."""
    if not ocr_enabled():
        return False
    try:
        import pytesseract  # type: ignore[import-untyped]
    except ImportError:
        return False
    cmd = find_tesseract()
    if cmd is None:
        return False
    pytesseract.pytesseract.tesseract_cmd = cmd
    return True


def ocr_page_text(page: fitz.Page, dpi: int = OCR_DPI) -> str:
    """OCR text of one page ("" on any OCR failure)."""
    try:
        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=dpi, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return str(pytesseract.image_to_string(image))
    except Exception as exc:  # OCR backends raise many unrelated error types
        logger.warning("OCR failed on page %d: %s", page.number + 1, type(exc).__name__)
        return ""
