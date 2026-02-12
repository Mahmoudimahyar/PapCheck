"""Canary tests for LLM grounding and anti-hallucination.

These tests make REAL LLM calls to verify the model reads provided text
rather than relying on training data. Skip gracefully if no API key.
"""

import os

import pytest

from refcheck.llm.client import call_llm
from refcheck.models.verification import VerificationResult

_HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
_SKIP_REASON = "ANTHROPIC_API_KEY not set"


@pytest.mark.canary
@pytest.mark.live
@pytest.mark.skipif(not _HAS_API_KEY, reason=_SKIP_REASON)
class TestLLMGrounding:
    """Canary tests that verify the LLM reads provided text, not memory.

    Uses class-scoped event loop to prevent litellm's cached httpx client
    from referencing a closed event loop between tests (Windows issue).
    """

    @pytest.mark.asyncio(loop_scope="class")
    async def test_number_modification(self) -> None:
        """LLM should report the MODIFIED number from source, not the real one.

        Real finding: aspirin reduces stroke risk by ~22%.
        We provide text saying 47%. LLM must report 47%.
        """
        source_text = (
            "Our meta-analysis of 12 randomized controlled trials found that "
            "aspirin therapy was associated with a 47% relative risk reduction "
            "in ischemic stroke (RR 0.53, 95% CI 0.41-0.68, p < 0.001). "
            "The number needed to treat was 125 over 5 years."
        )
        result = await call_llm(
            template="grounded_verification",
            variables={
                "claim": "Aspirin reduces stroke risk by 47%",
                "claim_type": "factual",
                "source_sections": source_text,
                "reference_title": "Aspirin and Stroke Prevention Meta-Analysis",
                "reference_authors": "Test Authors",
            },
            output_model=VerificationResult,
        )
        # LLM should say supported (because source says 47%)
        assert result.verdict in ("supported", "partially_supported")
        assert "47" in " ".join(result.evidence_quotes + [result.reasoning])

    @pytest.mark.asyncio(loop_scope="class")
    async def test_author_swap(self) -> None:
        """LLM should use the provided text's attribution, not real-world knowledge.

        Real: CRISPR-Cas9 was developed by Doudna and Charpentier.
        We provide text crediting different authors.
        """
        source_text = (
            "The CRISPR-Cas9 gene editing system was first developed by "
            "Dr. Robert Johnson and Dr. Maria Santos at the University of "
            "Melbourne in 2010. Their pioneering work demonstrated targeted "
            "genome editing in mammalian cells."
        )
        result = await call_llm(
            template="grounded_verification",
            variables={
                "claim": "CRISPR-Cas9 was developed by Johnson and Santos",
                "claim_type": "attribution",
                "source_sections": source_text,
                "reference_title": "Origins of CRISPR Technology",
                "reference_authors": "Johnson R, Santos M",
            },
            output_model=VerificationResult,
        )
        assert result.verdict == "supported"

    @pytest.mark.asyncio(loop_scope="class")
    async def test_negation(self) -> None:
        """LLM should report what provided text says, even if opposite of reality.

        Real: Vaccines are effective against measles.
        We provide text claiming otherwise (for testing only).
        """
        source_text = (
            "Our comprehensive review of 50 clinical trials found that "
            "the standard measles vaccine showed no statistically significant "
            "reduction in measles incidence (pooled RR 0.97, 95% CI 0.88-1.07, "
            "p = 0.54). The vaccine appeared to have minimal clinical benefit."
        )
        result = await call_llm(
            template="grounded_verification",
            variables={
                "claim": "Measles vaccine showed no significant reduction in measles incidence",
                "claim_type": "factual",
                "source_sections": source_text,
                "reference_title": "Vaccine Efficacy Review",
                "reference_authors": "Test Authors",
            },
            output_model=VerificationResult,
        )
        # LLM should agree with the provided text
        assert result.verdict in ("supported", "partially_supported")

    @pytest.mark.asyncio(loop_scope="class")
    async def test_absent_claim(self) -> None:
        """LLM should say cannot_verify for a claim NOT in the provided text."""
        source_text = (
            "This study evaluated the pharmacokinetics of Drug Y in healthy "
            "volunteers. Peak plasma concentration was reached at 2 hours. "
            "The half-life was 6.5 hours. No serious adverse events occurred."
        )
        result = await call_llm(
            template="grounded_verification",
            variables={
                "claim": "Drug Y reduces tumor size by 40% in cancer patients",
                "claim_type": "factual",
                "source_sections": source_text,
                "reference_title": "Drug Y Pharmacokinetics Study",
                "reference_authors": "Test Authors",
            },
            output_model=VerificationResult,
        )
        # Source text says nothing about tumor size or cancer
        assert result.verdict in ("cannot_verify", "not_supported")
