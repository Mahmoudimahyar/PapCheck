"""Canary tests for LLM grounding and anti-hallucination (V5 verifier prompt).

These tests make REAL LLM calls (role "verifier", prompt verify_claim) to check
that the model reads the provided passages rather than relying on training
data. Skipped gracefully when no provider key is set.
"""

import os

import pytest

from refcheck.llm.client import call_llm
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables

_KEY_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_BACKUP")
_HAS_API_KEY = any(os.environ.get(name) for name in _KEY_VARS)
_SKIP_REASON = "no OpenAI/Anthropic API key set"


async def _verify(claim: str, passage: str, title: str, claim_type: str = "factual",
                  ) -> JudgeOutput:
    variables: dict[str, object] = {
        "section": "user", "passages": f"[P1] (Results, p.3) {passage}",
        "coverage": "full_text", "pack_kind": "standard", "source_title": title,
        "source_authors": "Test Authors", "source_year": 2020, "claim": claim,
        "claim_type": claim_type, "sentence": claim, "prev_sentence": "", "paragraph": "",
        "section_heading": "Introduction", "co_cited_count": 1,
    }
    return await call_llm("verify_claim", variables, JudgeOutput, role="verifier",
                          use_cache=False, task="canary",
                          system_template="verify_claim",
                          system_variables=system_variables())


@pytest.mark.canary
@pytest.mark.live
@pytest.mark.skipif(not _HAS_API_KEY, reason=_SKIP_REASON)
class TestLLMGrounding:
    """The verifier must follow the provided passages, not its memory."""

    @pytest.mark.asyncio(loop_scope="class")
    async def test_number_modification(self) -> None:
        """Real finding is ~22%; the passage says 47%, so 47% is supported."""
        result = await _verify(
            "Aspirin reduces stroke risk by 47%",
            "Our meta-analysis of 12 randomized controlled trials found that aspirin therapy "
            "was associated with a 47% relative risk reduction in ischemic stroke (RR 0.53, "
            "95% CI 0.41-0.68, p < 0.001).",
            "Aspirin and Stroke Prevention Meta-Analysis",
        )
        assert result.verdict in ("supported", "partially_supported")
        assert "47" in " ".join([q.text for q in result.quotes] + [result.explanation])

    @pytest.mark.asyncio(loop_scope="class")
    async def test_author_swap(self) -> None:
        """Attribution follows the passage, not real-world knowledge."""
        result = await _verify(
            "CRISPR-Cas9 was developed by Johnson and Santos",
            "The CRISPR-Cas9 gene editing system was first developed by Dr. Robert Johnson "
            "and Dr. Maria Santos at the University of Melbourne in 2010.",
            "Origins of CRISPR Technology", claim_type="attribution",
        )
        assert result.verdict == "supported"

    @pytest.mark.asyncio(loop_scope="class")
    async def test_negation(self) -> None:
        """A counterfactual null finding in the passage supports the null claim."""
        result = await _verify(
            "Measles vaccine showed no significant reduction in measles incidence",
            "Our review of 50 clinical trials found that the standard measles vaccine showed "
            "no statistically significant reduction in measles incidence (pooled RR 0.97, "
            "95% CI 0.88-1.07, p = 0.54).",
            "Vaccine Efficacy Review",
        )
        assert result.verdict in ("supported", "partially_supported")

    @pytest.mark.asyncio(loop_scope="class")
    async def test_absent_claim(self) -> None:
        """A claim absent from the passages is not supported."""
        result = await _verify(
            "Drug Y reduces tumor size by 40% in cancer patients",
            "This study evaluated the pharmacokinetics of Drug Y in healthy volunteers. "
            "Peak plasma concentration was reached at 2 hours. The half-life was 6.5 hours.",
            "Drug Y Pharmacokinetics Study",
        )
        assert result.verdict in ("not_supported", "insufficient_evidence", "not_relevant")
