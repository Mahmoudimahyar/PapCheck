# Feature: PDF Upload & Smart Matching

**Module:** `src/refcheck/stages/match_pdfs/`
**Version:** MVP (core), V1 (GROBID + LLM fallback + version detection)
**Dependencies:** Stage 1 (parse_docx)
**User Intervention:** IP-3 (confirm uncertain matches)

---

## Purpose

Match user-uploaded PDFs to references in the manuscript. This is a critical accuracy bottleneck — a wrong match produces confidently wrong verification results downstream.

## Input

- `list[Reference]` from Stage 1
- Directory path containing user-uploaded PDFs

## Output

```python
class MatchResult(BaseModel):
    reference_id: int
    pdf_path: str | None
    confidence: float                  # 0.0 - 1.0
    match_method: Literal["doi", "title_fuzzy", "grobid_structured", "llm_firstpage", "user_confirmed", "unmatched"]
    needs_user_confirmation: bool      # True if confidence < 0.90
    candidate_alternatives: list[str]  # other possible PDF matches if ambiguous
```

## Implementation Requirements

### Matching Strategy (ordered by confidence)
1. **DOI match (highest confidence, MVP):** Extract DOI from PDF metadata (PyMuPDF) or first-page text. Match against reference DOIs. Confidence: 0.99.
2. **Title fuzzy match (MVP):** Extract title from PDF first page. Fuzzy match against reference titles using `rapidfuzz` with `token_sort_ratio`. Confidence: ratio * 0.95.
3. **GROBID structured extraction (V1):** Send PDF to GROBID Docker sidecar for structured header extraction (title, authors, DOI). Match structured output against references. Higher accuracy than raw text extraction.
4. **LLM first-page match (V1, fallback):** Send PDF first page text + unmatched reference list to LLM. Ask it to identify the best match. Confidence: LLM confidence * 0.85.

### Conservative Thresholds
- ≥0.90 confidence → auto-accept (but user can still override)
- 0.60-0.89 → flag for user confirmation
- <0.60 → treat as unmatched

### Version Detection (V1)
- Compare extracted year/journal against reference metadata
- Flag if PDF appears to be a preprint but reference cites journal version (or vice versa)

## Edge Cases
- PDF has no extractable text (scanned image) → use OCR (PyMuPDF built-in) or flag (V2)
- Multiple PDFs match the same reference → present all candidates to user
- PDF matches no reference → mark as "extra upload, not in reference list"
- Reference list entry is a book/chapter but PDF is a journal article → mismatch

## Tests & Acceptance Criteria

| Test ID | Test | Pass Criteria |
|---------|------|---------------|
| PM-01 | DOI-based matching | PDF with DOI in metadata matches correct reference |
| PM-02 | Title fuzzy matching | PDF with slightly different title format matches correctly |
| PM-03 | No match found | PDF unrelated to any reference marked as unmatched |
| PM-04 | Ambiguous match | Two similar references, system flags for user confirmation |
| PM-05 | Version mismatch detection (V1) | Preprint PDF flagged when reference cites journal version |
| PM-06 | Bulk upload (50 PDFs, 60 refs) | ≥90% correctly matched at high confidence |
| PM-07 | Scanned PDF handling (V2) | Scanned image PDF triggers OCR or appropriate warning |

### Quality Metrics

| Metric | Target |
|--------|--------|
| Match precision at auto-accept threshold | ≥98% |
| Match recall (refs with uploaded PDFs that get matched) | ≥90% |
| False match rate (wrong PDF assigned) | ≤2% |
| Version mismatch detection rate (V1) | ≥80% |
