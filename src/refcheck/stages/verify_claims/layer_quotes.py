"""Validate a layer's quotes against the evidence pack it saw (re-exported by layers).

V5.6: each quote carries ``states`` (the part of the cited span it states). A
"supports" quote whose ``states`` is explicitly "" is context only (the problem,
aim or design, not the finding). Quotes without the field (older cached outputs,
outputs built in code) count as stating. Contained duplicates are dropped
(``dedupe_contained``: the longer quote is kept).
"""

from pydantic import BaseModel

from refcheck.models.verification import EvidenceQuote, JudgeOutput
from refcheck.stages.verify_claims.quote_validator import (
    DEFAULT_MIN_SIMILARITY,
    normalize_for_match,
    validate_quotes,
)
from refcheck.stages.verify_claims.retriever import EvidencePack

_AFTER_CHARS = 40  # enough for a trailing "[10, 11, 23]" or "(Smith et al., 2019)"


class ValidatedQuote(BaseModel):
    """An LLM quote that was found in the evidence pack."""

    passage_id: str
    text: str
    role: str
    similarity: float = 0.0
    # The matched source text and what directly follows it: models often drop the
    # source's own citation markers ("... [10, 11].") from a quote (secondary-citation check).
    source_span: str = ""
    source_after: str = ""
    states: str | None = None  # V5.6: the cited part it states; None = not given (stating)
    context: str = ""  # why it is context only (never evidence); "" = evidence


def states_nothing(quote: EvidenceQuote) -> bool:
    """A supports quote whose ``states`` was given and is empty (context only)."""
    return (quote.role == "supports" and "states" in quote.model_fields_set
            and not quote.states.strip())


def validate_quote(passage_id: str, text: str, role: str, pack: EvidencePack,
                   min_similarity: float = DEFAULT_MIN_SIMILARITY) -> ValidatedQuote | None:
    """``text`` found in its passage (fallback: the whole pack), else None."""
    passage = pack.get(passage_id)
    haystacks = [passage.text] if passage else []
    haystacks.append(pack.joined_text)  # quote attributed to the wrong passage id
    for haystack in haystacks:
        check = validate_quotes([text], haystack, min_similarity)[0]
        if check.found_in_source:
            start, end = check.char_start or 0, check.char_end or 0
            return ValidatedQuote(
                passage_id=passage_id, text=text, role=role, similarity=check.similarity,
                source_span=haystack[start:end], source_after=haystack[end:end + _AFTER_CHARS])
    return None


def validate_output_quotes(
    output: JudgeOutput, pack: EvidencePack,
) -> tuple[list[ValidatedQuote], list[str]]:
    """Split the layer's quotes into validated / invalid against the pack."""
    validated: list[ValidatedQuote] = []
    invalid: list[str] = []
    for quote in output.quotes:
        found = validate_quote(quote.passage_id, quote.text, quote.role, pack)
        if found is None:
            invalid.append(quote.text)
            continue
        given = "states" in quote.model_fields_set
        validated.append(found.model_copy(update={
            "states": quote.states.strip() if given else None,
            "context": "it states nothing of the cited part" if states_nothing(quote) else ""}))
    return validated, invalid


def dedupe_contained(quotes: list[ValidatedQuote]) -> list[ValidatedQuote]:
    """Drop a quote whose normalised text is contained in another quote of the same role
    (keep the longer; of two equal ones the first). Closing punctuation is ignored: a
    sentence quoted with and without its trailing "(Fig. 2B)." is one quote."""
    norms = [normalize_for_match(q.text)[0].rstrip(" .,;:!?") for q in quotes]

    def covered(i: int) -> bool:
        return any(j != i and quotes[j].role == quotes[i].role and norms[i] in norms[j]
                   and (len(norms[j]) > len(norms[i]) or j < i) for j in range(len(quotes)))

    return [q for i, q in enumerate(quotes) if norms[i] and not covered(i)]


def dedupe_contained_texts(texts: list[str]) -> list[str]:
    """``dedupe_contained`` for plain quote texts (the result's evidence_quotes)."""
    kept = dedupe_contained([ValidatedQuote(passage_id="", text=t, role="") for t in texts])
    return [q.text for q in kept]
