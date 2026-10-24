"""Builders for the co-cited union check tests (synthetic texts, no network)."""

import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from unittest.mock import patch

from refcheck.llm.structured import LLMCallResult
from refcheck.llm.usage import TokenUsage
from refcheck.models.adjudication import CocitedCheck, CocitedOutput
from refcheck.stages.verify_claims.cocited import CoCitedRef
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_fakes import COCITED_ABSTRACT, ctx_with_cocited

UNION_PATH = "refcheck.stages.verify_claims.cocited_union.call_llm_raw"
# Stated only in the full text of co-cited reference 2 (not in its abstract).
REF2_QUOTE = "Gel Q increased capillary density in healed rat skin compared with saline"
REF2_FILLER = "Wound closure was followed with digital photographs every second day. "
REF2_TEXT = ("Abstract\n\n" + COCITED_ABSTRACT + "\n\nIntroduction\n\n"
             + "Skin wounds heal through overlapping phases of repair. " * 10
             + "\n\nResults\n\n" + REF2_QUOTE + ". " + REF2_FILLER * 8
             + "\n\nDiscussion\n\nGel Q may support repair of skin wounds. " * 3)
# Co-cited reference 3: abstract only.
REF3_QUOTE = "Drug X lowered IL-6 levels in human plasma after one dose"
REF3_ABSTRACT = REF3_QUOTE + ". The effect was seen in all twelve volunteers."
E_ABSENT = "capillary density in healed skin"  # stated by reference 2 only
UnionResponder = Callable[[list[str], Mapping[str, object]], CocitedOutput | Exception]


def ref2_doc() -> SourceDocument:
    return build_source_document(2, REF2_TEXT, abstract_text=COCITED_ABSTRACT)


def ctx_with_union(coverage: str = "full_text") -> PairContext:
    """ctx_with_cocited + the loaded sources of co-cited references 2 (full text) and 3."""
    ctx = ctx_with_cocited(coverage)
    ctx.co_cited = [*ctx.co_cited[:1], CoCitedRef(number=3, title="Drug X in humans")]
    ctx.co_cited_docs = {2: ref2_doc(), 3: build_abstract_document(3, REF3_ABSTRACT)}
    return ctx


def passage_with(variables: Mapping[str, object], text: str) -> str | None:
    """Id of the shown co-cited passage line containing ``text``."""
    for src in variables["sources"]:  # type: ignore[attr-defined]
        for line in src["passages"]:
            if text.lower() in line.lower():
                found = re.match(r"^\[([^\]]+)\]", line)
                return found.group(1) if found else None
    return None


def union_output(elements: list[str], answers: list[tuple[str, str | None, str | None]],
                 ) -> CocitedOutput:
    return CocitedOutput(elements=[
        CocitedCheck(element=e, category=a[0], passage_id=a[1], quote=a[2],  # type: ignore[arg-type]
                     note="synthetic") for e, a in zip(elements, answers, strict=False)],
        explanation="Synthetic union check.")


def cites(quote: str, find: str | None = None, passage: str | None = None) -> UnionResponder:
    """Every element "cocited" with ``quote``, from the passage containing ``find``
    (default: the quote itself) or the given ``passage`` id."""
    def respond(elements: list[str], variables: Mapping[str, object]) -> CocitedOutput:
        pid = passage or passage_with(variables, find or quote)
        return union_output(elements, [("cocited", pid, quote)] * len(elements))
    return respond


def fake_union(respond: UnionResponder, calls: list[dict[str, object]] | None = None,
               ) -> AbstractContextManager[object]:
    """Patch the union check's call; ``respond`` gets the elements and the variables."""
    async def fake(template: str, variables: dict[str, object], output_model: type,
                   **kwargs: object) -> LLMCallResult[CocitedOutput]:
        if calls is not None:
            calls.append({"template": template, "variables": variables, **kwargs})
        answer = respond([str(e) for e in variables["elements"]], variables)  # type: ignore[attr-defined]
        if isinstance(answer, Exception):
            raise answer
        return LLMCallResult[CocitedOutput](
            content=answer.model_dump_json(), parsed=answer, model_id="claude-haiku-5-5",
            litellm_id="anthropic/claude-haiku-5-5", provider="anthropic",
            display_name="claude-haiku-5-5",
            usage=TokenUsage(input_tokens=2400, output_tokens=90), latency_ms=30,
            cost_usd=0.0003)

    return patch(UNION_PATH, fake)
