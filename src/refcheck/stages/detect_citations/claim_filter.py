"""Filter out empty or citation-only claims before verification.

Removes claims where the manuscript text is just citation markers
(e.g., "(Wang et al., 2020; Smith et al., 2022)" or a narrative
"Wang et al. (2020).") with no actual assertion to verify. A citation-only
fragment is normally joined to its sentence by the sentence splitter; one
left with no sentence to attach to can never be verified.
"""

import logging
import re

from refcheck.models.claim import Claim
from refcheck.stages.detect_citations.citation_only import is_citation_only

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 10

CITATION_PATTERNS = [
    re.compile(
        r"\([A-Z][a-zA-Z\-]+(?:\s+et\s+al\.)?,?\s*\d{4}[a-z]?"
        r"(?:;\s*[A-Z][a-zA-Z\-]+(?:\s+et\s+al\.)?,?\s*\d{4}[a-z]?)*\)"
    ),
    re.compile(r"\[\d+(?:[,\s\-\u2013\u2014]+\d+)*\]"),
]


def filter_empty_claims(claims: list[Claim]) -> list[Claim]:
    """Remove claims where the text is just citation markers with no assertion.

    A claim is filtered if, after stripping all citation markers,
    the remaining text is fewer than 10 characters.
    """
    filtered: list[Claim] = []
    removed = 0
    for claim in claims:
        text = claim.extracted_claim or claim.manuscript_text or ""
        stripped = strip_citation_markers(text).strip()
        if len(stripped) < _MIN_TEXT_LENGTH:
            logger.info(
                "Filtered empty claim %d: '%s'", claim.id, text[:80],
            )
            removed += 1
            continue
        if is_citation_only(claim.manuscript_text):
            logger.info(
                "Skipped claim %d: citing sentence is only a citation, with no "
                "assertion to verify: '%s'", claim.id, claim.manuscript_text[:80],
            )
            removed += 1
            continue
        filtered.append(claim)

    if removed:
        logger.info("Filtered %d empty claims", removed)
    return filtered


def strip_citation_markers(text: str) -> str:
    """Remove citation markers, leaving only the actual claim text."""
    result = text
    for pattern in CITATION_PATTERNS:
        result = pattern.sub("", result)
    result = re.sub(r"[;\s]+$", "", result).strip()
    return result
