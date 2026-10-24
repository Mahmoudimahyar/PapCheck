"""--dry-run for run_eval.py: the whole eval path with canned layer answers, no API calls.

Smoke-tests datasets, source loading, retrieval (BM25 only), prompt rendering
(system + user templates are rendered for every call), routing incl. the
evidence re-check, result mapping and metrics without any paid call: no
preflight, no screen, no embeddings, and every chat layer gets a canned
JudgeOutput. First-pass verifier calls answer partially_supported with one
unsupported element (so the re-check path runs); re-check, expanded, judge and
confirm calls answer supported. The element adjudicator (abstract-only partials)
answers "stated" for the first element, quoting the first passage (so the quote
validation runs), and "absent" for the others. A pair with co-cited references gets
every verifier answer partial with two elements (the claim's last and first words), so
the adjudicator leaves one "absent" and the co-cited union check runs: it answers
"cocited" for the first element, quoting the co-cited window that shares the most
words with it, and "absent" for the others. Verdicts are meaningless; costs are $0.
"""

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from unittest.mock import patch

from eval_cli import parse_args
from eval_models import EvalConfig
from pydantic import BaseModel

from refcheck.llm.structured import LLMCallResult
from refcheck.llm.templates import render_template
from refcheck.llm.usage import TokenUsage
from refcheck.models.adjudication import (
    AdjudicateOutput,
    CocitedCheck,
    CocitedOutput,
    ElementCheck,
)
from refcheck.models.verification import EvidenceQuote, JudgeOutput
from refcheck.stages.verify_claims import (
    adjudicate,
    cocited_union,
    layers,
    retrieval_embed,
    screen,
)
from refcheck.stages.verify_claims.bm25 import tokenize
from refcheck.stages.verify_claims.calibration import ScreenThresholds

DRY_RUN_FLAG = "--dry-run"
DRY_MODEL = "dry-run"
_PASSAGE_RE = re.compile(r"^\[(?P<id>[A-Z]\d*)\]\s(?:Abstract:\s|\([^)]*\)\s)?(?P<text>.+)$",
                         re.MULTILINE)
_UNION_LINE_RE = re.compile(r"^\[(?P<id>[^\]]+)\] \((?P<label>.*?)\) (?P<text>.+)$")
_QUOTE_WORDS = 12


def parse_cli(argv: list[str] | None, description: str | None) -> EvalConfig:
    """parse_args plus --dry-run (forces BM25-only, no screen, fresh cache)."""
    args = list(argv or [])
    dry = DRY_RUN_FLAG in args
    cfg = parse_args([a for a in args if a != DRY_RUN_FLAG], description=description)
    if not dry:
        return cfg
    return cfg.model_copy(update={"dry_run": True, "use_embeddings": False,
                                  "with_screen": False, "reuse_cache": False})


def dry_run_roles(cfg: EvalConfig, thresholds: ScreenThresholds,
                  ) -> tuple[ScreenThresholds, dict[str, str | None], dict[str, str | None]]:
    """check_roles stand-in: no preflight call, screen disabled."""
    roles = {"verifier": DRY_MODEL, "judge": DRY_MODEL, "confirm": DRY_MODEL,
             "adjudicator": DRY_MODEL}
    return thresholds.model_copy(update={"enabled": False}), dict(roles), {}


def _first_quote(variables: Mapping[str, object]) -> tuple[str, str] | None:
    """(passage id, its first words) of the first passage shown."""
    match = _PASSAGE_RE.search(str(variables.get("passages", "")))
    if match is None:
        return None
    return match.group("id"), " ".join(match.group("text").split()[:_QUOTE_WORDS])


def canned_adjudication(variables: Mapping[str, object]) -> AdjudicateOutput:
    """First element "stated" (first passage quoted), the others "absent"."""
    raw = variables.get("elements")
    elements = [str(e) for e in raw] if isinstance(raw, list) else []
    quote = _first_quote(variables)
    checks = [ElementCheck(element=e, category="stated" if i == 0 and quote else "absent",
                           passage_id=quote[0] if i == 0 and quote else None,
                           quote=quote[1] if i == 0 and quote else None,
                           note="Dry run: canned answer.") for i, e in enumerate(elements)]
    return AdjudicateOutput(elements=checks, explanation="Dry run: canned answer.")


def _union_passages(variables: Mapping[str, object]) -> Iterator[tuple[str, list[str]]]:
    """(passage id, words) of each co-cited passage shown, in order."""
    sources = variables.get("sources")
    for src in sources if isinstance(sources, list) else []:
        lines = src.get("passages") if isinstance(src, dict) else None
        for line in lines if isinstance(lines, list) else []:
            if (match := _UNION_LINE_RE.match(str(line))) is not None:
                yield match.group("id"), match.group("text").split()


def _best_union_quote(variables: Mapping[str, object], element: str) -> tuple[str, str] | None:
    """(passage id, _QUOTE_WORDS words) of the co-cited window sharing the most content
    words with ``element`` (the earliest on ties), so the relevance rule can pass."""
    wanted = set(tokenize(element))
    best: tuple[int, str, str] | None = None
    for pid, words in _union_passages(variables):
        for start in range(max(len(words) - _QUOTE_WORDS, 0) + 1):
            span = " ".join(words[start:start + _QUOTE_WORDS])
            score = len(wanted & set(tokenize(span)))
            if best is None or score > best[0]:
                best = (score, pid, span)
    return None if best is None else (best[1], best[2])


def canned_union(variables: Mapping[str, object]) -> CocitedOutput:
    """First element "cocited" (best-matching co-cited window quoted), the others "absent"."""
    raw = variables.get("elements")
    elements = [str(e) for e in raw] if isinstance(raw, list) else []
    quote = _best_union_quote(variables, elements[0]) if elements else None
    checks = [CocitedCheck(element=e, category="cocited" if i == 0 and quote else "absent",
                           passage_id=quote[0] if i == 0 and quote else None,
                           quote=quote[1] if i == 0 and quote else None,
                           note="Dry run: canned answer.") for i, e in enumerate(elements)]
    return CocitedOutput(elements=checks, explanation="Dry run: canned answer.")


def canned_output(variables: Mapping[str, object]) -> JudgeOutput:
    """partially_supported + one element on a first pass (every pass, two elements, with
    co-cited references), supported otherwise."""
    found = _first_quote(variables)
    words = str(variables.get("cited_for") or variables.get("claim") or "").split()
    quotes = [EvidenceQuote(passage_id=found[0], role="supports", text=found[1],
                            states=" ".join(words[:6]))] if found else []
    shared = bool(variables.get("co_cited"))
    first = variables.get("pack_kind") == "standard" or shared
    elements = [" ".join(words[-6:])] + ([" ".join(words[:6])] if shared else []) \
        if first and words else []
    return JudgeOutput(
        verdict="partially_supported" if first else "supported",
        severity="minor" if first else "none",
        problem_type="compound_part_only" if first else "none", confidence=0.5,
        quotes=quotes, explanation="Dry run: canned answer [no model call].",
        missing=None, partial_type="missing_element" if first else "none",
        unsupported_elements=elements)


async def fake_call_llm_raw(template: str, variables: Mapping[str, object],
                            output_model: type[BaseModel], **kwargs: object,
                            ) -> LLMCallResult[BaseModel]:
    """Render both prompts (catches template errors), then answer from canned_output."""
    user = render_template(template, dict(variables))
    system_template = str(kwargs.get("system_template") or template)
    raw_system = kwargs.get("system_variables")
    system_vars = dict(raw_system) if isinstance(raw_system, Mapping) else {}
    system = render_template(system_template, system_vars)
    output: BaseModel = (canned_adjudication(variables) if output_model is AdjudicateOutput
                         else canned_union(variables) if output_model is CocitedOutput
                         else output_model.model_validate(canned_output(variables).model_dump()))
    usage = TokenUsage(input_tokens=(len(user) + len(system)) // 4, output_tokens=50)
    return LLMCallResult[BaseModel](
        content=output.model_dump_json(), parsed=output, usage=usage, model_id=DRY_MODEL,
        latency_ms=1,  # 0 would read as an LLM-cache hit in the run report
        litellm_id=DRY_MODEL, provider="dry-run", display_name="Dry run (no API call)")


async def no_api_call(*args: object, **kwargs: object) -> None:
    """Embedding / Decisions stand-in: a dry run never reaches a paid API."""
    raise RuntimeError("dry run: API calls are disabled")


@contextmanager
def dry_run_scope(enabled: bool) -> Iterator[None]:
    """Chat layers -> fake_call_llm_raw; embeddings and the screen fail fast (BM25 fallback)."""
    if not enabled:
        yield
        return
    with (patch.object(layers, "call_llm_raw", fake_call_llm_raw),
          patch.object(adjudicate, "call_llm_raw", fake_call_llm_raw),
          patch.object(cocited_union, "call_llm_raw", fake_call_llm_raw),
          patch.object(retrieval_embed, "embed_texts", no_api_call),
          patch.object(screen, "decide", no_api_call)):
        yield
