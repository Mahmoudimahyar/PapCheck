"""One chat layer (L2 verifier, L3 judge, L4 confirm) over an evidence pack.

Every layer returns a JudgeOutput (strict JSON schema). Quotes are checked
against the text of the passage they cite (fallback: the whole pack); only
validated evidence quotes count for routing and are shown to the user. V5.6
(layer_audit.py): context-only quotes (states nothing of the cited part, or the
title / author block / journal header) stay in the trace only, contained duplicates
are dropped, and benign notes come only from "dismissed" clearances whose quote
validates (dismissals.py: no clearance without a quote). That V5.6 strict clearance
runs only with REFCHECK_STRICT_CLEARANCE=on; the default sends the V5.5 prompts and
schema (clearance_mode.py) so cached V5.5 answers are reused.
"""

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.llm import CostLimitExceededError, CostTracker, LLMError, Role, call_llm_raw
from refcheck.models.claim import Claim
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims.clearance_mode import (
    layer_output,
    request_model,
    strict_clearance,
    template_for,
)
from refcheck.stages.verify_claims.layer_audit import audit_layer
from refcheck.stages.verify_claims.layer_quotes import ValidatedQuote, validate_output_quotes
from refcheck.stages.verify_claims.retriever import EvidencePack, clean_query, render_pack
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables
from refcheck.stages.verify_claims.verifier_helpers import PairContext

__all__ = [
    "NEGATIVE", "POSITIVE", "Axis", "LayerResult", "PackKind", "ValidatedQuote", "axis_of",
    "cited_for", "layer_variables", "pack_for", "pack_summary", "run_layer",
    "validate_output_quotes",
]

logger = logging.getLogger(__name__)

Axis = Literal["positive", "negative"]
# recheck = standard pack + per-element passages (evidence re-check, recheck.py)
PackKind = Literal["standard", "expanded", "recheck"]
POSITIVE = frozenset({"supported", "partially_supported"})
NEGATIVE = frozenset({"not_supported", "contradicted", "not_relevant"})
_MIN_CALL_SECONDS = 2.0
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:])")  # left behind by removed markers


def axis_of(verdict: str | None) -> Axis | None:
    """positive / negative / None (insufficient_evidence, errors)."""
    if verdict in POSITIVE:
        return "positive"
    if verdict in NEGATIVE:
        return "negative"
    return None


class LayerResult(BaseModel):
    """Output + metadata of one layer call (output None on failure)."""

    layer: str  # verifier / verifier_expanded / verifier_recheck / judge / confirm / adjudicate
    role: Role
    output: JudgeOutput | None = None
    validated_quotes: list[ValidatedQuote] = Field(default_factory=list)  # evidence only
    context_quotes: list[ValidatedQuote] = Field(default_factory=list)  # V5.6: trace only
    invalid_quotes: list[str] = Field(default_factory=list)
    rejected_dismissals: list[str] = Field(default_factory=list)  # V5.6: failed the audit
    model_id: str = ""
    model_display: str = ""
    provider: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    error_kind: str | None = None
    pack_kind: PackKind = "standard"
    pack_summary: str = ""

    @property
    def verdict(self) -> str | None:
        return self.output.verdict if self.output else None

    @property
    def axis(self) -> Axis | None:
        return axis_of(self.verdict)

    def quotes(self, *roles: str) -> list[ValidatedQuote]:
        """Validated quotes with one of the given roles (all when none given)."""
        return [q for q in self.validated_quotes if not roles or q.role in roles]


def pack_summary(pack: EvidencePack, kind: PackKind) -> str:
    ids = [p.id for p in pack.passages]
    shown = ", ".join(ids[:3]) + (f" … {ids[-1]}" if len(ids) > 3 else "")
    return f"{kind} pack ({pack.coverage}): {shown or 'empty'}; {pack.total_tokens} tokens"


def pack_for(ctx: PairContext, kind: PackKind) -> EvidencePack:
    """The pack a layer of this kind saw (standard when the other one was never built)."""
    other = ctx.expanded if kind == "expanded" else ctx.recheck if kind == "recheck" else None
    return other if other is not None else ctx.pack


def cited_for(claim: Claim, claim_text: str = "") -> str:
    """The part of the sentence THIS reference is cited for ("" = the whole sentence).

    Read with getattr: ``Claim.cited_for`` is filled by citation detection when
    a sentence attaches different references to different clauses.
    """
    raw = str(getattr(claim, "cited_for", "") or "")
    part = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", clean_query(raw)).strip()
    whole = " ".join((claim_text or claim.extracted_claim or claim.manuscript_text).split())
    return "" if not part or _norm(part) == _norm(whole) else part


def _norm(text: str) -> str:
    return " ".join(text.lower().strip(" .;,").split())


def layer_variables(claim: Claim, ctx: PairContext, pack: EvidencePack,
                    pack_kind: PackKind) -> dict[str, object]:
    """Template variables shared by verify_claim.md and judge_claim.md."""
    ref = ctx.ref
    authors = ref.authors[0] + (" et al." if len(ref.authors) > 1 else "") if ref.authors else ""
    return {
        "section": "user", "passages": render_pack(pack), "coverage": pack.coverage,
        "pack_kind": pack_kind, "source_title": ref.title, "source_authors": authors,
        "source_year": ref.year, "claim": ctx.claim_text or claim.extracted_claim,
        "claim_type": claim.claim_type, "sentence": claim.manuscript_text,
        "prev_sentence": ctx.prev_sentence, "paragraph": ctx.paragraph,
        "section_heading": claim.section_heading, "co_cited_count": claim.co_cited_count,
        "cited_for": cited_for(claim, ctx.claim_text),
        "co_cited": [ref.model_dump() for ref in ctx.co_cited],
    }


async def run_layer(
    role: Role,
    pack: EvidencePack,
    claim: Claim,
    ctx: PairContext,
    template: str,
    *,
    layer: str | None = None,
    pack_kind: PackKind = "standard",
    cost_tracker: CostTracker | None = None,
    timeout: float | None = None,
    model: str | None = None,
) -> LayerResult:
    """Call the role's model on the pack; never raises for LLM/budget/timeout failures."""
    base = LayerResult(layer=layer or role, role=role, pack_kind=pack_kind,
                       pack_summary=pack_summary(pack, pack_kind))
    if timeout is not None and timeout < _MIN_CALL_SECONDS:
        return base.model_copy(update={"error": "per-pair time budget exhausted",
                                       "error_kind": "timeout"})
    strict = strict_clearance()
    prompt = template_for(template, strict)
    try:
        # Confirm re-runs the verifier's template on the verifier's pack; its cache key is
        # role-scoped (llm.structured.ROLE_SCOPED_CACHE), so it never replays a verifier
        # answer of the same model, and an eval --reuse-cache re-run reuses it.
        result = await call_llm_raw(
            prompt, layer_variables(claim, ctx, pack, pack_kind), request_model(strict),
            model=model, role=role, cost_tracker=cost_tracker, task=f"verify_{base.layer}",
            timeout=timeout, system_template=prompt, system_variables=system_variables(),
        )
    except CostLimitExceededError as exc:
        return base.model_copy(update={"error": f"cost limit reached: {exc}",
                                       "error_kind": "budget"})
    except (LLMError, TimeoutError) as exc:
        kind = exc.kind if isinstance(exc, LLMError) else "timeout"
        logger.warning("%s failed for claim %d / ref %d (%s): %s", base.layer, claim.id,
                       ctx.ref.id, kind, str(exc)[:200])
        return base.model_copy(update={"error": f"{kind}: {str(exc)[:300]}",
                                       "error_kind": kind,
                                       "model_id": getattr(exc, "model_id", None) or ""})
    audit = audit_layer(layer_output(result.parsed, strict), pack, ctx, strict)
    return base.model_copy(update={
        "output": audit.output, "validated_quotes": audit.evidence,
        "context_quotes": audit.context, "invalid_quotes": audit.invalid,
        "rejected_dismissals": audit.rejected,
        "model_id": result.model_id, "model_display": result.display_name or result.model_id,
        "provider": result.provider, "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd, "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
    })
