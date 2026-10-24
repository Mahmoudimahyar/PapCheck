"""Row schema of the RefCheck manuscript gold benchmark (refcheck_v49_gold) + pair ids.

One row per unique (citing sentence, reference) pair of a real manuscript,
labelled by manual review. Rows carry the manuscript fields the production
Claim needs (sentence, cited_for, paragraph, section, co-citations) and the
reference fields the production source loader needs (pdf_path, abstract,
identity), so the eval can rebuild the exact production inputs.
Gold data holds unpublished manuscript text: it lives only under ~/.refcheck/eval.
"""

import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GOLD_DATASET = "refcheck_v49_gold"
# Stored co-cited abstracts (~400 tokens) are a superset of the production budget: the eval
# re-truncates them to cocited.COCITED_ABSTRACT_TOKENS (250) through co_cited_ref.
COCITED_ABSTRACT_CHARS = 1600
# review_C / review_D: tool-"supported" pairs reviewed later (a sample of one run / every
# supported verdict of a later run); their rows come from a labels file.
GoldSource = Literal["review_A", "review_B", "review_C", "review_D", "both", "adjudicated"]
Confidence = Literal["high", "medium", "low"]
Basis = Literal["full_text", "abstract"]
# "unverified": an element could not be checked (no full text; flag coverage_limited).
Severity = Literal["", "none", "minor", "major", "unverified"]
# Labels a reviewer may give; "cannot_judge" marks a pair whose gold is not valid (excluded).
REVIEW_LABELS = ("supported", "partially_supported", "not_supported", "contradicted",
                 "not_relevant", "cannot_judge")
_DASHES_RE = re.compile(r"[‐-―−]")


def normalize_sentence(text: str) -> str:
    """Case/space/dash-insensitive form of a citing sentence (pair identity)."""
    clean = _DASHES_RE.sub("-", unicodedata.normalize("NFKC", text or "").lower())
    return " ".join(clean.split())


def pair_id(sentence: str, ref: int) -> str:
    """Stable id of a (sentence, reference) pair: independent of session/claim numbering."""
    digest = hashlib.sha1(f"{normalize_sentence(sentence)}|{ref}".encode())
    return f"v49-{digest.hexdigest()[:12]}"


class CoCitedRef(BaseModel):
    """Another reference cited in the same sentence."""

    ref: int
    title: str = ""
    abstract: str | None = None  # DB abstract, whitespace-normalised, <= COCITED_ABSTRACT_CHARS


class GoldRow(BaseModel):
    """One line of refcheck_v49_gold[.dev|.test].jsonl."""

    model_config = ConfigDict(extra="ignore")

    id: str
    dataset: str = GOLD_DATASET
    session_id: str = ""  # run whose claims/references the row was built from
    claim_number: int = 0  # claim number in that session (verifications.claim_id)
    sentence: str
    claim: str
    cited_for: str = ""
    paragraph: str = ""
    section: str = ""
    claim_type: str = "factual"
    claim_quality: str = "ok"
    co_cited_count: int = 1
    co_cited_refs: list[CoCitedRef] = Field(default_factory=list)
    ref: int
    ref_title: str = ""
    ref_authors: list[str] = Field(default_factory=list)
    ref_year: int | None = None
    doi: str | None = None
    pdf_path: str | None = None  # production PDF (duplicate entries inherit the original's)
    abstract: str | None = None
    abstract_source: str | None = None
    identity_status: str = "unverified"  # as recorded by the production resolve stage
    gold_label: str
    gold_binary: Literal["ok", "problem"]
    gold_partial_type: str = ""
    tool_misread_type: str = ""
    gold_source: GoldSource
    gold_confidence: Confidence = "medium"
    gold_basis: Basis = "full_text"  # what the reviewer could read
    secondary_types: list[str] = Field(default_factory=list)  # further taxonomy types / guards
    partial_types: list[str] = Field(default_factory=list)  # genuine partial types, primary first
    tool_misread_types: list[str] = Field(default_factory=list)  # all guards (tool too harsh)
    severity: Severity = ""
    flags: list[str] = Field(default_factory=list)
    needs_adjudication: bool = False
    notes: str = ""
    split: Literal["dev", "test"] = "dev"
    exclude: bool = False
    exclude_reason: str = ""
    review_a_case: int | None = None
    review_b_case: int | None = None
    review_c_case: int | None = None
    review_d_cases: list[int] = Field(default_factory=list)  # several clauses may share a pair
    review_a_verdict: str = ""
    review_b_verdict: str = ""
    review_d_verdict: str = ""  # review D's verdict, also on rows whose label it did not set


class LabelOverride(BaseModel):
    """One entry of a labels file ({pair_id: LabelOverride}); None = keep the row's value.

    An entry with gold_source "review_C"/"review_D" may name a pair that no review
    A/B verdict covers: the builder then constructs its row from the session
    (claim_number/ref locate it; cases like ["C:4"] / ["D:7", "D:9"] give the review
    cases). keep_existing marks a pair the gold set already labels: the row keeps
    its label and fields, gold_label is recorded as the review's verdict, notes
    are appended and flags added (gold_annotate).
    """

    model_config = ConfigDict(extra="ignore")

    gold_label: str | None = None
    gold_partial_type: str | None = None
    tool_misread_type: str | None = None
    gold_confidence: Confidence | None = None
    gold_basis: Basis | None = None
    secondary_types: list[str] | None = None
    partial_types: list[str] | None = None
    tool_misread_types: list[str] | None = None
    severity: Severity | None = None
    flags: list[str] | None = None
    notes: str | None = None
    exclude: bool | None = None
    gold_source: GoldSource | None = None  # only used to construct new (review_C) rows
    claim_number: int | None = None
    ref: int | None = None
    cases: list[str] = Field(default_factory=list)
    keep_existing: bool = False


# LabelOverride fields copied onto a row when not None (gold_label/exclude have own rules).
OVERRIDE_FIELDS = ("gold_partial_type", "tool_misread_type", "gold_confidence", "gold_basis",
                   "secondary_types", "partial_types", "tool_misread_types", "severity",
                   "flags", "notes")


def binary_of(label: str) -> Literal["ok", "problem"]:
    return "ok" if label == "supported" else "problem"
