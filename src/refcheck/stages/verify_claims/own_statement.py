"""Does the cited paper state the point itself? (V5.6, review finding E5)

The secondary-citation note ("the source attributes this to other work — consider
citing the primary study", post_checks.py) fired for 14 reviewed pairs although the
paper's own Results or abstract stated the point, e.g. as the study's own result.
Before the note is added (``states_itself``), the paper counts as stating the point
when a supporting quote WITHOUT a marker lies outside the Introduction (its section is
found by locating the quote in the document; background restatements in the
Introduction often carry no marker), or when a search of the whole document finds a
marker-free sentence that states it. Thresholds were set on the reviewed pairs so
that list-like or merely topical sentences do not count (on the 41 reviewed pairs
with the note: 11 of the 12 the review called spurious lose it; 2 of the 4 whose
quotes were all secondary keep it):

* query: the cited span plus the supporting quote(s) that cite other work;
* candidates: the abstract's sentences and the sentences of the TOP_WINDOWS windows
  BM25 ranks best over the WHOLE text (retriever.bm25_ranking);
* a candidate counts when it carries no citation marker (markers.has_marker), is not
  the quote itself, is not in the Introduction (background restatements) nor a list
  (an abbreviation key: LIST_SEMICOLONS or more ";"), and covers
  at least PREFERRED_COVERAGE (Abstract / Results / Conclusion) or OWN_COVERAGE
  (other sections) of the content tokens (bm25.tokenize) of the cited span or of one
  such quote.

Own data only (V5.6 follow-up): a review's marker-free summary sentence restates
other work, so a review (``is_review``: its reference type, or "review" /
"meta-analysis" in the title, or "we review / summarize" / "this review" in the
abstract) never states the point itself. In any paper, a marker-free quote or
sentence outside Abstract / Results / Conclusion (Discussion, Methods, a custom
heading = "other") counts only when it reports data (``reports_data``: a figure, a
first-person finding such as "we found" / "our data show", or the study's own arms /
the study itself: "in the treated group", "in this study").
"""

import re

from rapidfuzz.utils import default_process

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.bm25 import tokenize
from refcheck.stages.verify_claims.gates import extract_quantities
from refcheck.stages.verify_claims.layer_quotes import ValidatedQuote
from refcheck.stages.verify_claims.markers import has_marker
from refcheck.stages.verify_claims.retriever import bm25_ranking
from refcheck.stages.verify_claims.source_models import SourceDocument
from refcheck.stages.verify_claims.source_windows import split_sentences

TOP_WINDOWS = 12
OWN_COVERAGE = 0.75
PREFERRED_COVERAGE = 0.6
MIN_TOKENS = 4  # a target this short is matched by too many sentences
LIST_SEMICOLONS = 3
_SECTION_KEY_CHARS = 80  # quote prefix located in the document (quote_section)
_PREFERRED = frozenset({"Abstract", "Results", "Conclusion"})
_EXCLUDED = frozenset({"Introduction"})
_REVIEW_TITLE_RE = re.compile(r"\b(?:review|meta-?analys[ie]s|overview)\b", re.IGNORECASE)
_REVIEW_ABSTRACT_RE = re.compile(
    r"\b(?:(?:we|here\s+we)\s+(?:review|summari[sz]e|overview|discuss\s+recent)"
    r"|this\s+(?:review|mini-?review|overview)|in\s+this\s+(?:review|overview))\b",
    re.IGNORECASE)
_OWN_FINDING_RE = re.compile(
    r"\b(?:we|our\s+(?:results|data|findings|study|experiments))\s+(?:\w+\s+)?"
    r"(?:found|find|show(?:ed|n|s)?|observ(?:ed|e)|demonstrat(?:ed|e)|report(?:ed)?"
    r"|detect(?:ed)?|measur(?:ed|e)|identif(?:ied|y)|confirm(?:ed)?|indicat(?:ed|e)"
    r"|reveal(?:ed)?)\b"
    # the study's own arms or the study itself: "in the CS/DBM group", "in this study"
    r"|\b(?:in|of|for|from)\s+(?:the|our|both|all|each)\s+(?:[\w/+-]+\s+){0,2}groups?\b"
    r"|\b(?:this|the\s+present|the\s+current|our)\s+(?:study|experiments?|model)\b",
    re.IGNORECASE)


def is_review(doc: SourceDocument, ref: Reference | None) -> bool:
    """The paper reviews other work (module doc)."""
    if ref is not None and ("review" in ref.reference_type.lower()
                            or _REVIEW_TITLE_RE.search(ref.title or "")):
        return True
    abstract = doc.abstract_chunk.text if doc.abstract_chunk is not None else ""
    if not abstract and ref is not None:
        abstract = ref.abstract_text or ""
    return _REVIEW_ABSTRACT_RE.search(abstract) is not None


def reports_data(sentence: str) -> bool:
    """A figure (not a year, citation marker or name such as IL-6), a first-person
    finding ("we found", "our data show") or the study's own arms (module doc)."""
    if extract_quantities(sentence, source=True):
        return True
    return _OWN_FINDING_RE.search(sentence) is not None


def counts_as_own(section: str | None, sentence: str) -> bool:
    """A marker-free sentence in ``section`` that may state the paper's own point."""
    if section is None or section in _EXCLUDED:
        return False
    return section in _PREFERRED or reports_data(sentence)


def _candidates(doc: SourceDocument, query: str) -> list[tuple[str, str]]:
    """(section, sentence) of the abstract and of the best BM25 windows."""
    out: list[tuple[str, str]] = []
    abstract = doc.abstract_chunk
    if abstract is not None:
        out += [("Abstract", s) for _, s in split_sentences(abstract.text)]
    windows = {c.idx: c for c in doc.windows}
    for idx, _ in bm25_ranking(query, doc)[:TOP_WINDOWS]:
        chunk = windows[idx]
        sentences = doc.sentences[chunk.sent_start:chunk.sent_end] \
            or [s for _, s in split_sentences(chunk.text)]
        out += [(chunk.heading, s) for s in sentences]
    return out


def _coverage(target: set[str], sentence: set[str]) -> float:
    return len(target & sentence) / len(target) if target else 0.0


def own_statement(doc: SourceDocument, cited: str,
                  quotes: list[ValidatedQuote]) -> str | None:
    """A marker-free sentence of the paper that states the cited point (module doc)."""
    targets = [t for t in (set(tokenize(text)) for text in [cited, *(q.text for q in quotes)])
               if len(t) >= MIN_TOKENS]
    if not targets or not doc.chunks:
        return None
    quoted = [default_process(q.text) for q in quotes]
    query = " ".join([cited, *(q.text for q in quotes)])
    for section, sentence in _candidates(doc, query):
        if not counts_as_own(section, sentence) or has_marker(sentence) \
                or sentence.count(";") >= LIST_SEMICOLONS:
            continue
        plain = default_process(sentence)
        if any(q and (q in plain or plain in q) for q in quoted):
            continue
        need = PREFERRED_COVERAGE if section in _PREFERRED else OWN_COVERAGE
        words = set(tokenize(sentence))
        if max(_coverage(t, words) for t in targets) >= need:
            return sentence
    return None


def quote_section(doc: SourceDocument, text: str) -> str | None:
    """The section of the window (or the abstract) that contains a quote, else None."""
    key = default_process(text)[:_SECTION_KEY_CHARS]
    if not key:
        return None
    abstract = doc.abstract_chunk
    if abstract is not None and key in default_process(abstract.text):
        return "Abstract"
    return next((c.heading for c in doc.windows if key in default_process(c.text)), None)


def states_itself(doc: SourceDocument, cited: str, secondary: list[ValidatedQuote],
                  own: list[ValidatedQuote], ref: Reference | None = None) -> bool:
    """The paper states the point itself: not a review, and a marker-free supporting
    quote (``own``) that counts as its own, or a sentence ``own_statement`` finds."""
    if is_review(doc, ref):
        return False
    if any(counts_as_own(quote_section(doc, q.text), q.text) for q in own):
        return True
    return own_statement(doc, cited, secondary) is not None
