"""Template variables of the element adjudicator prompt (prompts/adjudicate_elements.md).

The system part renders the taxonomy's model-applied guards G2-G4 (definition
+ first synthetic example) from partial_taxonomy.json via taxonomy_prompt, so
the adjudicator and the verifier rubric never drift apart; the disqualifiers
(framing that asserts a cause, added quantifiers, time frames, mechanisms,
recommendations, populations, dropped explicit limits, specifics) are spelled out in
the template and enforced in code (clear_rules.disqualifier via adjudicate_rules.py;
framing, like stated / wording, must quote the passage it rests on, V5.6).
QUANTIFIERS lives in clear_rules (no imports there) and is re-exported here.
The user part shows the SAME evidence pack the
shown verdict was based on and the co-cited references (only an abstract can
clear an element).
"""

from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.clear_rules import QUANTIFIERS
from refcheck.stages.verify_claims.layers import PackKind, cited_for
from refcheck.stages.verify_claims.retriever import EvidencePack, render_pack
from refcheck.stages.verify_claims.taxonomy_prompt import taxonomy_prompt
from refcheck.stages.verify_claims.verifier_helpers import PairContext

TEMPLATE = "adjudicate_elements"
__all__ = ["QUANTIFIERS", "TEMPLATE", "adjudicate_system_variables", "adjudicate_user_variables"]


def adjudicate_system_variables() -> dict[str, object]:
    """System-prompt variables (stable: cacheable across pairs)."""
    # G2's example adds nothing to the cocited category (an abstract quote is required).
    guards = [g.model_dump() | ({"example": ""} if g.id == "cocited_share" else {})
              for g in taxonomy_prompt().guards]
    return {"section": "system", "guards": guards,
            "quantifiers": ", ".join(f"'{q}'" for q in QUANTIFIERS)}


def adjudicate_user_variables(claim: Claim, ctx: PairContext, pack: EvidencePack,
                              pack_kind: PackKind, elements: list[str]) -> dict[str, object]:
    """User-prompt variables: pack, co-cited references, claim and the elements."""
    ref = ctx.ref
    authors = ref.authors[0] + (" et al." if len(ref.authors) > 1 else "") if ref.authors else ""
    return {
        "section": "user", "passages": render_pack(pack), "coverage": pack.coverage,
        "pack_kind": pack_kind, "source_title": ref.title, "source_authors": authors,
        "source_year": ref.year, "claim": ctx.claim_text or claim.extracted_claim,
        "sentence": claim.manuscript_text, "cited_for": cited_for(claim, ctx.claim_text),
        "co_cited": [r.model_dump() for r in ctx.co_cited], "elements": list(elements),
    }
