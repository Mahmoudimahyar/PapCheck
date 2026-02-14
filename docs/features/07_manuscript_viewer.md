# Feature 07: Evidence Mapping & Interactive Manuscript Viewer

**Module:** `src/refcheck/stages/extract_claims/`, `src/refcheck/stages/verify_claims/`, `frontend/`
**Version:** V2+ (depends on claim extraction + verification being complete)
**Status:** Planned

---

## Overview

This feature adds three capabilities:

1. **Positional claim mapping** — during claim extraction, record the exact location of each claim in the manuscript (paragraph index, character offsets, citation marker)
2. **Source evidence storage** — during verification, store not just the LLM's extracted quotes but the full source sections with quote positions highlighted within them
3. **Interactive manuscript viewer** — a new frontend page that renders the full manuscript with verdict-colored highlights, clickable to reveal source evidence and model reasoning in a side panel

Together, these create a visual audit trail: the researcher sees their manuscript color-coded by verification status and can click any claim to see exactly what the cited paper says and why the model reached its verdict.

---

## 1. Positional Claim Mapping

### Data Model Additions

```python
# Add to Claim model
class ClaimLocation(BaseModel):
    paragraph_index: int              # 0-based index into manuscript paragraphs
    char_start: int                   # character offset within the paragraph
    char_end: int                     # character offset end
    citation_markers: list[str] = []  # e.g., ["[7]", "[8]"]
    section_heading: str = ""         # which manuscript section

class Claim(BaseModel):
    # ... existing fields ...
    location: ClaimLocation | None = None
```

### Extraction Logic

During claim extraction (Stage 2), after the LLM returns claims:
1. For each claim, search the manuscript text for the `manuscript_text` field
2. Find the paragraph that contains this text
3. Record the paragraph index and character offsets
4. Extract the citation markers from the text (regex: `\[\d+(?:[,\-–]\s*\d+)*\]`)
5. If exact match fails, use fuzzy matching to find the closest paragraph

Edge cases:
- Same sentence cited in two claims (different citations) → different ClaimLocation with overlapping ranges
- Claim spans two paragraphs → use the paragraph containing the citation marker
- Citation in a table or figure caption → record with a flag `in_figure_or_table: bool`

---

## 2. Source Evidence Storage

### Data Model Additions

```python
class EvidenceSection(BaseModel):
    section_heading: str = ""             # e.g., "Results", "Discussion"
    full_text: str = ""                   # the complete section/paragraph from the article
    page_number: int | None = None        # if extractable from PDF
    quote_highlights: list[QuoteHighlight] = []

class QuoteHighlight(BaseModel):
    quote: str                            # the exact evidence quote
    char_start: int                       # position within full_text
    char_end: int                         # position within full_text
    match_type: Literal[
        "direct",           # verbatim or near-verbatim match
        "paraphrased",      # same meaning, different words
        "numeric_mismatch", # numbers don't match
        "absent"            # claim element not found in source
    ] = "direct"
    manuscript_element: str = ""          # which part of the claim this supports

class VerificationResult(BaseModel):
    # ... existing fields ...
    evidence_sections: list[EvidenceSection] = []   # NEW: full sections with highlights
    # evidence_quotes: list[str] still exists for backward compatibility
```

### Storage Logic

During verification (Stage 5), after the LLM returns quotes and the quote validator runs:
1. Take the source sections that were fed to the LLM (from section_finder)
2. For each evidence quote the LLM extracted:
   a. Find its position within the source section (fuzzy search)
   b. Classify the match type (direct, paraphrased, numeric mismatch)
   c. Store as QuoteHighlight with character offsets
3. Package into EvidenceSection objects with the full section text + quote positions
4. Store in `VerificationResult.evidence_sections`

Match type classification:
- similarity >= 0.95 → "direct"
- similarity >= 0.80 → "paraphrased"
- similarity >= 0.60 AND contains number mismatch → "numeric_mismatch"
- similarity < 0.60 → "absent" (quote likely hallucinated)

---

## 3. Interactive Manuscript Viewer

### Page: `/verify/{sessionId}/viewer`

#### Left Panel: Manuscript View

- Full manuscript rendered paragraph by paragraph (from ParsedManuscript.sections)
- Each claim's text range highlighted with verdict color:
  - Green (`--color-supported`): supported
  - Amber (`--color-partial`): partially_supported
  - Red (`--color-not-supported`): not_supported / contradicted
  - Gray (`--color-unverifiable`): cannot_verify
  - No highlight: uncited text
- Overlapping citations in the same sentence: use underline-style indicators with different colors per citation, not overlapping background colors
- Clicking a highlighted claim selects it and scrolls the right panel to its evidence
- Currently selected claim has a stronger highlight (border or outline)
- Legend bar at top showing color meanings and counts
- Scroll position syncs: as you scroll the manuscript, the right panel updates to show evidence for visible claims

#### Right Panel: Evidence Panel (appears on claim click)

Header:
- Claim text with verdict badge and confidence percentage
- Reference number, title, and authors
- Tier badge (1/2/3)

"Model Reasoning" section:
- The LLM's reasoning text, formatted as readable prose
- If Tier 2: both strict and generous reasoning, labeled
- If Tier 3: both models' reasoning, labeled

"Source Evidence" section:
- Each evidence section rendered as a card:
  - Section heading label (e.g., "Results — Page 4")
  - Full section text with the key quotes highlighted (bold + colored underline)
  - Match type indicator per quote: ✓ direct match, ≈ paraphrased, ⚠ numeric mismatch
- If multiple references for the claim: tabs to switch between references

"Atomic Claims" section (if available):
- Each atom with its individual verification status (checkmark / X / ?)

Footer:
- "Override Verdict" button → opens human review modal
- "Next Claim" / "Previous Claim" navigation

#### Evidence Strength Indicators

Per-quote visual indicators within the source text:
- **Direct match**: solid colored underline — source says essentially the same thing
- **Paraphrased**: dashed colored underline — same meaning, different wording
- **Numeric mismatch**: amber underline with tooltip showing "Manuscript: 30% → Source: 28%"
- **No evidence found**: claim element shown with "No supporting text found" note

---

## 4. API Endpoints

### GET `/api/sessions/{session_id}/manuscript`

Returns the full manuscript structured for rendering:
```json
{
  "title": "...",
  "paragraphs": [
    {
      "index": 0,
      "text": "Drug X reduced mortality by 30% [7] and improved...",
      "section_heading": "Results",
      "claims": [
        {
          "claim_id": 12,
          "char_start": 0,
          "char_end": 40,
          "citation_markers": ["[7]"],
          "verdict": "partially_supported",
          "confidence": 0.75,
          "reference_ids": [7]
        }
      ]
    }
  ],
  "legend": {
    "supported": 45,
    "partially_supported": 12,
    "not_supported": 3,
    "contradicted": 1,
    "cannot_verify": 8,
    "uncited": 23
  }
}
```

### GET `/api/sessions/{session_id}/evidence/{claim_id}`

Returns full evidence for a specific claim:
```json
{
  "claim": {
    "id": 12,
    "manuscript_text": "Drug X reduced mortality by 30% [7]",
    "extracted_claim": "Drug X reduced mortality by 30%",
    "claim_type": "factual",
    "priority": "high",
    "atomic_claims": ["Drug X was studied...", "Mortality reduction was 30%..."]
  },
  "verifications": [
    {
      "reference_id": 7,
      "reference_title": "A Phase III Trial of Drug X...",
      "reference_authors": ["Smith A", "Jones B"],
      "verdict": "partially_supported",
      "confidence": 0.75,
      "tier": 2,
      "reasoning": "The direction matches but...",
      "evidence_sections": [
        {
          "section_heading": "Results",
          "full_text": "In the intention-to-treat analysis... Drug X resulted in a 28% reduction in all-cause mortality (p=0.003)... The effect was consistent across age subgroups...",
          "quote_highlights": [
            {
              "quote": "Drug X resulted in a 28% reduction in all-cause mortality",
              "char_start": 42,
              "char_end": 99,
              "match_type": "numeric_mismatch",
              "manuscript_element": "reduced mortality by 30%"
            }
          ]
        }
      ],
      "atomic_results": [
        {"atom": "Drug X was studied for mortality", "verified": true, "evidence": "..."},
        {"atom": "Mortality reduction was 30%", "verified": false, "evidence": "Source says 28%"}
      ]
    }
  ]
}
```

---

## 5. Tests

### Positional Mapping Tests
- PM-01: Claim text found in manuscript → correct paragraph index and offsets
- PM-02: Claim with multiple citations → all citation markers captured
- PM-03: Claim text not found exactly → fuzzy match finds closest paragraph
- PM-04: Overlapping claims in same sentence → both mapped with correct offsets
- PM-05: Claim in figure caption → detected and flagged

### Evidence Storage Tests
- ES-01: Direct quote from source → stored with correct offsets and "direct" type
- ES-02: Paraphrased content → classified as "paraphrased"
- ES-03: Numeric mismatch → classified as "numeric_mismatch" with details
- ES-04: Hallucinated quote → classified as "absent"
- ES-05: Multiple evidence sections stored per verification

### Viewer API Tests
- VA-01: GET manuscript returns all paragraphs with claim positions
- VA-02: GET evidence returns full sections with quote highlights
- VA-03: Overlapping claims in same paragraph render correctly
- VA-04: Claim with no verification returns cannot_verify placeholder

### Quality Metrics
- ≥90% of claims successfully mapped to manuscript positions
- ≥85% of evidence quotes successfully located in source sections
- Manuscript viewer renders in <2 seconds for 150-reference manuscripts
- Evidence panel loads in <500ms per claim
