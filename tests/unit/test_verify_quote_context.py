"""V5.6 evidence quotes: front matter (E1), "states" (E2/E4), contained duplicates (E6).

Synthetic data only.
"""

from refcheck.models.verification import EvidenceQuote
from refcheck.stages.verify_claims.layer_audit import audit_layer
from refcheck.stages.verify_claims.layer_quotes import (
    ValidatedQuote,
    dedupe_contained,
    dedupe_contained_texts,
    states_nothing,
    validate_output_quotes,
)
from refcheck.stages.verify_claims.quote_context import (
    front_matter,
    header_text,
    is_author_block,
    is_title,
)
from refcheck.stages.verify_claims.source_document import build_source_document
from tests.unit.verify_fakes import (
    ABSTRACT,
    FULL_TEXT,
    RESULT_TEXT,
    judge_output,
    make_ctx,
    make_pack,
    make_ref,
)

TITLE = "Injectable gel Q lowers paw swelling in arthritic mice: a controlled study"
HEADER = ("Journal of Synthetic Gels 12 (2020) 101-109\n" + TITLE + "\n"
          "Ann Smith, Bo Doe\nDepartment of Bioengineering, Example University, USA\n\n")


def _quote(text: str, role: str = "supports", **extra: str) -> EvidenceQuote:
    return EvidenceQuote.model_validate({"passage_id": "P1", "text": text, "role": role,
                                         **extra})


def test_title_detection() -> None:
    assert is_title(TITLE, TITLE)
    assert is_title("Injectable gel Q lowers paw swelling", TITLE)  # a title fragment
    assert is_title(TITLE + ". Journal of Synthetic Gels", TITLE)  # title + header words
    assert not is_title("in arthritic mice", TITLE)  # too short to be the title
    assert not is_title("Gel Q lowered paw swelling by 35% (p < 0.01) in arthritic mice "
                        "compared with vehicle at day 14.", TITLE)


def test_author_block_detection() -> None:
    ref = make_ref(authors=["Smith A", "Doe B"], journal="Journal of Synthetic Gels")
    assert is_author_block("Ann Smith, Bo Doe, Department of Bioengineering", ref)
    assert is_author_block("Received 3 May 2020; accepted 9 June 2020", ref)
    assert not is_author_block("Smith and colleagues reduced swelling in mice by 35%.", ref)
    assert not is_author_block(RESULT_TEXT, ref)


def test_journal_words_and_statistics_never_make_an_author_block() -> None:
    ref = make_ref(authors=["Smith A", "Doe B"], journal="Am J Transplant")
    for quote in ("In transplant recipients, MST was 52 ± 4 d vs 12 ± 2 d (n = 6, P < 0.01).",
                  "Transplant survival: 8/10 vs 0/10 (P = 0.002, n = 10).",
                  "Transplant Graft Survival Improved In Treated Recipients"):
        assert front_matter(quote, ref) is None, quote
    assert is_author_block("Ann Smith, Bo Doe, Department of Transplant Surgery", ref)
    assert is_author_block("Am J Transplant 2020; 20: 101-109", ref)


def test_journal_header_before_the_abstract() -> None:
    ref = make_ref(title=TITLE, authors=["Smith A", "Doe B"])
    doc = build_source_document(ref.id, HEADER + FULL_TEXT, abstract_text=ABSTRACT)
    assert "Example University" in header_text(doc)
    assert front_matter("Journal of Synthetic Gels 12 (2020) 101-109", ref, doc) is not None
    assert front_matter(TITLE, ref, doc) == "the reference's title"
    assert front_matter(RESULT_TEXT, ref, doc) is None
    assert front_matter("Inflammation drives tissue damage.", ref, doc) is None


def test_running_text_before_a_late_abstract_is_not_header() -> None:
    """A PDF whose abstract is extracted after the Introduction (two-column layout)."""
    ref = make_ref(title=TITLE, authors=["Smith A", "Doe B"])
    intro = ("Journal of Synthetic Gels 12 (2020) 101-109\n\nInflammation of the joints is "
             "common in older adults and is usually treated with drugs that act on the whole "
             "body (3, 4). ")
    doc = build_source_document(ref.id, intro + ABSTRACT + "\n\n" + FULL_TEXT,
                                abstract_text=ABSTRACT)
    assert "Inflammation of the joints" not in header_text(doc)
    assert front_matter("Inflammation of the joints is common in older adults and is usually "
                        "treated with drugs that act on the whole body", ref, doc) is None


def test_states_marks_context_only_supports_quotes() -> None:
    assert states_nothing(_quote(RESULT_TEXT, states=""))
    assert not states_nothing(_quote(RESULT_TEXT, states="reduced IL-6"))
    assert not states_nothing(_quote(RESULT_TEXT))  # older outputs: no field -> evidence
    assert not states_nothing(_quote(RESULT_TEXT, role="closest", states=""))
    out = judge_output("supported").model_copy(update={"quotes": [
        _quote(RESULT_TEXT, states=""), _quote(RESULT_TEXT, states=" reduced IL-6 ")]})
    validated, _ = validate_output_quotes(out, make_pack())
    assert [q.context != "" for q in validated] == [True, False]
    assert validated[1].states == "reduced IL-6"


def test_dedupe_keeps_the_longer_quote_per_role() -> None:
    def vq(text: str, role: str = "supports") -> ValidatedQuote:
        return ValidatedQuote(passage_id="P1", text=text, role=role)
    short = "drug X reduced IL-6 levels by 40%"
    kept = dedupe_contained([vq(short), vq(RESULT_TEXT), vq(RESULT_TEXT.upper()),
                             vq(short, "closest")])
    assert [(q.text, q.role) for q in kept] == [(RESULT_TEXT, "supports"), (short, "closest")]
    assert dedupe_contained_texts([short, RESULT_TEXT, "Other text."]) == [
        RESULT_TEXT, "Other text."]


def test_dedupe_ignores_closing_punctuation() -> None:
    long = "Gel Q lowered scar collagen in both kidneys (Fig. 2B)."
    assert dedupe_contained_texts(["Gel Q lowered scar collagen in both kidneys.", long]) == [
        long]


def test_audit_sets_title_and_context_quotes_aside() -> None:
    ctx = make_ctx()  # reference title "Drug X in mice"
    ctx.ref = ctx.ref.model_copy(update={"title": "Drug X reduced IL-6 levels by 40%"})
    out = judge_output("supported").model_copy(update={"quotes": [
        _quote("Drug X reduced IL-6 levels by 40%", states="reduced IL-6"),
        _quote(ABSTRACT.split(". ")[1], states="", passage_id="A")]})
    audit = audit_layer(out, make_pack(), ctx)
    assert audit.evidence == []
    assert [q.context for q in audit.context] == [
        "the reference's title", "it states nothing of the cited part"]
