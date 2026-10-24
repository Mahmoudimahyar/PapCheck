"""V5.7 change switches: every V5.7 proposal is on unless listed in REFCHECK_V57_DISABLE.

REFCHECK_V57_DISABLE is a comma list of proposal numbers ("1,3,11") that turns those
changes off, so a cache replay can ablate them one at a time. Experimental proposals
(#14, #15) have their own opt-in switch as well; this helper only disables.

V5.8 round-2 fixes (G6) use the same switch with numbers >= 20. The ones without DEV
evidence (OPT_IN: #20, #24, #25, #29, #31, #32, #33; derived from TEST errors or never
measured live) are OFF by default and turned on with REFCHECK_V57_ENABLE (same comma-list
format); a number in both lists is off:

* 20 F1  screen tie-break for a disputed negative (dispute.screen_tie_break)
* 21 F2  quote edge repair before the exact match (layer_quotes.edge_trimmed)
* 22 F3  a hedged "stated" answer is not a clearance (round2_rules.hedged_stated)
* 23 F4  author-framing scaffolds (framing_rules.py)
* 24 F5  a near-duplicate survivor inherits its twin's clearance (round2_rules.twin_of)
* 25 F6  co-cited about-check: disjunctions and initialisms (round2_rules.about_parts)
* 26 F14 sub-type rules: noun-phrase list -> missing_element (subtype_round2.py; its
  other two rules are #32 / #33)
* 27 F8  "overstated" without a trigger word is re-checked as wording
* 28 F11 check-first when a supported verdict's "missing" names absent content
* 29 F7  overstated / broadened survivors also go to the co-cited union check (live)
* 30 F9  limitation elements: deficit terms in the union retrieval query (live)
* 31 F10 polarity trigger of the slot audit (live)
* 32 F14 part of #26: contradicted exclusivity / consequence sub-types (opt-in)
* 33 F14 part of #26: a quantifier survivor -> scope_overgeneralized (opt-in)

29-31 add or change adjudicator requests (measured live, adjudicator role only).
"""

import logging
import os

logger = logging.getLogger(__name__)

ENV = "REFCHECK_V57_DISABLE"
ENABLE_ENV = "REFCHECK_V57_ENABLE"
# Experimental V5.8 rules: off unless listed in REFCHECK_V57_ENABLE (module doc).
OPT_IN: frozenset[int] = frozenset({20, 24, 25, 29, 31, 32, 33})


def _numbers(env: str) -> frozenset[int]:
    found: set[int] = set()
    for part in os.getenv(env, "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            found.add(int(part))
        else:
            logger.warning("Ignoring %s entry %r (not a proposal number)", env, part)
    return frozenset(found)


def disabled() -> frozenset[int]:
    """The proposal numbers listed in REFCHECK_V57_DISABLE (unknown entries are ignored)."""
    return _numbers(ENV)


def opted_in() -> frozenset[int]:
    """The OPT_IN proposal numbers listed in REFCHECK_V57_ENABLE."""
    return _numbers(ENABLE_ENV) & OPT_IN


def enabled(n: int) -> bool:
    """Proposal ``n`` is on: not listed in REFCHECK_V57_DISABLE and, for an OPT_IN
    proposal, listed in REFCHECK_V57_ENABLE."""
    return n not in disabled() and (n not in OPT_IN or n in opted_in())
