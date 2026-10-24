"""Offline fakes for the V5.4 partial sub-type end-to-end tests (synthetic data only).

Only the LLM call (layers.call_llm_raw), the role preflight, the screen and the
embeddings are mocked (``scripted``); retrieval, the cascade, the evidence
re-check, co-cited plumbing and result mapping are the real code. The scripted
answers depend on the source, the role and the pack kind:

(a) ref 1: the verifier calls an element absent; the targeted re-check finds it in
    a part of the paper the standard pack left out -> supported + evidence_recheck;
(b) ref 2: the rest of the sentence is ref 3's share (ref 3 has an abstract) ->
    supported + cocited_share and the citation-placement note;
(c) ref 4: a genuine scope_overgeneralized partial.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import JudgeOutput, VerificationResult
from refcheck.stages.verify_claims import verify_claims
from refcheck.stages.verify_claims.retrieval_embed import clear_embedding_cache
from refcheck.stages.verify_claims.source_document import _cached_pdf_document
from tests.unit.test_verifier import _ROLE_MODEL, Fakes
from tests.unit.verify_fakes import llm_result, make_ref

_V = "refcheck.stages.verify_claims"
TITLES = {1: "Gel Q in arthritic mice", 2: "Hydrogel R in rat kidneys",
          3: "Hydrogel R in pig livers", 4: "Scaffold S in rat femoral defects"}
SWELLING = "Gel Q reduced paw swelling in arthritic mice by 35% compared with vehicle."
SAFETY = "No animal lost weight and no adverse events were recorded during dosing."
KIDNEY = "Hydrogel R lowered fibrosis in rat kidneys after twelve weeks."
LIMB = "Scaffold S restored limb function in rats with femoral defects."
LIVER = "Hydrogel R lowered fibrosis in pig livers."
SENTENCE_B = "Hydrogel R lowered fibrosis in rat kidneys [2] and pig livers [3]."
SCOPE = "in human patients"


def _filler(topic: str, n: int) -> str:
    return " ".join(f"In cohort {i}, {topic} at dose {i} mg/kg was compared with vehicle, and "
                    f"sample set {i} was scored blind by two assessors." for i in range(1, n + 1))


def _pdf(path: Path, sections: list[tuple[str, str]]) -> Path:
    """A text PDF, one page per ~2,000 characters so nothing overflows a text box."""
    text = "\n\n".join(f"{head}\n\n{body}" for head, body in sections)
    doc = fitz.open()
    for start in range(0, len(text), 2000):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(36, 36, 576, 806), text[start:start + 2000], fontsize=8)
    doc.save(str(path))
    doc.close()
    return path


def references(tmp: Path) -> list[Reference]:
    long_results = _filler("gel Q reduced paw swelling in arthritic mice", 110)
    return [
        make_ref(1, title=TITLES[1], pdf_path=_pdf(tmp / "q.pdf", [
            ("Results", f"{SWELLING} {long_results}"),
            ("Safety", f"{SAFETY} Animals were housed in pairs with free access to chow.")])),
        make_ref(2, title=TITLES[2], pdf_path=_pdf(tmp / "r.pdf", [
            ("Results", f"{KIDNEY} {_filler('renal collagen staining', 12)}")])),
        make_ref(3, title=TITLES[3], abstract_text=LIVER,
                 abstract_source="pubmed"),
        make_ref(4, title=TITLES[4], pdf_path=_pdf(tmp / "s.pdf", [
            ("Results", f"{LIMB} {_filler('scaffold S bridged the femoral gap', 12)}")])),
    ]


def claims() -> list[Claim]:
    def claim(cid: int, text: str, ref: int, sentence: str = "", co: int = 1) -> Claim:
        sentence = sentence or f"{text} [{ref}]"
        return Claim(id=cid, extracted_claim=text, manuscript_text=sentence,
                     paragraph_text=f"Context. {sentence} More context.", claim_type="factual",
                     reference_ids=[ref], co_cited_count=co)
    shared = "Hydrogel R lowered fibrosis in rat kidneys and pig livers."
    return [claim(1, "Gel Q reduced paw swelling in arthritic mice and was well tolerated.", 1),
            claim(2, shared, 2, SENTENCE_B, 2), claim(3, shared, 3, SENTENCE_B, 2),
            claim(4, f"Scaffold S restores limb function {SCOPE}.", 4)]


def _out(verdict: str, quote: tuple[str, str], **fields: object) -> JudgeOutput:
    return JudgeOutput.model_validate({
        "verdict": verdict, "severity": fields.pop("severity", "none"), "problem_type": "none",
        "confidence": 0.85, "explanation": f"Synthetic {verdict} [{quote[0]}].",
        "missing": fields.pop("missing", None),
        "quotes": [{"passage_id": quote[0], "text": quote[1], "role": "supports"}], **fields})


def _answer(title: str, role: str, pack_kind: str, passages: str) -> JudgeOutput:
    def pid(text: str) -> str:  # the id of the passage that shows ``text``
        line = next(ln for ln in passages.split("\n[") if text[:30] in ln)
        return line.lstrip("[").split("]")[0]
    if title == TITLES[1] and pack_kind == "recheck":
        return _out("supported", (pid(SAFETY), SAFETY))
    if title == TITLES[1]:
        return _out("partially_supported", (pid(SWELLING), SWELLING), severity="minor",
                    partial_type="missing_element",
                    unsupported_elements=["well tolerated with no adverse events"])
    if title == TITLES[2]:
        return _out("supported", (pid(KIDNEY), KIDNEY), benign_notes=["cocited_share"],
                    dismissed=[{"element": "pig livers", "guard": "cocited_share",
                                "passage_id": "3", "quote": LIVER}])
    if title == TITLES[3]:
        return _out("supported", ("A", LIVER))
    return _out("partially_supported", (pid(LIMB), LIMB), severity="major",
                partial_type="scope_overgeneralized", unsupported_elements=[SCOPE])


class ScriptedFakes(Fakes):
    """Answers by source, role and pack kind (pairs run concurrently)."""

    async def _llm(self, template: str, variables: object, output_model: object,
                   **kwargs: object) -> object:
        assert isinstance(variables, dict)
        role = str(kwargs["role"])
        out = _answer(variables["source_title"], role, variables["pack_kind"],
                      variables["passages"])
        model_id, provider = _ROLE_MODEL.get(role, ("gpt-6-luna", "openai"))
        return llm_result(out, model_id, provider)

    def calls(self, ref_id: int) -> list[dict[str, object]]:
        return [{**c.args[1], "role": c.kwargs["role"], "system": c.kwargs["system_variables"]}
                for c in self.llm.await_args_list if c.args[1]["source_title"] == TITLES[ref_id]]


RunResult = tuple[ScriptedFakes, list[Reference], dict[int, VerificationResult]]


@contextmanager
def scripted(monkeypatch: pytest.MonkeyPatch) -> Iterator[ScriptedFakes]:
    """ScriptedFakes patched in for one test (screen off, no OCR, no embeddings)."""
    for name in ("REFCHECK_PRIVACY_PROFILE", "REFCHECK_SCREEN_T_ACCEPT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REFCHECK_SCREEN_ENABLED", "false")  # the screen is not under test
    monkeypatch.setenv("REFCHECK_OCR", "0")
    clear_embedding_cache()
    _cached_pdf_document.cache_clear()
    f = ScriptedFakes()
    with patch(f"{_V}.verifier.preflight", f.preflight), patch(f"{_V}.screen.decide", f.decide), \
            patch(f"{_V}.layers.call_llm_raw", f.llm), \
            patch(f"{_V}.retrieval_embed.embed_texts", AsyncMock(side_effect=RuntimeError("x"))):
        yield f


async def run_all(fakes: ScriptedFakes, tmp_path: Path) -> RunResult:
    """verify_claims over the scripted manuscript: (fakes, references, results by ref)."""
    refs = references(tmp_path)
    results = await verify_claims(claims(), refs)
    return fakes, refs, {r.reference_id: r for r in results}
