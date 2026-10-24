# Feature 10: V2 Quality Improvements — PDF Resolution, Reference Library & LLM Transparency

**Priority:** High
**Dependencies:** Feature 08 (Citation-First Verification)
**Status:** Designed

---

## Problem Statement

Testing on a 122-reference hydrogel transplantation manuscript produced 51 "cannot_verify" results out of 304 claims (~17%). The breakdown reveals distinct failure categories:

### Category A: No Source PDF (28 claims, 27 references)
- 25/27 have DOIs but are paywalled (Acta Biomaterialia, Transplantation, Science Translational Medicine, etc.)
- 2 have no DOI: [81] OPTN/HRSA website, [91] a 1998 book chapter (metadata lost in parsing)
- Several are very recent (2025) — not yet on Unpaywall/PMC
- A few are book chapters (almost never open-access)

### Category B: Wrong/Irrelevant Source Section (23 claims)
- Claim 4: source text was just publication metadata (title/authors), not content
- Claim 54: paper about face transplantation/MMP3, but claim about therapeutic cell engraftment — wrong reference mapping
- Claim 57: paper discusses systemic immunosuppression biomarkers, but claim about localized immunomodulation — topic mismatch

### Category C: Reference Extraction Bugs
Malformed parsed references with truncated journal names:
- `"Front\nLark, J. et al. (2024)"` → "Frontiers" truncated to "Front"
- `"Int\nTull, R. (2012)"` → "International" truncated to "Int"
- `"68\ndoi: 10.5555/synth.a.10001\nRuse, A. et al."` → reference number leaked into text
- `"Circ\nFenn, L. et al. (2019)"` → "Circulation" truncated to "Circ"

### Category D: No LLM Reasoning Visibility
Users cannot see which model verified each citation, what reasoning it used, or how voting (when multi-LLM is active) resolved disagreements.

---

## Solution Overview

Eight improvements organized by implementation phase:

1. **Reference extraction fixes** — detect and repair truncated/malformed reference entries
2. **Gap resolution UI** — journal links for paywalled papers, per-reference upload buttons
3. **Reference library** — lightweight SQLite persistence for PDFs across sessions
4. **Abstract-only verification** — fallback verification against abstracts when no PDF
5. **PDF text quality + section finder** — detect metadata-only extractions, improve relevance
6. **Cannot-verify breakdown** — exact dashboard showing WHY each claim couldn't be verified
7. **LLM reasoning transparency** — expandable per-claim model reasoning and voting display
8. **Re-verification trigger** — auto-re-verify claims when user uploads a missing PDF

---

## Part 1: Reference Extraction Fixes

### Root Cause
The DOCX parser splits on paragraph boundaries. Some reference list entries span multiple paragraphs in the DOCX (especially when formatted with hanging indents or when journal names wrap). This creates fragments like `"Front"` (first paragraph) + `"iers in Bioengineering...\nBai, J. et al. (2024)"` (second paragraph).

### Fix: Post-Parse Validation & Repair

After extracting the raw reference list, run a repair pass:

```python
class ReferenceRepairResult(BaseModel):
    original_text: str
    repaired_text: str
    repair_type: str  # "merged_fragment", "removed_number_prefix", "none"
    confidence: float
```

**Rule 1 — Fragment Detection:** If a reference entry is shorter than 30 characters and doesn't contain a year (4-digit number 1900-2099), it's likely a fragment. Merge with the next entry.

**Rule 2 — Number Prefix Removal:** If entry starts with just a number followed by newline (e.g., `"68\ndoi:..."`), strip the leading number — it's the reference list number that leaked in.

**Rule 3 — Truncated Journal Detection:** Match common truncated journal prefixes against a lookup table:
```
"Front" → "Frontiers"
"Int" → "International" 
"Circ" → "Circulation"
"J Am" → "Journal of the American"
"Nat" → "Nature"
"Sci" → "Science"
"Biomater" → "Biomaterials"
"Transpl" → "Transplantation"
```
If a fragment matches a known prefix AND the next entry starts with a lowercase letter or continuation pattern, merge them.

**Rule 4 — LLM Repair Fallback:** For entries that look malformed but don't match rules 1-3, send to a cheap LLM call: "This reference entry appears malformed. Return the corrected version as JSON: {title, authors, year, journal, doi}."

### Data Model Addition

```python
class Reference(BaseModel):
    # ... existing fields ...
    raw_text_original: str = ""   # before repair
    repair_applied: str = "none"  # "merged_fragment" | "removed_prefix" | "llm_repair" | "none"
```

---

## Part 2: Gap Resolution UI Improvements

### 2.1 Journal Links for Paywalled References

For each unresolved reference on the review page, show:
- **DOI link**: `https://doi.org/{doi}` (clickable, opens in new tab)
- **PubMed link**: `https://pubmed.ncbi.nlm.nih.gov/{pmid}/` (if PMID available)
- **Google Scholar link**: `https://scholar.google.com/scholar?q={url_encoded_title}`
- **Sci-Hub hint**: Display DOI prominently so user can paste it elsewhere (don't link directly)

### 2.2 Per-Reference PDF Upload

Each unresolved reference row gets an upload button:
- Drag-and-drop zone or file picker (PDF only)
- On upload: match to this specific reference (skip the matching step — user is explicitly telling us which reference this PDF belongs to)
- After upload: update reference status to `"available"`, set `pdf_source = "user_upload"`
- Show success confirmation with extracted title for the user to verify

### 2.3 Batch Upload Reminder

At the top of the unresolved references section:
- Count badge: "27 references need PDFs"
- "Upload All" button: opens a bulk upload modal where user can drag multiple PDFs
- After bulk upload: run matching against only the unresolved references

### API Changes

```
# Existing endpoint (already in API_CONTRACT.md)
POST /api/sessions/{session_id}/references/{ref_id}/upload-pdf

# New: generate download links for unresolved references
GET /api/sessions/{session_id}/references/{ref_id}/links
Response: {
    "doi_url": "https://doi.org/10.1016/...",
    "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
    "scholar_url": "https://scholar.google.com/scholar?q=...",
    "pmc_url": null,
    "unpaywall_status": "closed_access"
}
```

---

## Part 3: Reference Library (Lightweight SQLite)

### Purpose
Persist uploaded and downloaded PDFs across sessions. When a user uploads a paywalled PDF for manuscript A, it should automatically be available when manuscript B cites the same paper.

### Database Schema

Single SQLite database at `~/.refcheck/library.db`:

```python
class LibraryPaper(SQLModel, table=True):
    __tablename__ = "library_papers"
    id: int | None = Field(default=None, primary_key=True)
    doi: str | None = Field(default=None, index=True)
    pmid: str | None = Field(default=None, index=True)
    title: str = ""
    authors_json: str = "[]"     # JSON list[str]
    year: int | None = None
    journal: str | None = None
    pdf_path: str = ""           # absolute path to stored PDF
    pdf_hash: str = ""           # SHA-256 for dedup
    text_extracted: bool = False # has text been pre-extracted?
    text_path: str | None = None # path to extracted text cache
    source: str = ""             # "user_upload" | "open_access" | "pmc"
    added_at: str = ""           # ISO datetime
    source_session_id: str | None = None
```

### Storage Location
`~/.refcheck/library/pdfs/` — PDFs stored by hash: `{sha256[:8]}_{sanitized_title}.pdf`

### Integration Points

**On PDF upload (any session):**
1. Compute SHA-256 hash
2. Check if already in library (by hash)
3. If new: copy to library folder, create LibraryPaper record
4. If existing: link to existing library copy

**On session start (after reference extraction):**
1. For each reference without a PDF, check library by DOI → PMID → fuzzy title
2. If found: set `pdf_source = "library"`, link PDF path
3. Report: "Found 12 papers from your library (X remain unresolved)"

**On gap resolution (after API search):**
1. For each newly downloaded PDF, add to library
2. Dedup by hash before storing

### API Endpoints

```
GET  /api/library                         # List all papers (paginated, searchable)
GET  /api/library/stats                   # {total, with_pdf, by_source}
POST /api/library/upload                  # Upload PDF directly to library
DELETE /api/library/{paper_id}            # Remove paper
GET  /api/library/search?q=hydrogel      # Search by title/author/DOI
```

---

## Part 4: Abstract-Only Verification Fallback

### When to Use
When a reference has no PDF but has an abstract (from PubMed, Semantic Scholar, or CrossRef).

### How It Works
1. During gap resolution, if no PDF found but abstract IS available → store abstract text
2. During verification, if `source_status = "no_pdf"` but `abstract_text` is not empty → verify against abstract
3. Cap confidence at **0.60** regardless of model output
4. Set `source_coverage = "abstract_only"` on the verification result
5. In the report and UI, clearly label: "⚠️ Verified against abstract only — confidence capped"

### Data Model

```python
class Reference(BaseModel):
    # ... existing fields ...
    abstract_text: str | None = None
    abstract_source: str | None = None  # "pubmed" | "semantic_scholar" | "crossref"

class VerificationResult(BaseModel):
    # ... existing fields ...
    source_coverage: str = "full_text"  # "full_text" | "abstract_only" | "no_source"
```

### Abstract Retrieval Priority
1. PubMed E-Utilities (`efetch` with `rettype=abstract`)
2. Semantic Scholar API (`/paper/{doi}?fields=abstract`)
3. CrossRef (abstract field, when available — ~50% of records)

---

## Part 5: PDF Text Quality & Section Finder Improvements

### 5.1 Text Quality Scoring

Before verification, assess the quality of extracted PDF text:

```python
class TextQualityScore(BaseModel):
    total_chars: int
    total_words: int
    has_abstract: bool
    has_methods: bool
    has_results: bool
    is_metadata_only: bool    # < 500 chars of actual content
    is_likely_supplement: bool # contains "Supplementary" in first 200 chars
    score: float              # 0.0 to 1.0
```

**Scoring rules:**
- `is_metadata_only`: total extractable text < 500 characters (just title/authors/DOI)
- `is_likely_supplement`: first page contains "Supplementary", "Supporting Information", "Table S1"
- `score < 0.3`: Don't verify against this PDF — fall back to abstract or mark as no_source
- `score 0.3-0.6`: Verify but cap confidence at 0.70
- `score > 0.6`: Normal verification

### 5.2 Section Finder Improvements

Current problem: section finder sometimes extracts irrelevant sections.

**Fix 1 — Topic Coherence Check:** After extracting the top candidate section, compute keyword overlap between the claim and the extracted section. If overlap < 10% (measured by shared non-stopword tokens), try the next candidate section. If all candidates have < 10% overlap, flag as `section_relevance = "low"` and cap confidence at 0.50.

**Fix 2 — Broader Initial Extraction:** Instead of extracting only the single best section, extract the top 3 sections and concatenate them (up to context window limits). More context = better chance of finding the relevant passage.

**Fix 3 — Full-Paper Fallback:** If the PDF is short (< 15 pages), just send the entire text. The LLM can find the relevant part itself. Only use section finding for longer papers.

### Data Model

```python
class VerificationResult(BaseModel):
    # ... existing fields ...
    section_relevance: str = "high"  # "high" | "medium" | "low" | "full_paper"
    text_quality_score: float = 1.0
```

---

## Part 6: Cannot-Verify Breakdown Dashboard

### The Problem
"51 cannot_verify" tells the user nothing. They need to know WHY for each one.

### Reason Categories

```python
class CannotVerifyReason(str, Enum):
    NO_PDF = "no_pdf"                           # No PDF available at all
    NO_PDF_PAYWALLED = "no_pdf_paywalled"       # Has DOI, known paywalled
    NO_PDF_NOT_FOUND = "no_pdf_not_found"       # No DOI or paper not in any database
    NO_PDF_BOOK_CHAPTER = "no_pdf_book_chapter" # Book chapter, not journal article
    NO_PDF_WEBSITE = "no_pdf_website"           # Website/database, not a paper
    PDF_METADATA_ONLY = "pdf_metadata_only"     # PDF exists but only metadata extractable
    PDF_SCANNED = "pdf_scanned"                 # Scanned PDF, no text (needs OCR)
    PDF_SUPPLEMENT = "pdf_supplement"            # Wrong PDF — supplement instead of main paper
    SECTION_IRRELEVANT = "section_irrelevant"   # Extracted section doesn't match claim topic
    REFERENCE_MISMATCH = "reference_mismatch"   # Claim assigned to wrong reference
    LLM_ERROR = "llm_error"                     # LLM call failed (timeout, parse error)
    ABSTRACT_INSUFFICIENT = "abstract_insufficient" # Abstract doesn't address the specific claim
```

### Dashboard on Results Page

```
Cannot Verify Breakdown (51 claims):
────────────────────────────────────
📄 No PDF — Paywalled          28  ████████████████████  [Upload PDFs]
📄 No PDF — Not Found           2  ██                    [Check manually]
📄 No PDF — Book Chapter        1  █                     
📄 No PDF — Website             1  █                     
🔍 Irrelevant Section          12  ████████              [Details]
📎 PDF Metadata Only            4  ███                   [Re-extract]
🔗 Reference Mismatch           2  ██                    [Fix mapping]
⚠️ LLM Error                    1  █                     [Retry]
```

Each category is clickable → shows the specific claims in that bucket.

### API

```
GET /api/sessions/{session_id}/cannot-verify-breakdown
Response: {
    "total": 51,
    "reasons": {
        "no_pdf_paywalled": {"count": 28, "claim_ids": [4, 7, ...]},
        "section_irrelevant": {"count": 12, "claim_ids": [54, 57, ...]},
        ...
    }
}
```

---

## Part 7: LLM Reasoning Transparency

### Per-Claim Evidence Panel

When a user clicks on any verified citation, show:

**Always visible:**
- Verdict badge (Supported / Partially Supported / Not Supported / Contradicted / Cannot Verify)
- Confidence score (e.g., "87%")
- Source coverage badge ("Full Text" / "Abstract Only" / "No Source")

**Expandable section — "Reasoning":**
- Model name and version (e.g., "Claude Sonnet 4.5")
- Full reasoning text from the LLM
- Evidence quotes (highlighted, in a distinct box)
- Section of the paper that was examined

**Expandable section — "Verification Details":**
- Source coverage: full text / abstract only / no source
- Text quality score
- Section relevance
- Cannot-verify reason (if applicable)
- Response time
- Token count

**Future-proof for multi-LLM (Feature 09):**
When multi-LLM voting is active, the reasoning section becomes:
- Jury panel (model dots with verdict colors)
- Per-model expandable cards (each model's reasoning)
- Consensus type (unanimous / majority / escalated)
- Escalation timeline (if applicable)

The data model already supports this via lists — even with a single model, the reasoning is stored in a list with one entry.

### Data Model

```python
class ModelReasoning(BaseModel):
    model_name: str              # "claude-sonnet-4.5"
    model_display: str           # "Claude Sonnet 4.5"
    verdict: str
    confidence: float
    reasoning: str
    evidence_quotes: list[str]
    source_section: str          # which section of the paper was examined
    response_time_ms: int
    input_tokens: int
    output_tokens: int

class VerificationResult(BaseModel):
    # ... existing fields ...
    model_reasoning: list[ModelReasoning] = []  # one entry now, multiple with multi-LLM
    cannot_verify_reason: str | None = None
```

### API

```
GET /api/sessions/{session_id}/evidence/{claim_id}
Response: {
    "claim_id": 54,
    "manuscript_text": "...",
    "reference_id": 46,
    "verdict": "cannot_verify",
    "confidence": 0.0,
    "cannot_verify_reason": "section_irrelevant",
    "source_coverage": "full_text",
    "text_quality_score": 0.85,
    "section_relevance": "low",
    "model_reasoning": [
        {
            "model_name": "claude-sonnet-4.5",
            "model_display": "Claude Sonnet 4.5",
            "verdict": "cannot_verify",
            "confidence": 0.0,
            "reasoning": "The source paper discusses face transplantation and MMP3 expression...",
            "evidence_quotes": [],
            "source_section": "Results section, paragraphs 3-5",
            "response_time_ms": 2340,
            "input_tokens": 1847,
            "output_tokens": 312
        }
    ]
}
```

---

## Part 8: Re-Verification Trigger

### Flow
When a user uploads a PDF for a reference that previously had `no_pdf`:
1. Update reference status → `"available"`, `pdf_source = "user_upload"`
2. Add PDF to library (Part 3)
3. Find all claims that reference this paper
4. Re-run verification for those claims ONLY
5. Emit SSE events showing re-verification progress
6. Update results in real-time on the frontend

### API

```
POST /api/sessions/{session_id}/references/{ref_id}/upload-pdf
Response: {
    "reference_id": 46,
    "pdf_matched": true,
    "pdf_source": "user_upload",
    "claims_to_reverify": [54, 55, 57],   # NEW
    "reverification_started": true          # NEW
}
```

### Frontend Behavior
After upload:
- Show toast: "PDF uploaded for [Reference Title]. Re-verifying 3 claims..."
- Claims that are being re-verified show a spinning indicator
- When re-verification completes, the verdict/confidence update in real-time
- Cannot-verify breakdown dashboard updates automatically

---

## Additional Improvements (Claude's Recommendations)

### 9. Unpaywall + PMC Aggressive Retry

Currently Unpaywall is checked once. Add:
- **PubMed Central full-text fetch**: If reference has a PMCID, fetch via PMC OA API (`https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{id}`)
- **Europe PMC fallback**: `https://europepmc.org/search?query=DOI:{doi}` (covers some papers Unpaywall misses)
- **Unpaywall retry for recent papers**: Papers < 6 months old often become OA after an embargo. If a paper is recent and paywalled, mark it for re-check on next session.

### 10. Reference Type Detection

Classify each reference to set expectations:
- **Journal article** (standard — full verification expected)
- **Book chapter** (rarely has OA PDF — abstract verification likely)
- **Conference paper** (check ACM/IEEE open access)
- **Website/database** (cannot verify traditionally — check URL accessibility instead)
- **Government report** (often freely available — try direct URL)
- **Preprint** (check bioRxiv/medRxiv/arXiv for full text)

Store as `reference_type` field. Use in cannot-verify breakdown and to set appropriate confidence thresholds.

### 11. Claim-Reference Coherence Check

After citation-to-reference mapping (Feature 08), add a lightweight coherence check:
- Extract top 5 keywords from the claim text
- Extract top 5 keywords from the reference title + abstract
- Compute Jaccard similarity
- If < 0.05: flag as potential mismatch, add to `"reference_mismatch"` bucket
- Show in UI: "⚠️ This claim may be matched to the wrong reference"

---

## Done Criteria

- [ ] Reference extraction repairs truncated journal names (test with the 4 known examples)
- [ ] Unresolved references show DOI/PubMed/Scholar links
- [ ] Per-reference upload button works and triggers re-verification
- [ ] Library SQLite persists PDFs across sessions
- [ ] Library auto-matches on new session start
- [ ] Abstract-only verification works when no PDF (confidence capped at 0.60)
- [ ] Text quality scoring detects metadata-only PDFs
- [ ] Section finder uses top-3 sections + coherence check
- [ ] Cannot-verify breakdown dashboard shows exact reason per claim
- [ ] LLM reasoning expandable per claim with model name, reasoning, evidence
- [ ] Re-verification triggers after PDF upload for affected claims
- [ ] Reference type detection classifies entries
- [ ] Claim-reference coherence check flags mismatches
- [ ] All existing tests pass
- [ ] `ruff check src/` → 0 errors
- [ ] `mypy src/` → 0 errors
- [ ] `cd frontend && npm run build` → success
- [ ] No file exceeds 200 lines
