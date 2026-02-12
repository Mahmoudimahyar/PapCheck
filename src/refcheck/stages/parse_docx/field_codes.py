"""Extract Zotero/Mendeley/EndNote field codes from DOCX XML."""

import logging
import zipfile
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)

# Word XML namespace
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _WORD_NS}

# Patterns indicating reference manager field codes
_FIELD_CODE_MARKERS = [
    "ADDIN ZOTERO_ITEM",
    "ADDIN EN.CITE",
    "ADDIN Mendeley",
    "CSL_CITATION",
]


def detect_field_codes(docx_path: Path) -> bool:
    """Check whether a DOCX file contains reference manager field codes.

    Looks for Zotero, Mendeley, or EndNote markers in the document XML.
    """
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return False
            xml_content = zf.read("word/document.xml")
        return _scan_xml_for_field_codes(xml_content)
    except (zipfile.BadZipFile, KeyError, OSError):
        logger.warning("Could not read DOCX XML for field code detection")
        return False


def _scan_xml_for_field_codes(xml_content: bytes) -> bool:
    """Scan raw Word XML for reference manager field code markers."""
    try:
        tree = etree.fromstring(xml_content)  # noqa: S320
    except etree.XMLSyntaxError:
        logger.warning("Malformed DOCX XML")
        return False

    # Check instrText elements for field codes
    instr_elements = tree.findall(f".//{{{_WORD_NS}}}instrText")
    for elem in instr_elements:
        if elem.text:
            for marker in _FIELD_CODE_MARKERS:
                if marker in elem.text:
                    return True

    # Also check fldChar elements (complex field codes)
    body_text = etree.tostring(tree, encoding="unicode")
    return any(marker in body_text for marker in _FIELD_CODE_MARKERS)
