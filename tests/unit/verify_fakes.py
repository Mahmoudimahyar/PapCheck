"""Shared builders for the V5 verification cascade tests (no network)."""

from collections.abc import Callable, Sequence

from refcheck.llm.structured import LLMCallResult
from refcheck.llm.usage import TokenUsage
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import EvidenceQuote, JudgeOutput
from refcheck.stages.verify_claims.layers import LayerResult, PackKind, ValidatedQuote
from refcheck.stages.verify_claims.retriever import EvidencePack, Passage
from refcheck.stages.verify_claims.screen import ScreenResult
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.verifier_helpers import PairContext, build_pair_context

ABSTRACT = (
    "Background: inflammation drives tissue damage. Methods: we randomised 120 mice to "
    "drug X or vehicle. Results: drug X reduced inflammation markers in treated mice "
    "compared with vehicle. Conclusion: drug X is anti-inflammatory in mice."
)
RESULT_TEXT = "Drug X reduced IL-6 levels by 40% compared with vehicle (p < 0.01)."
FULL_TEXT = (
    "Abstract\n\n" + ABSTRACT + "\n\nIntroduction\n\n"
    + "Inflammation is a common pathway in many diseases and has been studied widely. " * 12
    + "\n\nResults\n\n" + RESULT_TEXT + " "
    + "Body weight did not differ between the groups during the study period. " * 8
    + "\n\nDiscussion\n\nThese results suggest drug X has anti-inflammatory effects in mice. "
    + "Further work is needed to confirm these findings in other models. " * 6
)


def make_claim(text: str = "Drug X reduces inflammation in mice.", claim_id: int = 1,
               claim_type: str = "factual", co_cited: int = 1) -> Claim:
    return Claim(id=claim_id, extracted_claim=text, manuscript_text=text + " [1]",
                 paragraph_text="Inflammation matters. " + text + " [1] More text.",
                 claim_type=claim_type,  # type: ignore[arg-type]
                 reference_ids=[1], co_cited_count=co_cited)


def make_ref(ref_id: int = 1, **fields: object) -> Reference:
    base: dict[str, object] = {"id": ref_id, "title": "Drug X in mice",
                               "authors": ["Smith J", "Doe A"], "year": 2020,
                               "source_status": "found"}
    base.update(fields)
    return Reference.model_validate(base)


def make_pack(texts: Sequence[str] = (RESULT_TEXT,), coverage: str = "full_text",
              abstract: str | None = ABSTRACT) -> EvidencePack:
    passages: list[Passage] = []
    if abstract:
        passages.append(Passage(id="A", unit_idx=0, section="Abstract", kind="abstract",
                                text=abstract))
    for i, text in enumerate(texts, start=1):
        passages.append(Passage(id=f"P{i}", unit_idx=i, section="Results", page=4, text=text))
    return EvidencePack(passages=passages, coverage=coverage,  # type: ignore[arg-type]
                        total_tokens=sum(len(p.text) // 4 for p in passages),
                        retrieval_version="test")


def make_ctx(claim: Claim | None = None, coverage: str = "full_text",
             pack: EvidencePack | None = None) -> PairContext:
    claim = claim or make_claim()
    ref = make_ref()
    if coverage == "full_text":
        doc = build_source_document(ref.id, FULL_TEXT, abstract_text=ABSTRACT)
    else:
        doc = build_abstract_document(ref.id, ABSTRACT)
    pack = pack or make_pack(coverage=coverage, texts=() if coverage != "full_text"
                             else (RESULT_TEXT,))
    ctx = build_pair_context(claim, ref, doc, pack)
    ctx.expanded = pack
    return ctx


def judge_output(verdict: str = "supported", quotes: Sequence[tuple[str, str, str]] = (),
                 severity: str = "none", missing: str | None = None,
                 confidence: float = 0.9) -> JudgeOutput:
    return JudgeOutput.model_validate({
        "verdict": verdict, "severity": severity, "problem_type": "none",
        "confidence": confidence, "explanation": f"Explanation for {verdict} [P1].",
        "missing": missing,
        "quotes": [EvidenceQuote(passage_id=p, text=t, role=r)  # type: ignore[arg-type]
                   for p, t, r in quotes],
    })


_PACK_KIND: dict[str, PackKind] = {"verifier": "standard", "verifier_recheck": "recheck"}


def layer(name: str, verdict: str | None = "supported", supports: bool = True,
          role_quote: str = "supports", severity: str = "none", provider: str = "openai",
          model_id: str = "gpt-6-luna", missing: str | None = None,
          cost: float = 0.001, error: str | None = None) -> LayerResult:
    """A finished LayerResult (validated quotes already decided)."""
    role = {"verifier_expanded": "verifier", "verifier_recheck": "verifier"}.get(name, name)
    if error is not None or verdict is None:
        return LayerResult(layer=name, role=role, error=error or "transient: boom",  # type: ignore[arg-type]
                           error_kind="transient")
    quotes = [ValidatedQuote(passage_id="P1", text=RESULT_TEXT, role=role_quote,
                             similarity=1.0)] if supports else []
    out = judge_output(verdict, [(q.passage_id, q.text, q.role) for q in quotes], severity,
                       missing)
    return LayerResult(layer=name, role=role, output=out, validated_quotes=quotes,  # type: ignore[arg-type]
                       model_id=model_id, model_display=model_id, provider=provider,
                       cost_usd=cost, latency_ms=100,
                       pack_kind=_PACK_KIND.get(name, "expanded"))


def screen(s: float = 0.99, conflicts: float = 0.0, topic: float = 1.0,
           injection: float = 0.0, refused: Sequence[str] = ()) -> ScreenResult:
    probs = {"topic_match": topic, "finding_stated": s, "evidence_sufficient": s,
             "finding_conflicts": conflicts, "claim_overreaches": 0.0,
             "contains_instructions": injection}
    for name in refused:
        probs.pop(name, None)
    return ScreenResult(probs=probs, refused=list(refused), s=min(s, topic, 1 - conflicts),
                        p_problem=1 - min(s, topic, 1 - conflicts), model="gpt-6-luna-decisions",
                        model_display="Decisions API · gpt-6-luna", latency_ms=150,
                        cost_usd=0.0005)


def llm_result(output: JudgeOutput, model_id: str = "gpt-6-luna",
               provider: str = "openai") -> LLMCallResult[JudgeOutput]:
    return LLMCallResult[JudgeOutput](
        content=output.model_dump_json(), parsed=output, model_id=model_id,
        litellm_id=f"{provider}/{model_id}", provider=provider, display_name=model_id,
        usage=TokenUsage(input_tokens=1000, output_tokens=200), latency_ms=50,
        cost_usd=0.0002)


LayerScript = Callable[[str], LayerResult]
