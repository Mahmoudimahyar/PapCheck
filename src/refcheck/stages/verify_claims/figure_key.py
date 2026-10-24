"""A figure colour key the manuscript states differently from the source (V5.8 G2).

The manual review found a credited legend panel giving two markers one pair of colours
("MK1 (green) and MK2 (red)") where the source figure's own key shows them the other way
round. No model sees a
figure, so this is read deterministically (figure_key_claims: the claimed colours;
figure_key_source: the source's keys from text colours or local OCR + pixel colour)
and, like the number and lineage rules, turns the verdict partial (outcome_rules.py:
specific_detail_mismatch, major).

A verdict-changing (``decisive``) conflict needs ALL of (never flag on uncertainty):

* the cited text (a credit panel, or the cited part of a sentence) gives marker-like
  names a checkable colour, unambiguously, for at least TWO markers in at least two
  different colours;
* the source is full text with a readable local PDF;
* some source key group has a confident colour for EVERY claimed marker, and the claimed
  markers themselves show at least two different colours there (another word of the
  group, e.g. DAPI, does not count);
* no such group agrees with the manuscript (every marker the same bin or a wheel
  neighbour, figure_colors.contradicts) - a paper may show several keys;
* in that group EVERY claimed marker is contradicted, or two of them are swapped (each
  shows a colour the manuscript gives the other). The element names each contradicted
  marker with both colours.

Anything weaker (one claimed marker, one of two markers contradicted, a group whose
other words supply the second colour) is ``decisive=False``: a review note only, no
verdict change (outcome_rules.py) - a paper often colours a marker differently in
another figure, and a missed agreeing reading (key text under the OCR / saturation
thresholds) is not evidence of disagreement.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from refcheck.stages.verify_claims.figure_colors import contradicts
from refcheck.stages.verify_claims.figure_key_claims import (
    ColourClaim,
    colour_claims,
    marker_key,
)
from refcheck.stages.verify_claims.figure_key_source import KeyGroup, source_groups
from refcheck.stages.verify_claims.layers import cited_for

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.verifier_helpers import PairContext

ELEMENT_PREFIX = "colour key:"


class ColourMismatch(BaseModel):
    """One marker: the manuscript's colour and the source key's."""

    marker: str
    claimed: str
    seen: str


class ColourConflict(BaseModel):
    """The source key group that contradicts the manuscript's colour claims."""

    page: int
    mismatches: list[ColourMismatch]
    decisive: bool = True  # False: a review note only (module doc)

    @property
    def element(self) -> str:
        said = " and ".join(f"{m.marker} {m.claimed}" for m in self.mismatches)
        seen = " and ".join(f"{m.marker} {m.seen}" for m in self.mismatches)
        return f"{ELEMENT_PREFIX} manuscript says {said}, source figure shows {seen}"

    @property
    def note(self) -> str:
        if not self.decisive:
            return (f"Colour key check: a figure key in the source (page {self.page}) shows "
                    f"{self._seen()}, where the manuscript says {self._said()}; this may be "
                    "another figure, so the verdict is unchanged - please check the legend.")
        return (f"Colour key check: the source figure key (page {self.page}) shows "
                f"{self._seen()}, where the manuscript says {self._said()}; the verdict is "
                "partially supported (the figure legend's colour key needs correcting).")

    def _said(self) -> str:
        return ", ".join(f"{m.marker} in {m.claimed}" for m in self.mismatches)

    def _seen(self) -> str:
        return ", ".join(f"{m.marker} in {m.seen}" for m in self.mismatches)


def _readable(group: KeyGroup, claims: list[ColourClaim]) -> bool:
    return all(marker_key(c.marker) in group.colours for c in claims)


def _mismatches(group: KeyGroup, claims: list[ColourClaim]) -> list[ColourMismatch]:
    found = []
    for claim in claims:
        seen = group.colours[marker_key(claim.marker)]
        if contradicts(claim.colour, seen):
            found.append(ColourMismatch(marker=claim.marker, claimed=claim.colour, seen=seen))
    return found


def _swapped(group: KeyGroup, claims: list[ColourClaim]) -> bool:
    """Two claimed markers each show a colour the manuscript gives the other."""
    seen = {c.marker: group.colours[marker_key(c.marker)] for c in claims}
    return any(a.colour != b.colour and contradicts(a.colour, seen[a.marker])
               and not contradicts(b.colour, seen[a.marker])
               and not contradicts(a.colour, seen[b.marker])
               for a in claims for b in claims if a is not b)


def _decisive(group: KeyGroup, claims: list[ColourClaim],
              mismatches: list[ColourMismatch]) -> bool:
    keys = {marker_key(c.marker) for c in claims}
    return (len(keys) >= 2 and len({c.colour.lower() for c in claims}) >= 2
            and len({group.colours[k] for k in keys}) >= 2
            and (len(mismatches) == len(claims) or _swapped(group, claims)))


def key_conflict(claims: list[ColourClaim], groups: list[KeyGroup]) -> ColourConflict | None:
    """The conflict of ``claims`` with the source's key ``groups`` (module doc), or None;
    ``decisive`` only for the strict pattern, else a review note."""
    readable = [g for g in groups if claims and _readable(g, claims)]
    found = [(g, _mismatches(g, claims)) for g in readable]
    if not found or any(not mismatches for _, mismatches in found):
        return None  # nothing to compare, or some key agrees with the manuscript
    strong = next(((g, m) for g, m in found if _decisive(g, claims, m)), None)
    if strong is not None:
        return ColourConflict(page=strong[0].page, mismatches=strong[1])
    keyed = [(g, m) for g, m in found if len(set(g.colours.values())) >= 2]
    if not keyed:
        return None  # one coloured word, not a key
    return ColourConflict(page=keyed[0][0].page, mismatches=keyed[0][1], decisive=False)


def colour_conflict(text: str, pdf_path: Path | None) -> ColourConflict | None:
    """The conflict of ``text``'s colour claims with the PDF's figure keys, or None."""
    claims = colour_claims(text)
    if not claims or pdf_path is None or not pdf_path.is_file():
        return None
    return key_conflict(claims, source_groups(pdf_path, {marker_key(c.marker) for c in claims}))


def colour_finding(ctx: "PairContext") -> ColourConflict | None:
    """The colour-key conflict of a pair: its credit panel, or the cited part of its
    sentence (a co-cited sentence only when narrowed to this reference)."""
    if ctx.coverage != "full_text":
        return None
    part = cited_for(ctx.claim, ctx.claim_text)
    whole = ctx.claim_text if ctx.claim.co_cited_count <= 1 else ""
    text = ctx.credit_panel or part or whole
    if not text or not colour_claims(text):  # cheap: no PDF is opened without a claim
        return None
    return colour_conflict(text, ctx.ref.pdf_path)
