"""cited_for parity between the eval rows and production (V5.7 #10 / #14).

Production computes cited_for at detection time (detect_citations/cited_for.py). The gold
rows store the V5.6 value and the Citation-Integrity rows have none, so the eval
recomputes it with the current rules (detect_citations/cited_for_rescope.py):

- gold: ``gold_cited_for`` returns the stored value unless a V5.7 rule narrows it
  (4 of 281 rows with #10, 5 with REFCHECK_SUBJECT_PREPEND=on);
- Citation-Integrity: only a row whose cited_for a V5.7 rule changes gets one (5 of
  305 test.bal rows); every other row keeps "" so its verifier request stays
  byte-identical (cached). Full production parity (always the narrowed sentence) would
  change about half the rows and is deliberately not the default.

REFCHECK_V57_DISABLE=10 (and #14 off) reproduces the V5.6 values exactly.
"""

import logging
from collections.abc import Iterable, Mapping

from eval_models import EvalItem, ScreenRecord
from gold_models import GoldRow

from refcheck.stages.detect_citations.cited_for_rescope import gold_cited_for, placeholder_scope

logger = logging.getLogger(__name__)


def gold_row_cited_for(row: GoldRow) -> str:
    """The gold row's cited_for under the current rules (stored value when unchanged)."""
    author = row.ref_authors[0] if row.ref_authors else ""
    return gold_cited_for(row.sentence, row.claim, row.cited_for, author, row.ref_year)


def ci_cited_for(item: EvalItem) -> str:
    """A Citation-Integrity row's cited_for: the V5.7-narrowed clause, else ""."""
    if not item.claim_raw:
        return ""
    found = placeholder_scope(item.claim_raw)
    return found.after if found is not None and found.changed else ""


def parity_changed(item: EvalItem) -> bool:
    """A V5.7 rule changed this item's cited_for (so a recorded screen is stale)."""
    if item.gold_row is not None:
        return gold_row_cited_for(item.gold_row) != item.gold_row.cited_for
    return bool(ci_cited_for(item))


def fresh_screens(items: Iterable[EvalItem],
                  screens: Mapping[str, ScreenRecord]) -> dict[str, ScreenRecord]:
    """``screens`` without items whose cited_for changed: the screen reads cited_for, so
    those few pairs are screened again (one uncached call each; a miss when offline)."""
    stale = {item.id for item in items if item.id in screens and parity_changed(item)}
    if stale:
        logger.info("cited_for changed (V5.7 #10/#14): re-screening %s", sorted(stale))
    return {key: rec for key, rec in screens.items() if key not in stale}
