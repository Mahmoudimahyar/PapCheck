# Feature 11: Verification Pipeline Bugfixes & Cannot-Verify Retry Workflow

**Priority:** Critical
**Dependencies:** Feature 10 (V2 Quality Improvements) — these are fixes to incomplete Feature 10 implementation
**Status:** Designed

---

## Problem Statement

Feature 10 was designed and partially implemented, but a detailed investigation revealed **6 bugs and 1 major architectural gap** where designed systems exist in code but are never actually wired into the pipeline.

### Bug 1: Library References Stuck as "pending" (Backend)
**Severity: Medium.** 9 references matched from the library have PDF files on disk but `source_status` stays `"pending"` forever. The library integration adds `pdf_path` but never updates `source_status` to `"found"` or `"available"`.

### Bug 2: "Found" References Showing Upload Button (UI)
**Severity: Low.** 18 references with `source_status='found'` but no actual PDF file show inconsistent UI. The condition `!ref.pdf_path && ref.source_status !== "found"` doesn't properly handle "found metadata but no PDF" vs "has PDF file".

### Bug 3: Malformed Titles — 30+ References (Parser)
**Severity: High.** The reference repairer (Phase 1 of Feature 10) was implemented but doesn't catch all cases. ~30+ references still have titles that are journal abbreviations ("Front", "Orthop", "Int", "Sci", "Nat"), DOI strings, or year fragments. Any title under 25 characters is likely wrong.

### Bug 4: 5 Empty Claims (Parser Edge Case)
**Severity: Low.** 5 claims have blank `extracted_claim` text. They come from citation-only manuscript text like `"(Lane et al., 2020; Fenn-Ashby et al., 2022)"` — the citation detector found references but there's no actual claim to verify.

### Bug 5: text_quality_score Never Computed (Classification — CRITICAL)
**Severity: Critical.** `text_quality.py` exists with `score_pdf_text()` but it is **never called**. The `text_quality_score` field defaults to `1.0` on every VerificationResult. This means:
- Metadata-only PDFs (< 500 chars of content) are treated as full-quality
- Supplements are never detected
- The quality-based confidence capping from Feature 10 spec never fires

### Bug 6: section_relevance Hardcoded to "high" (Classification — CRITICAL)  
**Severity: Critical.** `section_relevance` is set to `"high"` by default and never computed from actual topic coherence. The `check_topic_coherence()` function from Feature 10 either doesn't exist or is never called. This means:
- `classify_cannot_verify()` always falls through to the default: `SECTION_IRRELEVANT`
- "section_irrelevant" is a meaningless catch-all label, not a real diagnosis
- The user sees 22 claims labeled "section irrelevant" with no way to distinguish "wrong section extracted" from "PDF has no relevant content" from "reference mapping is wrong"

### Architectural Gap: No Cannot-Verify Retry Workflow
When verification returns "cannot_verify", the system gives up immediately. There is no progressive broadening strategy. The LLM may have received a narrow, irrelevant text snippet when the relevant information was elsewhere in the paper. The user's key insight: **the LLM needs to see full paragraph context, not just keyword-matched fragments.**

---

## Solution Architecture

### Fix Strategy

All 6 bugs are straightforward code fixes. The architectural gap requires a new "retry with broader context" pipeline stage.

```
Claim + Reference PDF
         │
         ▼
┌─────────────────────────┐
│  1. Score PDF Quality    │ ← text_quality.py (EXISTS, wire it in)
│     metadata_only?       │
│     supplement?          │
│     scanned?             │
└────────────┬────────────┘
             │
     score ≥ 0.3           score < 0.3
         │                     │
         ▼                     ▼
┌─────────────────┐    ┌─────────────────┐
│ 2. Extract       │    │ Fall back to    │
│    Sections      │    │ abstract-only   │
│    (top 3)       │    │ verification    │
└────────┬────────┘    └─────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 3. Check Coherence      │ ← check_topic_coherence() (wire it in)
│    claim vs sections     │
│    coherence > 0.10?     │
└────────┬────────────────┘
         │
    yes (> 0.10)         no (< 0.10)
         │                     │
         ▼                     ▼
┌─────────────────┐    ┌──────────────────────┐
│ 4. Normal        │    │ 5. RETRY WORKFLOW    │
│    Verification  │    │    (NEW — see below) │
└─────────────────┘    └──────────────────────┘
```

### Cannot-Verify Retry Workflow (New)

When initial verification returns "cannot_verify" OR coherence is low:

```
Step 1: BROADER SECTIONS
  ─ Re-extract using top 5 sections instead of top 3
  ─ Include abstract + introduction regardless of keyword match
  ─ Send to LLM with full paragraph context around each section
  ─ If verdict ≠ cannot_verify → DONE (use this result)

Step 2: FULL PAPER (if paper < 50 pages)
  ─ Send entire paper text to LLM
  ─ Tell LLM: "Search the entire paper for evidence"
  ─ If verdict ≠ cannot_verify → DONE (use this result, note "full_paper" mode)

Step 3: ABSTRACT FALLBACK
  ─ If abstract available, verify against abstract only
  ─ Cap confidence at 0.60
  ─ If verdict ≠ cannot_verify → DONE (source_coverage = "abstract_only")

Step 4: CLASSIFY AND GIVE UP
  ─ Run classify_cannot_verify() with ACTUAL scores
  ─ Store the specific reason
  ─ Mark as genuinely unverifiable with the real reason
```

This workflow ensures we exhaust all options before marking something "cannot_verify", and when we do, we know exactly why.

---

## Part 1: Bug Fixes (Detailed)

### Fix 1: Library Status Update

**Where:** The pipeline stage or service function that checks the library for matching papers (was specified in Feature 10 Phase 3, Step 3.2).

**What to change:** After matching a reference from the library and setting `pdf_path`:
```python
ref.source_status = "found"       # WAS: left as "pending"
ref.pdf_source = "library"        # WAS: sometimes not set
```

Also verify the library integration is called at the right time — it should run BEFORE gap resolution (so the resolver doesn't waste API calls looking for papers we already have).

### Fix 2: UI Upload Button Condition

**Where:** The frontend component that renders reference rows (likely `reference-table.tsx` or wherever the upload button is rendered on the review page).

**What to change:** The condition for showing the upload button should be:
```typescript
// Show upload button when: no PDF file exists, regardless of source_status
const showUploadButton = !ref.pdf_path;

// Show "found but no PDF" status when: metadata resolved but no file
const isFoundNoPdf = ref.source_status === "found" && !ref.pdf_path;

// Show links (DOI/PubMed/Scholar) when: no PDF available
const showLinks = !ref.pdf_path && (ref.doi || ref.pmid || ref.title);
```

### Fix 3: Malformed Title Detection & LLM Repair

**Where:** `src/refcheck/stages/parse_docx/reference_repairer.py` (exists from Feature 10)

**What to add:** A SECOND repair pass that runs AFTER the fragment-merging pass:

```python
def detect_malformed_titles(references: list[Reference]) -> list[Reference]:
    """Detect references where title field contains journal abbreviation or garbage."""
    for ref in references:
        if _is_likely_bad_title(ref.title):
            # Attempt to re-extract title from raw_text using a different strategy
            repaired_title = _extract_title_from_raw(ref.raw_text)
            if repaired_title and len(repaired_title) > 25:
                ref.title = repaired_title
                ref.repair_applied = "title_re_extracted"
            else:
                # Mark for LLM repair
                ref.repair_applied = "needs_llm_repair"
    return references

def _is_likely_bad_title(title: str) -> bool:
    """Heuristic: titles under 25 chars are suspicious."""
    if not title:
        return True
    stripped = title.strip().rstrip(".")
    if len(stripped) < 25:
        return True
    if stripped.startswith("doi:"):
        return True
    if stripped.startswith("(20") or stripped.startswith("(19"):
        return True
    return False

def _extract_title_from_raw(raw_text: str) -> str | None:
    """Try to extract the actual title from the raw reference text.
    
    Most reference formats: Author (Year). TITLE. Journal, Vol, Pages.
    The title is usually the longest sentence-like segment.
    """
    # Split on periods, find the longest segment that looks like a title
    # (not a journal abbreviation, not author names, not DOI)
    ...
```

For references that can't be fixed by heuristics, use a **batch LLM repair call** — send all malformed references in one call:
```
Given these malformed reference entries, extract the correct title for each:
1. "Front\nBai, J. et al. (2024). ..." → title: ?
2. "Orthop\nSmith, R. (2022). ..." → title: ?
...
```

### Fix 4: Filter Empty Claims

**Where:** The claim extraction stage (after citation-first detection produces verification units).

**What to add:** Before storing claims, filter out entries where the claim text (excluding the citation marker itself) is empty or under 10 characters:
```python
def filter_empty_claims(claims: list[Claim]) -> list[Claim]:
    """Remove claims that are just citation markers with no actual text."""
    filtered = []
    for claim in claims:
        # Strip citation markers like (Author, Year) or [N]
        text_without_citations = strip_citation_markers(claim.manuscript_text)
        if len(text_without_citations.strip()) < 10:
            logger.info("Filtered empty claim: '%s'", claim.manuscript_text[:80])
            continue
        filtered.append(claim)
    return filtered
```

### Fix 5 & 6: Wire Up Quality Scoring and Coherence

**Where:** `src/refcheck/stages/verify_claims/verifier.py` — the main verification function.

**What's wrong:** `score_pdf_text()` and `check_topic_coherence()` exist but are never called. The verification function goes straight from "extract sections" to "call LLM" without scoring.

**What to change:** Insert quality scoring and coherence checking INTO the verification pipeline:

```python
async def verify_claim(claim, reference, pdf_text):
    # STEP 1: Score PDF text quality (CURRENTLY MISSING)
    from refcheck.stages.verify_claims.text_quality import score_pdf_text
    quality = score_pdf_text(pdf_text)
    text_quality_score = quality["score"]
    
    if text_quality_score < 0.3:
        # Fall back to abstract
        return _verify_abstract_only(claim, reference)
    
    # STEP 2: Extract sections
    sections = extract_top_sections(pdf_text, claim.manuscript_text, top_n=3)
    
    # STEP 3: Check coherence (CURRENTLY MISSING)
    from refcheck.stages.verify_claims.coherence_checker import check_claim_reference_coherence
    coherence = check_topic_coherence(claim.manuscript_text, sections_text)
    section_relevance = "high" if coherence > 0.10 else "low"
    
    # STEP 4: If low coherence, use retry workflow (NEW)
    if section_relevance == "low":
        return await _retry_verification_workflow(claim, reference, pdf_text, quality)
    
    # STEP 5: Normal verification
    result = await _call_verification_llm(claim, sections_text)
    result.text_quality_score = text_quality_score
    result.section_relevance = section_relevance
    
    # STEP 6: If LLM returned cannot_verify, try retry workflow
    if result.verdict == "cannot_verify":
        retry_result = await _retry_verification_workflow(claim, reference, pdf_text, quality)
        if retry_result.verdict != "cannot_verify":
            return retry_result
    
    return result
```

---

## Part 2: Cannot-Verify Retry Workflow (New Module)

### Module: `src/refcheck/stages/verify_claims/retry_workflow.py`

```python
class RetryResult(BaseModel):
    verdict: str
    confidence: float
    reasoning: str
    evidence_quotes: list[str]
    retry_strategy_used: str  # "broader_sections" | "full_paper" | "abstract" | "gave_up"
    attempts: int
    source_coverage: str      # "full_text" | "abstract_only" | "no_source"
```

### Broader Context Strategy

The key user insight: **the LLM needs the full paragraph, not keyword-matched fragments.**

When extracting sections for retry:
1. Include the **abstract** always (regardless of keyword match)
2. Include the **introduction** always  
3. Include the **results** section always
4. Include any section whose heading mentions keywords from the claim
5. For each selected section, include the **full paragraph** (not truncated)
6. Concatenate with section headings preserved

### Full-Paper Strategy

For papers under 50 pages (~100,000 chars):
- Send the entire paper text
- Use a specific prompt: "Search the ENTIRE paper below for evidence that supports or contradicts this claim. The relevant information may be in any section."

### Verification Prompt — Broader Context

New Jinja2 template `src/refcheck/prompts/verification_broad_context.md`:
```
You are verifying a scientific citation. The full context paragraph from the manuscript is:

{{ full_paragraph }}

The specific claim being verified:
{{ claim_text }}

The cited paper sections (including abstract, introduction, and results):
{{ source_sections }}

IMPORTANT: Search ALL provided sections thoroughly. The evidence may be in an unexpected section — for example, a claim about results might be supported by a sentence in the Methods or Discussion.

If the source text does not address this claim AT ALL (the paper is about a completely different topic), respond with verdict "not_relevant" instead of "cannot_verify".

Respond in JSON:
{
    "verdict": "supported" | "partially_supported" | "not_supported" | "contradicted" | "cannot_verify" | "not_relevant",
    "confidence": <0.0-1.0>,
    "reasoning": "<your reasoning>",
    "evidence_quotes": ["<direct quotes from the source>"]
}
```

**Critical addition:** The new `"not_relevant"` verdict. This is distinct from `"cannot_verify"`:
- `cannot_verify` = "I don't have enough information to judge"
- `not_relevant` = "This paper is about a completely different topic than the claim"

The user specifically asked to clearly flag when a paper is not relevant. This is a mapping/extraction problem, not a verification problem.

### Data Model Updates

```python
class VerificationResult(BaseModel):
    # ... existing fields ...
    retry_strategy_used: str | None = None  # "broader_sections" | "full_paper" | "abstract" | None
    retry_attempts: int = 0
    
# Add "not_relevant" to the verdict options
Verdict = Literal[
    "supported", "partially_supported", "not_supported", 
    "contradicted", "cannot_verify", "not_relevant"
]
```

Add to `CannotVerifyReason`:
```python
NOT_RELEVANT = "not_relevant"  # Paper topic doesn't match claim at all
```

---

## Part 3: classify_cannot_verify() — Use Real Data

The current implementation always receives default values. Fix by passing actual computed data:

```python
# BEFORE (broken — all defaults)
reason = classify_cannot_verify(
    reference_source_status=ref.source_status,
    reference_doi=ref.doi,
    reference_type=ref.reference_type,
    text_quality_score=1.0,           # ← ALWAYS 1.0
    section_relevance="high",         # ← ALWAYS "high"
    source_coverage="full_text",      # ← ALWAYS "full_text"
    had_llm_error=False,
)

# AFTER (fixed — actual computed values)
reason = classify_cannot_verify(
    reference_source_status=ref.source_status,
    reference_doi=ref.doi,
    reference_type=ref.reference_type,
    text_quality_score=result.text_quality_score,     # ← COMPUTED
    section_relevance=result.section_relevance,       # ← COMPUTED
    source_coverage=result.source_coverage,           # ← COMPUTED
    had_llm_error=result.had_llm_error,               # ← TRACKED
)
```

---

## Part 4: Full Paragraph Context for LLM

### Current Problem
The citation-first pipeline extracts a single sentence around each citation marker. When this sentence is ambiguous or short (e.g., "This has been extensively studied (Smith et al., 2020)."), the LLM has almost nothing to verify against.

### Fix
Store and send the **full paragraph** (not just the sentence) as verification context:

```python
class CitationInstance(BaseModel):
    # ... existing fields ...
    sentence_text: str        # just the sentence (for display)
    paragraph_text: str       # full paragraph (for LLM verification context)
```

The verification prompt should receive `paragraph_text` as the claim context. The `sentence_text` is still used for display in the UI and report.

---

## Part 5: Frontend Fixes

### Cannot-Verify Breakdown — Show Real Reasons
After fixing the classification, the breakdown dashboard (from Feature 10) will show real categories instead of everything being "section_irrelevant":
- "No PDF — Paywalled" (28) 
- "Not Relevant — Paper topic mismatch" (5)
- "PDF Metadata Only" (3)
- "Section Irrelevant — Relevant section not found" (8)
- etc.

### Add "Not Relevant" Verdict Color
```
not_relevant: #8b5cf6 (violet) — distinct from cannot_verify gray
```
Display: "⚠️ Paper Not Relevant" — draws attention since it indicates a citation error in the manuscript.

### Library Stats on Upload Page
Show: "Your library has X papers. These will be matched automatically."

---

## Done Criteria

**Bug Fixes:**
- [ ] Library-matched references have `source_status = "found"` (not "pending")
- [ ] Upload button shows ONLY when `!ref.pdf_path` (regardless of source_status)
- [ ] Links (DOI/PubMed/Scholar) show when no PDF + identifiers exist
- [ ] 30+ malformed titles repaired (second-pass heuristic + LLM batch repair)
- [ ] Empty claims (citation-only text) filtered before verification
- [ ] `text_quality_score` computed via `score_pdf_text()` for every verification
- [ ] `section_relevance` computed via `check_topic_coherence()` for every verification
- [ ] `classify_cannot_verify()` receives ACTUAL computed values, not defaults

**New Features:**
- [ ] Cannot-verify retry workflow: broader sections → full paper → abstract → give up
- [ ] `"not_relevant"` verdict distinguishes "wrong paper" from "can't tell"
- [ ] Full paragraph context sent to LLM (not just extracted sentence)
- [ ] Retry strategy tracked on VerificationResult (`retry_strategy_used`, `retry_attempts`)
- [ ] Verification prompt for broad context includes abstract + intro + results always

**Quality:**
- [ ] All existing tests pass
- [ ] `ruff check src/` → 0 errors
- [ ] `mypy src/` → 0 errors
- [ ] `cd frontend && npm run build` → success
- [ ] No file exceeds 200 lines
