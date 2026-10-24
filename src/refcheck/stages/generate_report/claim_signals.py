"""Claim-level warnings shown next to a verdict.

* ``cited_for``: in "A does X (Ref1) and Y (Ref2)." Ref2 is cited for "Y" only.
  The verifier judges that clause; a reader who sees only the whole sentence
  cannot tell why a reference "does not support" it.
* fragment: the citing sentence looks incomplete ("Combining these
  features (Kray et al., 2023).") — the verdict is about unclear text.
* ambiguous mapping: "(Wade et al., 2024)" with Wade 2024a/b/c in the list; the
  pair was checked against a best guess.
"""

import re

from pydantic import BaseModel, Field

from refcheck.models.claim import Claim

FRAGMENT_TEXT = "Claim text appears incomplete — check the sentence in the manuscript."
_MARKER_RE = re.compile(
    r"\s*\[\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\]"  # [12], [3–5]
    r"|\s*\([^()]*\b(?:19|20)\d{2}[a-z]?\b[^()]*\)"  # (Smith et al., 2018b)
)


class ClaimSignals(BaseModel):
    """Claim-level findings (all empty for an ordinary claim)."""

    cited_for: str = ""  # narrowed clause; "" = the reference covers the whole sentence
    fragment: bool = False
    mapping_ambiguous: bool = False
    candidate_reference_ids: list[int] = Field(default_factory=list)
    mapping_text: str = ""


_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:])")  # left behind by removed markers


def _norm(text: str) -> str:
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", _MARKER_RE.sub("", text))
    return " ".join(text.lower().split()).strip(" .;,")


def narrowed_cited_for(claim: Claim) -> str:
    """The clause this reference is cited for, "" when it is the whole sentence."""
    part = " ".join(claim.cited_for.split())
    if not part:
        return ""
    wholes = [w for w in (claim.extracted_claim, claim.manuscript_text) if w.strip()]
    return "" if any(_norm(part) == _norm(w) for w in wholes) else part


def _refs(ids: list[int]) -> str:
    labels = [f"[{i}]" for i in ids]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " or " + labels[-1]


def mapping_text(claim: Claim) -> str:
    """Why the claim's reference is a guess ("" when the mapping is certain)."""
    if not claim.mapping_ambiguous:
        return ""
    markers = claim.location.citation_markers if claim.location else []
    cited = f"“{markers[0]}”" if markers else "The in-text citation"
    checked = claim.reference_ids[0] if claim.reference_ids else None
    against = f"; it was checked against [{checked}]" if checked is not None else ""
    candidates = claim.candidate_reference_ids
    if len(candidates) > 1:
        return (f"{cited} could refer to {_refs(candidates)}{against}. "
                "Add the year letter (e.g. 2024a/2024b) or a co-author to the citation.")
    return (f"{cited} matches no reference by year or year letter{against} "
            "(same first author). Check the citation's year.")


def claim_signals(claim: Claim | None) -> ClaimSignals:
    """All claim-level findings of ``claim``."""
    if claim is None:
        return ClaimSignals()
    return ClaimSignals(
        cited_for=narrowed_cited_for(claim),
        fragment=claim.claim_quality == "fragment",
        mapping_ambiguous=claim.mapping_ambiguous,
        candidate_reference_ids=list(claim.candidate_reference_ids),
        mapping_text=mapping_text(claim),
    )
