"""Evidence-pack models and rendering (re-exported by retriever)."""

from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.source_models import ChunkKind, Coverage

_SECTION_DISPLAY = {"other": "Other"}


class Passage(BaseModel):
    """One labelled passage of an evidence pack ("A" = abstract, "P1".. = windows)."""

    id: str
    unit_idx: int  # chunk idx of the best-ranked unit in this passage
    unit_idxs: list[int] = Field(default_factory=list)  # all chunks merged into it
    section: str  # Abstract/Introduction/Methods/Results/Discussion/Conclusion/other
    page: int | None = None
    kind: ChunkKind = "window"
    text: str
    score: float = 0.0  # fused retrieval score of the best unit; 0.0 for the abstract
    n_tokens: int = 0


class EvidencePack(BaseModel):
    """Retrieved passages for one claim, best first, within a token budget."""

    passages: list[Passage] = Field(default_factory=list)
    coverage: Coverage
    total_tokens: int = 0
    retrieval_version: str
    used_embeddings: bool = False
    max_tokens: int = 0
    query: str = ""

    def get(self, passage_id: str) -> Passage | None:
        """Passage by id ("A", "P3"); None when the id is not in the pack."""
        wanted = passage_id.strip().strip("[]").upper()
        return next((p for p in self.passages if p.id.upper() == wanted), None)

    @property
    def joined_text(self) -> str:
        """All passage texts (fallback haystack for quote validation)."""
        return "\n\n".join(p.text for p in self.passages)

    @property
    def is_empty(self) -> bool:
        return not self.passages


def passage_label(passage: Passage) -> str:
    """Heading shown for a passage, e.g. "Results, p.4" or "Abstract"."""
    if passage.id == "A":
        return "Abstract"
    parts = [_SECTION_DISPLAY.get(passage.section, passage.section)]
    if passage.kind == "caption":
        parts.append("figure/table caption")
    if passage.page is not None:
        parts.append(f"p.{passage.page}")
    return ", ".join(parts)


def render_pack(pack: EvidencePack) -> str:
    """Prompt text: "[A] Abstract: …" then "[P1] (Results, p.4) …", one passage per line."""
    lines: list[str] = []
    for passage in pack.passages:
        text = " ".join(passage.text.split())
        if passage.id == "A":
            lines.append(f"[A] Abstract: {text}")
        else:
            lines.append(f"[{passage.id}] ({passage_label(passage)}) {text}")
    return "\n".join(lines)
