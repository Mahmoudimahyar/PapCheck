"""OCR fallback for scanned/image-based PDF pages."""

import logging
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

_MIN_TEXT_CHARS = 50
_OCR_DPI = 300


def extract_text_with_ocr_fallback(pdf_path: Path) -> str:
    """Extract text from PDF. Falls back to OCR for image-based pages."""
    doc = fitz.open(str(pdf_path))
    full_text: list[str] = []
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text").strip()
            if len(text) < _MIN_TEXT_CHARS:
                ocr_text = _try_ocr_page(page)
                if ocr_text and len(ocr_text) > len(text):
                    text = ocr_text
            if text:
                full_text.append(text)
    finally:
        doc.close()
    return "\n\n".join(full_text)


def _try_ocr_page(page: object) -> str | None:
    """Attempt OCR on an image-based page. Graceful if pytesseract missing."""
    try:
        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=_OCR_DPI)  # type: ignore[attr-defined]
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        result: str = pytesseract.image_to_string(img).strip()
        return result
    except ImportError:
        logger.warning("pytesseract not installed, skipping OCR")
        return None
    except Exception as exc:
        logger.warning("OCR failed for page: %s", exc)
        return None
