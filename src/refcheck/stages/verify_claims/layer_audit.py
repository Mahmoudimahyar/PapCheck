"""Audit one layer's parsed output before routing sees it (V5.6, run by layers.run_layer).

1. quotes are validated against the pack the layer saw (layer_quotes);
2. context-only quotes are set aside: a supports quote that states nothing of the
   cited part (E2/E4) and any quote that is the title, author block or journal header
   (E1, quote_context). They stay in the layer trace but are not evidence: they never
   count as a supports quote for routing and are never stored as evidence_quotes;
3. contained duplicates are dropped, the longer quote kept (E6);
4. the layer's "dismissed" clearances are checked (dismissals.py, L2): benign notes
   (and so guards) come only from validated dismissals.

Steps 2 (states) and 4 run only with REFCHECK_STRICT_CLEARANCE=on (clearance_mode.py).
Off (default, V5.5): the output has no states / dismissed, guards come from benign_notes
and a cocited_share note needs a co-cited abstract shown (``checked_notes``); front-matter
quotes and contained duplicates are handled in both modes.

A positive verdict left without an evidence supports quote is an "unusual positive"
(cascade.verifier_final -> cross-check), as before.
"""

from pydantic import BaseModel, Field

from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims.clearance_mode import checked_notes
from refcheck.stages.verify_claims.dismissals import audit_dismissals
from refcheck.stages.verify_claims.layer_quotes import (
    ValidatedQuote,
    dedupe_contained,
    validate_output_quotes,
)
from refcheck.stages.verify_claims.quote_context import front_matter
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.verifier_helpers import PairContext


class LayerAudit(BaseModel):
    """What a layer's output contributes once audited."""

    output: JudgeOutput
    evidence: list[ValidatedQuote] = Field(default_factory=list)
    context: list[ValidatedQuote] = Field(default_factory=list)  # trace only
    invalid: list[str] = Field(default_factory=list)  # not found in the pack
    rejected: list[str] = Field(default_factory=list)  # dismissals that failed the audit


def mark_context(quotes: list[ValidatedQuote], ctx: PairContext) -> list[ValidatedQuote]:
    """Each quote with ``context`` set when it is front matter (title / author block)."""
    marked: list[ValidatedQuote] = []
    for quote in quotes:
        why = quote.context or front_matter(quote.text, ctx.ref, ctx.doc)
        marked.append(quote.model_copy(update={"context": why}) if why else quote)
    return marked


def audit_layer(out: JudgeOutput, pack: EvidencePack, ctx: PairContext,
                strict: bool = True) -> LayerAudit:
    """Validate, classify and de-duplicate quotes; check the clearances (module doc)."""
    validated, invalid = validate_output_quotes(out, pack)
    marked = mark_context(validated, ctx)
    evidence = dedupe_contained([q for q in marked if not q.context])
    context = [q for q in marked if q.context]
    if not strict:
        return LayerAudit(output=checked_notes(out, ctx), evidence=evidence, context=context,
                          invalid=invalid)
    audit = audit_dismissals(out, pack, ctx, evidence)
    return LayerAudit(output=audit.output, evidence=evidence, context=context,
                      invalid=invalid, rejected=audit.rejected)
