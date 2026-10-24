"""Post-parse repair pass for malformed DOCX reference entries.

Handles truncated journal names, leaked reference numbers, and
fragments caused by multi-paragraph references in DOCX files.
"""

import logging
import re

from pydantic import BaseModel

logger = logging.getLogger(__name__)

JOURNAL_PREFIXES: dict[str, str] = {
    "Front": "Frontiers",
    "Int": "International",
    "Circ": "Circulation",
    "J Am": "Journal of the American",
    "Nat": "Nature",
    "Sci": "Science",
    "Biomater": "Biomaterials",
    "Transpl": "Transplantation",
    "Plast": "Plastic",
    "Ann": "Annals",
    "Br": "British",
    "Am J": "American Journal",
    "Eur": "European",
    "Clin": "Clinical",
    "Cell": "Cell",
    "Mol": "Molecular",
    "Biochem": "Biochemistry",
    "Biomed": "Biomedical",
}

YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
NUMBER_PREFIX_PATTERN = re.compile(r"^\d{1,3}\s*\n")


class RepairEntry(BaseModel):
    """A single repaired reference entry."""

    text: str
    repair_type: str


def repair_reference_list(raw_entries: list[str]) -> list[RepairEntry]:
    """Repair malformed reference entries from DOCX parsing.

    Applies three rules in order:
    1. Fragment detection — short entry without a year → merge with next
    2. Number prefix removal — leading reference number leaked in
    3. Truncated journal prefix — merge known abbreviation with next entry
    """
    repaired: list[RepairEntry] = []
    i = 0
    while i < len(raw_entries):
        entry = raw_entries[i].strip()

        # Rule 1: Fragment — short entry without a year
        is_fragment = len(entry) < 30 and not YEAR_PATTERN.search(entry)
        if is_fragment and i + 1 < len(raw_entries):
            merged = entry + " " + raw_entries[i + 1].strip()
            repaired.append(RepairEntry(
                text=merged, repair_type="merged_fragment",
            ))
            logger.info("Merged fragment: '%s' + next entry", entry[:40])
            i += 2
            continue

        # Rule 2: Number prefix — starts with just a number + newline
        number_match = NUMBER_PREFIX_PATTERN.match(entry)
        if number_match:
            cleaned = entry[number_match.end():].strip()
            repaired.append(RepairEntry(
                text=cleaned, repair_type="removed_number_prefix",
            ))
            logger.info("Removed number prefix from: '%s'", entry[:40])
            i += 1
            continue

        # Rule 3: Truncated journal prefix
        if _is_journal_prefix(entry) and i + 1 < len(raw_entries):
            merged = entry + raw_entries[i + 1].strip()
            repaired.append(RepairEntry(
                text=merged, repair_type="merged_journal_prefix",
            ))
            logger.info("Merged journal prefix: '%s'", entry[:40])
            i += 2
            continue

        # No repair needed
        repaired.append(RepairEntry(text=entry, repair_type="none"))
        i += 1

    return repaired


def _is_journal_prefix(text: str) -> bool:
    """Check if text is likely a truncated journal name prefix."""
    stripped = text.strip().rstrip(".")
    if stripped in JOURNAL_PREFIXES:
        return True
    return len(stripped) < 8 and len(stripped) > 0 and stripped[0].isupper()


def summarize_repairs(entries: list[RepairEntry]) -> str:
    """Build a human-readable summary of repairs applied."""
    total = len(entries)
    merged = sum(1 for e in entries if e.repair_type == "merged_fragment")
    prefixes = sum(1 for e in entries if e.repair_type == "removed_number_prefix")
    journals = sum(1 for e in entries if e.repair_type == "merged_journal_prefix")
    repaired = merged + prefixes + journals
    return (
        f"Repaired {repaired} of {total} references "
        f"({merged} merged fragments, {prefixes} prefix removals, "
        f"{journals} journal merges)"
    )
