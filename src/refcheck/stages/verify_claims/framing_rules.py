"""Author-framing scaffolds (V5.8 #23, F4; taxonomy author_framing_or_example (a)).

An element the element adjudicator found in nothing it was shown ("absent"), or an
"absent" element the co-cited union check could not clear, is the citing author's
organising layer, not a claim attributed to the source, when it is ONLY:

* an enumeration scaffold ("three phases", "two categories");
* a positioning contrast ("rather than", "unlike") with nothing else;
* a meta element ("the classification", "framing");
* a concessive link ("even when", "even if").

"Only" is literal: with the scaffold phrase and stop words removed, no content word may
be left ("unlike tacrolimus" or "prevented rejection even when given 7 days after
transplantation" still state something about the source and are never cleared). The
element must also pass clear_rules.disqualifier (no time frame, mechanism, population,
number ...), the same safeguard a model-chosen framing clearance has, and the scaffold's
words must be in the cited span, so a scaffold the model invented clears nothing. The
element is cleared as framing (a note; a disputed pair keeps its review flag). Never for
an overstated / broadened / contradicted element. Rejected: an emphasis "particularly X"
(it hit 2 gold partials) and a negated universal ("not all ...": derived from a TEST
error, and "not all recipients developed rejection" is a finding, not a hedge). Off with
REFCHECK_V57_DISABLE=23.
"""

import re

from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.bm25 import tokenize
from refcheck.stages.verify_claims.clear_rules import disqualifier

FRAMING_NOTE = "rule: author framing (an organising scaffold of the citing text)"
SCAFFOLD_CATEGORIES = frozenset({"absent"})
_SCAFFOLDS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(two|three|four|five|several|multiple|\d+)[\s-]+(phases?|stages?|steps?"
    r"|categor(y|ies)|types?|class(es)?|levels?|generations?|waves?)\b",
    r"\b(different from|differs? from|difference from|unlike|in contrast (to|with)"
    r"|as opposed to|rather than)\b",
    r"\b(category|framing|classification|organi[sz]ing structure)\b",
    r"\beven (when|if|after|though)\b"))


def is_scaffold(element: str, cited: str, category: str = "absent") -> bool:
    """``element`` is nothing but an author-framing scaffold of the cited span (module
    doc); ``category``: the element's answer category (only "absent" qualifies)."""
    if not v57.enabled(23) or category not in SCAFFOLD_CATEGORIES:
        return False
    if disqualifier(element) is not None:
        return False
    for pattern in _SCAFFOLDS:
        match = pattern.search(element)
        if match is None or not re.search(re.escape(match.group(0)), cited or "",
                                          re.IGNORECASE):
            continue
        if not tokenize(pattern.sub(" ", element)):
            return True
    return False
