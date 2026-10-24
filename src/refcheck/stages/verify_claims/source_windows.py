"""Sentence splitting and 3-sentence / stride-2 retrieval windows."""

import bisect
import re

from refcheck.stages.verify_claims.source_models import Chunk, estimate_tokens
from refcheck.stages.verify_claims.source_runs import TextRun

WINDOW_SENTENCES = 3
WINDOW_STRIDE = 2
_MAX_SENTENCE_WORDS = 80
_SPLIT_SENTENCE_WORDS = 60
_MIN_SENTENCE_WORDS = 4

_ABBREVIATIONS = frozenset({
    "al", "fig", "figs", "eq", "eqs", "ref", "refs", "eg", "ie", "vs", "approx", "ca", "cf",
    "no", "nos", "vol", "vols", "dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "inc",
    "ltd", "co", "corp", "resp", "suppl", "sect", "sec", "tab", "ch", "ed", "eds", "pp",
    "spp", "sp", "var", "subsp", "nr", "est", "dept", "univ", "viz", "jan", "feb", "mar",
    "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "min", "max", "mol",
    "conc", "temp", "wt", "aff", "gen", "nat", "proc", "sci", "med", "biol", "chem",
})
# Sentence end: terminal punctuation (+ closing quotes/brackets), or a period directly
# followed by a numeric citation ("shown.[12] Next", "shown.12,13 Next").
_BOUNDARY_RE = re.compile(
    r"(?:[.!?][\"'”’)\]]*"
    r"|(?<=[a-z)\]])\.(?:\[\d[\d,\s–-]*\]|\d{1,3}(?:[,–-]\d{1,3})*))\s+"
)
_LAST_TOKEN_RE = re.compile(r"(\S+)$")
_INITIALS_RE = re.compile(r"(?:[a-z]\.)+[a-z]?")
_WORD_RE = re.compile(r"\S+")


def split_sentences(text: str) -> list[tuple[int, str]]:
    """Split prose into (char offset, sentence); robust to 'et al.', 'Fig.', decimals."""
    raw: list[tuple[int, str]] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(text):
        nxt = text[match.end():match.end() + 1]
        if not nxt or nxt.islower() or _is_abbreviation(text[start:match.start()]):
            continue
        end = match.start() + len(match.group(0).rstrip())
        raw.append((start, text[start:end]))
        start = match.end()
    if text[start:].strip():
        raw.append((start, text[start:].rstrip()))
    return _merge_fragments(_cap_long(raw))


def _is_abbreviation(before: str) -> bool:
    found = _LAST_TOKEN_RE.search(before)
    if found is None:
        return False
    token = found.group(1).lower().lstrip("([\"'")
    return (token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha())
            or bool(_INITIALS_RE.fullmatch(token)))


def _cap_long(sentences: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Split run-on 'sentences' (tables, lists) into ~60-word pieces."""
    out: list[tuple[int, str]] = []
    for offset, sent in sentences:
        words = list(_WORD_RE.finditer(sent))
        if len(words) <= _MAX_SENTENCE_WORDS:
            out.append((offset, sent))
            continue
        for i in range(0, len(words), _SPLIT_SENTENCE_WORDS):
            group = words[i:i + _SPLIT_SENTENCE_WORDS]
            out.append((offset + group[0].start(), sent[group[0].start():group[-1].end()]))
    return out


def _merge_fragments(sentences: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Attach very short fragments (stray labels, numbers) to the following sentence."""
    out: list[tuple[int, str]] = []
    carry: tuple[int, str] | None = None
    for offset, sent in sentences:
        if carry is not None:
            offset, sent = carry[0], f"{carry[1]} {sent}"
            carry = None
        if len(sent.split()) < _MIN_SENTENCE_WORDS:
            carry = (offset, sent)
            continue
        out.append((offset, sent))
    if carry is not None:
        if out:
            out[-1] = (out[-1][0], f"{out[-1][1]} {carry[1]}")
        else:
            out.append(carry)
    return out


def window_bounds(n_sentences: int) -> list[tuple[int, int]]:
    """[start, end) sentence ranges: 3 sentences, stride 2, last sentences always covered."""
    bounds: list[tuple[int, int]] = []
    for start in range(0, n_sentences, WINDOW_STRIDE):
        if start > 0 and start + 1 >= n_sentences:
            break
        bounds.append((start, min(start + WINDOW_SENTENCES, n_sentences)))
    return bounds


def build_windows(runs: list[TextRun], start_idx: int) -> tuple[list[Chunk], list[str]]:
    """Turn runs into window chunks (idx from start_idx) plus the global sentence list."""
    chunks: list[Chunk] = []
    sentences: list[str] = []
    for run_id, run in enumerate(runs):
        sents = split_sentences(run.text)
        if not sents:
            continue
        base = len(sentences)
        sentences.extend(s for _, s in sents)
        offsets = [m[0] for m in run.page_marks]
        for lo, hi in window_bounds(len(sents)):
            text = " ".join(s for _, s in sents[lo:hi])
            chunks.append(Chunk(
                idx=start_idx + len(chunks), heading=run.section, text=text,
                n_tokens=estimate_tokens(text), page=_page_at(run, offsets, sents[lo][0]),
                kind="caption" if run.kind == "caption" else "window",
                run=run_id, sent_start=base + lo, sent_end=base + hi,
            ))
    return chunks, sentences


def _page_at(run: TextRun, offsets: list[int], char_offset: int) -> int | None:
    if not run.page_marks:
        return None
    pos = max(bisect.bisect_right(offsets, char_offset) - 1, 0)
    return run.page_marks[pos][1]
