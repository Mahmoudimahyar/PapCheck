"""Deterministic checks after routing that add notes / review, never change a verdict.

(The two deterministic checks that DO change a verdict - a figure the source states
differently, an impossible lineage connective - are in outcome_rules.py.)

* Secondary citation (M12): a validated "supports" quote that itself cites other
  work ("... [10, 11, 23]", "(Smith et al., 2019)") means the source reports
  someone else's finding; the manuscript should cite the primary study. V5.6 (E5):
  given the pair context, no note when the paper states the point itself - a
  marker-free supporting quote in its Abstract / Results / Conclusion (elsewhere only
  when it reports data), or such a sentence found over the whole document; never for
  a review (own_statement.states_itself).
* Numbers absent from the source (M13): claim figures that occur nowhere in the
  source document text (see source_numbers.py).
* Quote surroundings: the source text right around each validated quote; a claim
  figure stated there (another arm or cohort of the quoted result) is not a quoted-
  number mismatch (gates.numeric_mismatch). V5.6 (E7): neither is a claim figure the
  whole text or abstract states with the same unit and kind ("8 mm" in the Methods,
  "60 days" in the Results); a bare figure or percentage stated elsewhere in another
  context still is (common figures appear somewhere in most papers).

The V5.7 "check first" triage of supported verdicts (notes / review only) is in
check_first.py; it uses ``cites_other_work``.
"""

from collections.abc import Iterable

from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote, cited_for, pack_for
from refcheck.stages.verify_claims.markers import LEADING_MARKER_RE, MARKER_RE
from refcheck.stages.verify_claims.number_rule import same_kind
from refcheck.stages.verify_claims.own_statement import states_itself
from refcheck.stages.verify_claims.source_document import SourceDocument
from refcheck.stages.verify_claims.source_numbers import (
    numbers_missing_from_source,
    quantities,
    source_index,
)
from refcheck.stages.verify_claims.verifier_helpers import PairContext

SECONDARY_CITATION_NOTE = ("Secondary citation: the source attributes this to other work "
                           "— consider citing the primary study.")
NEAR_QUOTE_CHARS = 250  # same sentence / table row as the quote


def cites_other_work(quote: ValidatedQuote) -> bool:
    """The quote, its source span, or a marker right after it cites other work."""
    if MARKER_RE.search(quote.text) or MARKER_RE.search(quote.source_span):
        return True
    return LEADING_MARKER_RE.match(quote.source_after) is not None


def _own_quote(quote: ValidatedQuote) -> bool:
    """A supporting evidence quote (not context only) that cites no other work."""
    return quote.role == "supports" and not quote.context and not cites_other_work(quote)


def secondary_citation_note(quotes: Iterable[ValidatedQuote],
                            ctx: PairContext | None = None) -> str | None:
    """SECONDARY_CITATION_NOTE when a supporting quote cites other work and (given the
    pair context) the paper does not state the point itself (module doc)."""
    shown = list(quotes)
    secondary = [q for q in shown if q.role == "supports" and cites_other_work(q)]
    if not secondary:
        return None
    if ctx is not None and states_itself(
            ctx.doc, cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text, secondary,
            [q for q in shown if _own_quote(q)], ctx.ref):
        return None
    return SECONDARY_CITATION_NOTE


def searchable_text(doc: SourceDocument) -> str:
    """Whole source text plus the abstract (a metadata abstract is not in full_text)."""
    abstract = doc.abstract_chunk
    if abstract is None or abstract.text in doc.full_text:
        return doc.full_text
    return doc.full_text + "\n\n" + abstract.text


def missing_numbers_note(ctx: PairContext) -> str | None:
    """Note listing claim numbers found nowhere in the source text, else None."""
    part = cited_for(ctx.claim, ctx.claim_text)
    missing = numbers_missing_from_source(part or ctx.claim_text, searchable_text(ctx.doc))
    if not missing:
        return None
    note = f"Numbers not found in the source: {', '.join(missing)}"
    if ctx.coverage != "full_text":
        note += " (only the abstract was available)"
    elif not part and ctx.claim.co_cited_count > 1:
        note += (f" (the sentence cites {ctx.claim.co_cited_count} references; the figure "
                 "may come from another one)")
    return note + " — please check where they come from."


def stated_elsewhere(claim_part: str, source_text: str) -> list[str]:
    """Claim figures the source states with the same value, unit and kind, as source
    text: a measurement unit ("8 mm") suffices; a percentage or plain figure needs the
    same statistic label or words after it ("60 days"); a bare one never counts."""
    pool = source_index(source_text) if source_text.strip() else ()
    found: list[str] = []
    for q in quantities(claim_part):
        tolerance = 0.5 / float(10 ** q.decimals) + 1e-9
        match = next((s for s in pool if abs(s.value - q.value) <= tolerance and s.unit == q.unit
                      and (q.unit not in ("", "%") or same_kind(q, s))), None)
        if match is not None:
            found.append(" ".join([match.text, *match.nouns]))
    return found


def quote_surroundings(ctx: PairContext, layers: Iterable[LayerResult]) -> str:
    """Source text within NEAR_QUOTE_CHARS of each validated quote, in its own passage,
    plus the claim figures the whole source states with the same kind (module doc)."""
    parts: list[str] = []
    for lay in layers:
        pack = pack_for(ctx, lay.pack_kind)
        for quote in lay.validated_quotes:
            passage = pack.get(quote.passage_id)
            parts.append(_around(quote.source_span or quote.text,
                                 [passage.text] if passage is not None else [],
                                 pack.joined_text))
    part = cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text
    parts.extend(stated_elsewhere(part, searchable_text(ctx.doc)))
    return "\n\n".join(parts)


def _around(span: str, own: list[str], joined: str) -> str:
    for text in [*own, joined]:
        start = text.find(span)
        if start >= 0:
            end = start + len(span) + NEAR_QUOTE_CHARS
            return text[max(0, start - NEAR_QUOTE_CHARS):end]
    return span
