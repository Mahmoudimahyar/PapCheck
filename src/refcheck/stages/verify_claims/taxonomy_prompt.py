"""Partial-verdict taxonomy (prompts/partial_taxonomy.json) as rubric template variables.

The verifier / judge / confirm rubric (verify_claim.md, partial
verify_taxonomy.md) renders the guards, rules R1-R7 and the genuine types
from this data at prompt-build time, so the prompt never drifts from the
taxonomy file. Each type is condensed to its definition head, its "assign
if" decision sentence and its first (synthetic) example.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from refcheck.models.partial_types import GENUINE_PRECEDENCE, LEGACY_FOR_TYPE

TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "prompts" / "partial_taxonomy.json"
# Guards the model applies itself (evidence_gap is the pipeline's evidence re-check).
MODEL_GUARDS: tuple[str, ...] = ("cocited_share", "author_framing_or_example",
                                 "overliteral_wording")
# Guards whose decision rule refers to patterns listed only in their definition.
_FULL_DEFINITION = frozenset({"author_framing_or_example", "overliteral_wording"})
# R2 only defines the gold "misread type" label of supported pairs (eval scoring); the
# model's side of it is benign_notes, so it is left out of the prompt.
LABELLING_RULES = frozenset({"R2"})
_SENTENCE_END_RE = re.compile(r"(?<=\.)\s+(?=[A-Z])")
_HEAD_END_RE = re.compile(r":\s| - |\.\s")
_RULE_ASIDE_RE = re.compile(r"\s*\(R\d:[^()]*(?:\([^()]*\)[^()]*)*\)")  # covered by rules R1-R7


class TaxonomyEntry(BaseModel):
    """One type, condensed for the prompt."""

    id: str
    definition: str  # full definition (guards need their listed patterns)
    head: str  # definition up to its first ":", " - " or sentence end
    rule: str  # the "assign if" sentence of the decision rule
    full: bool = False  # render the full definition (guards with listed patterns)
    severity: str = ""
    example: str = ""


class TaxonomyPrompt(BaseModel):
    """Everything the rubric partial renders."""

    version: str
    evidence_gap: TaxonomyEntry
    guards: list[TaxonomyEntry] = Field(default_factory=list)  # model-applied, in order
    genuine: list[TaxonomyEntry] = Field(default_factory=list)  # precedence order
    rules: dict[str, str] = Field(default_factory=dict)  # R1..R7
    precedence: str = ""  # "tangential_source > ... > certainty_overstated"
    legacy: str = ""  # "tangential_source=not_in_source, ..."


def definition_head(definition: str) -> str:
    """The definition up to its first colon, dash aside or sentence end."""
    match = _HEAD_END_RE.search(definition)
    head = definition[:match.start()] if match else definition
    return head.strip().rstrip(".") + "."


def assign_sentence(rule: str) -> str:
    """The sentence of a decision rule that says when to assign the type."""
    sentences = _SENTENCE_END_RE.split(rule.strip())
    picked = next((s for s in sentences if "assign if" in s.lower()), sentences[0])
    return picked.strip()


def _entry(raw: dict[str, object]) -> TaxonomyEntry:
    examples = raw.get("examples")
    first = examples[0] if isinstance(examples, list) and examples else ""
    severity = _RULE_ASIDE_RE.sub("", str(raw.get("severity", ""))).strip()
    definition = str(raw.get("definition", "")).strip()
    return TaxonomyEntry(
        id=str(raw["id"]), definition=definition, head=definition_head(definition),
        rule=assign_sentence(str(raw.get("decision_rule", ""))),
        full=str(raw["id"]) in _FULL_DEFINITION,
        severity="" if severity in ("none", "major") else severity, example=str(first))


def legacy_hint() -> str:
    """Compact partial_type -> legacy problem_type hint ("..., else not_in_source")."""
    pairs = [f"{t}={tag}" for t, tag in LEGACY_FOR_TYPE.items() if tag != "not_in_source"]
    return ", ".join(pairs) + ", else not_in_source"


@lru_cache(maxsize=1)
def taxonomy_prompt(path: Path = TAXONOMY_PATH) -> TaxonomyPrompt:
    """Load and condense the taxonomy (cached; the file is part of the package)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {str(t["id"]): _entry(t) for t in data["types"]}
    rules = {k: str(v) for k, v in data.get("rules_v1_1", {}).items()
             if re.fullmatch(r"R\d", k) and k not in LABELLING_RULES}
    return TaxonomyPrompt(
        version=str(data.get("version", "")), evidence_gap=by_id["evidence_gap"],
        guards=[by_id[g] for g in MODEL_GUARDS],
        genuine=[by_id[g] for g in GENUINE_PRECEDENCE], rules=rules,
        precedence=" > ".join(GENUINE_PRECEDENCE),
        legacy=legacy_hint())


def system_variables() -> dict[str, object]:
    """System-prompt variables of verify_claim.md / judge_claim.md."""
    return {"section": "system", "taxonomy": taxonomy_prompt()}
