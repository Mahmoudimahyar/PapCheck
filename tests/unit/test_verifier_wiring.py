"""verify_claims wiring of the V5.2 fixes (mocked layers, no network).

M14: a result computed on an abstract that stands in for an unusable PDF must
name the PDF problem (reference_mismatch / pdf_supplement), never the generic
abstract_insufficient and never not_supported. M2: retrieval for a pair leads
with the clause the reference is cited for.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from refcheck.stages.verify_claims import verify_claims
from refcheck.stages.verify_claims.credit import PANEL_PREFIX
from refcheck.stages.verify_claims.retrieval_embed import clear_embedding_cache
from refcheck.stages.verify_claims.retriever import retrieve
from refcheck.stages.verify_claims.source_document import _cached_pdf_document
from tests.unit.credit_fakes import PANEL_B, POE, credit_claim, strip
from tests.unit.test_verifier import Fakes, _pdf
from tests.unit.verify_fakes import ABSTRACT, judge_output, make_claim, make_ref

# Long enough to stand in for an unusable PDF (V5.6: >= 300 characters, several sentences).
FALLBACK_ABSTRACT = ABSTRACT + (" Treated mice kept their body weight and food intake during "
                                "the whole study period.")

_V = "refcheck.stages.verify_claims"
_SUPPLEMENT_TEXT = (
    "Supporting Information\n\nDrug X in mice\n\n"
    + "".join(f"Figure S{i}. Body weight and food intake of the mice in treatment group {i} "
              "measured weekly over the twelve-week study period.\n" for i in range(1, 9))
    + "Table S1. Primer sequences used for qPCR.\n"
)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    for name in ("REFCHECK_SCREEN_ENABLED", "REFCHECK_PRIVACY_PROFILE",
                 "REFCHECK_SCREEN_T_ACCEPT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REFCHECK_SCREEN_CALIBRATION", "does-not-exist.json")
    monkeypatch.setenv("REFCHECK_OCR", "0")
    clear_embedding_cache()
    _cached_pdf_document.cache_clear()
    f = Fakes()
    with patch(f"{_V}.verifier.preflight", f.preflight), patch(f"{_V}.screen.decide", f.decide), \
            patch(f"{_V}.layers.call_llm_raw", f.llm), \
            patch(f"{_V}.retrieval_embed.embed_texts", AsyncMock(side_effect=RuntimeError("x"))):
        yield f


def _supplement_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "paper_si_001.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 560, 800), _SUPPLEMENT_TEXT, fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


async def test_mismatch_fallback_negative_names_the_wrong_pdf(
    fakes: Fakes, tmp_path: Path,
) -> None:
    """Before the wiring this ended as abstract_insufficient, hiding the wrong PDF."""
    fakes.outputs["verifier"] = [judge_output("not_supported", missing="No data.")]
    fakes.outputs["confirm"] = [judge_output("not_supported", missing="No data.")]
    ref = make_ref(pdf_path=_pdf(tmp_path), identity_status="mismatch",
                   abstract_text=FALLBACK_ABSTRACT, abstract_source="pubmed")
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert result.verdict == "cannot_verify"
    assert result.cannot_verify_reason == "reference_mismatch"
    assert result.reasoning.startswith("The attached PDF is a different paper")
    assert result.source_coverage == "abstract_only"


async def test_mismatch_fallback_positive_keeps_label_and_flags_review(
    fakes: Fakes, tmp_path: Path,
) -> None:
    abstract_quote = "drug X reduced inflammation markers in treated mice compared with vehicle"
    fakes.outputs["verifier"] = [judge_output("supported", [("A", abstract_quote, "supports")])]
    ref = make_ref(pdf_path=_pdf(tmp_path), identity_status="mismatch",
                   abstract_text=FALLBACK_ABSTRACT, abstract_source="crossref")
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert result.verdict == "supported" and result.needs_user_review
    assert "different paper" in result.reasoning


async def test_supplement_pdf_falls_back_and_names_the_supplement(
    fakes: Fakes, tmp_path: Path,
) -> None:
    fakes.outputs["verifier"] = [judge_output("not_relevant", missing="Off topic.")]
    fakes.outputs["confirm"] = [judge_output("not_relevant", missing="Off topic.")]
    ref = make_ref(pdf_path=_supplement_pdf(tmp_path), abstract_text=FALLBACK_ABSTRACT)
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert result.verdict == "cannot_verify"
    assert result.cannot_verify_reason == "pdf_supplement"
    assert "supplementary material" in result.reasoning


async def test_retrieval_query_leads_with_cited_clause(fakes: Fakes, tmp_path: Path) -> None:
    """M2: the evidence pack is retrieved for the clause this reference supports."""
    seen: list[str] = []

    async def spy(query: str, *args: object, **kwargs: object) -> object:
        seen.append(query)
        return await retrieve(query, *args, **kwargs)  # type: ignore[arg-type]

    text = "Drug X reduces inflammation in mice and drug Y prolongs survival in rats."
    claim = make_claim(text).model_copy(update={"cited_for": "drug Y prolongs survival in rats"})
    with patch(f"{_V}.verifier.retrieve", spy):
        await verify_claims([claim], [make_ref(pdf_path=_pdf(tmp_path))])
    assert seen and seen[0].startswith("drug Y prolongs survival in rats Drug X")
    assert seen[0].endswith(text)


async def test_retrieval_query_is_the_sentence_when_not_narrowed(
    fakes: Fakes, tmp_path: Path,
) -> None:
    seen: list[str] = []

    async def spy(query: str, *args: object, **kwargs: object) -> object:
        seen.append(query)
        return await retrieve(query, *args, **kwargs)  # type: ignore[arg-type]

    claim = make_claim()
    claim = claim.model_copy(update={"cited_for": claim.extracted_claim})
    with patch(f"{_V}.verifier.retrieve", spy):
        await verify_claims([claim], [make_ref(pdf_path=_pdf(tmp_path))])
    assert seen == ["Drug X reduces inflammation in mice."]


async def test_verifier_sees_the_other_references_of_the_sentence(
    fakes: Fakes, tmp_path: Path,
) -> None:
    """Guard 2 (cocited_share): claims of one sentence share their references."""
    first = make_claim(claim_id=1, co_cited=2)
    second = first.model_copy(update={"id": 2, "reference_ids": [2]})
    other = make_ref(2, title="Drug Y in rats", abstract_text="Drug Y prolonged survival.")
    await verify_claims([first, second], [make_ref(pdf_path=_pdf(tmp_path)), other])
    verifier_calls = [c for c in fakes.llm.await_args_list if c.kwargs["role"] == "verifier"]
    rendered = [c.args[1]["co_cited"] for c in verifier_calls]
    assert [{"number": 2, "title": "Drug Y in rats",
             "abstract": "Drug Y prolonged survival."}] in rendered
    assert "taxonomy" in verifier_calls[0].kwargs["system_variables"]


async def test_retrieval_query_of_a_credit_leads_with_its_panel(fakes: Fakes,
                                                                tmp_path: Path) -> None:
    """V5.6 L1: a figure credit retrieves evidence for the legend panel it closes."""
    seen: list[str] = []

    async def spy(query: str, *args: object, **kwargs: object) -> object:
        seen.append(query)
        return await retrieve(query, *args, **kwargs)  # type: ignore[arg-type]

    with patch(f"{_V}.verifier.retrieve", spy):
        await verify_claims([credit_claim(sentence=POE)], [make_ref(pdf_path=_pdf(tmp_path))])
    assert seen and seen[0].startswith(PANEL_PREFIX + strip(PANEL_B))
