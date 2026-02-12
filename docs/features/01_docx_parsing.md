# Feature: DOCX Parsing & Reference Extraction

**Module:** `src/refcheck/stages/parse_docx/`
**Version:** MVP
**Dependencies:** None (first stage in pipeline)
**User Intervention:** IP-1 (reference list confirmation)

---

## Purpose

Parse a DOCX manuscript to extract:
1. The full manuscript text, organized by sections
2. A structured, numbered reference list with parsed metadata
3. Citation markers within the text (e.g., "[1]", "(Smith, 2020)")
4. Zotero/Mendeley/EndNote field codes if present (for structured metadata)

**Biomedical focus:** Vancouver (numbered) citation style is highest priority. PubMed IDs (PMIDs) should be detected where present.

## Input

- File path to a `.docx` file

## Output

```python
class ParsedManuscript(BaseModel):
    """Result of DOCX parsing."""
    filename: str
    sections: list[ManuscriptSection]  # text organized by headings
    references: list[Reference]         # parsed reference list
    citation_style: Literal["numbered", "author_year", "footnote", "unknown"]
    has_field_codes: bool               # Zotero/Mendeley detected
    warnings: list[str]                 # any parsing issues encountered

class ManuscriptSection(BaseModel):
    heading: str | None
    text: str
    citations: list[InTextCitation]     # citations found in this section

class InTextCitation(BaseModel):
    raw_text: str          # e.g., "[1-3, 5]" or "(Smith et al., 2020)"
    position: int          # character offset in section text
    reference_ids: list[int] | None  # mapped to reference list (None if unmapped)
```

## Implementation Requirements

### Reference List Detection
- Identify the reference/bibliography section by heading keywords: "References", "Bibliography", "Works Cited", "Literature Cited"
- Handle cases where there is no explicit heading (references at end after a horizontal rule or numbering pattern)
- Each reference entry should be split into individual references (handle multi-line entries)

### Reference Metadata Parsing
- For each reference, extract: authors, title, year, journal, volume, pages, DOI, PMID
- DOI detection: look for "doi:", "https://doi.org/", "10.XXXX/" patterns
- PMID detection: look for "PMID:", "PubMed:" patterns (biomedical priority)
- Handle inconsistent formatting: some refs will have DOIs, some won't
- If Zotero/Mendeley/EndNote field codes are present in the DOCX XML, extract structured metadata directly — this is higher quality than text parsing

### Citation Style Detection
- Detect whether the manuscript uses numbered citations `[1]`, `[1-3]`, `[1, 5, 7]` or author-year citations `(Smith, 2020)`, `(Smith & Jones, 2020)`, `(Smith et al., 2020)` or footnote citations
- **Priority:** Numbered (Vancouver) style is most common in biomedical manuscripts — optimize for this first

### In-Text Citation Extraction
- Find all citation markers in the body text
- For numbered styles: parse ranges like [1-5] into individual reference IDs [1, 2, 3, 4, 5]
- For author-year: fuzzy match against the reference list to link
- Record the position of each citation for later claim extraction

## Edge Cases to Handle

- References split across page breaks or columns
- References containing URLs that wrap across lines
- Non-standard numbering (references numbered starting from 0, or with letters)
- Duplicate references (same paper listed twice with different numbers)
- References to non-journal sources: books, book chapters, conference proceedings, websites, government reports, preprints, clinical guidelines
- Manuscripts with supplementary reference lists (V2)
- Unicode characters in author names (accents, non-Latin scripts)
- Manuscripts where citations in text don't match the reference list numbering
- Mixed citation styles within one manuscript (rare but happens)

## What This Module Does NOT Do

- Does NOT extract claims from citations (that's Stage 2)
- Does NOT verify references exist (that's Stage 4)
- Does NOT handle PDF manuscripts (DOCX only)
- Does NOT modify the original manuscript

## Tests & Acceptance Criteria

### Unit Tests (`tests/unit/test_parse_docx.py`)

| Test ID | Test | Input | Expected | Pass Criteria |
|---------|------|-------|----------|---------------|
| P-01 | Basic numbered references | DOCX with 10 numbered refs | 10 Reference objects | All 10 parsed, ≥8 with correct title and year |
| P-02 | Author-year references | DOCX with author-year style | References with correct style | `citation_style == "author_year"` |
| P-03 | DOI extraction | References containing DOIs | DOIs correctly extracted | All DOIs matching `10.\d{4,}/` pattern extracted |
| P-04 | PMID extraction | Biomedical refs with PMIDs | PMIDs correctly extracted | All PMIDs detected |
| P-05 | Range citations | Text containing "[1-5, 7]" | Expanded to [1, 2, 3, 4, 5, 7] | 6 reference IDs extracted |
| P-06 | Field code extraction | DOCX with Zotero field codes | Structured metadata from codes | `has_field_codes == True` |
| P-07 | Messy formatting | Real-world manuscript | Best-effort extraction + warnings | No crashes, warnings populated |
| P-08 | No reference section | DOCX without references | Empty list with warning | `references == []`, warning present |
| P-09 | Large manuscript | DOCX with 150+ references | All references extracted | Count matches expected, < 30 seconds |

### Quality Metrics

| Metric | Target |
|--------|--------|
| Reference extraction precision | ≥95% |
| Reference extraction recall | ≥95% |
| Metadata field accuracy | ≥85% |
| Processing speed | <30s for 150 refs |
| Crash rate | 0% on any valid DOCX |

### Test Fixtures Needed (`tests/fixtures/manuscripts/`)
- `simple_numbered.docx` — Clean biomedical manuscript, 10 numbered references (Vancouver style)
- `author_year_style.docx` — Manuscript with author-year citations
- `messy_formatting.docx` — Real-world manuscript with inconsistent reference formatting
- `with_zotero_codes.docx` — Manuscript containing Zotero field codes
- `large_manuscript.docx` — Biomedical manuscript with 150+ references
- `no_references.docx` — Manuscript with no reference section

## Implementation Notes for AI Agent

1. Start with python-docx for text extraction
2. For field codes, parse DOCX XML directly with `lxml` — traverse `w:fldChar` and `w:instrText` elements
3. For reference parsing, use regex-based approach first, with LLM fallback for non-standard entries
4. Build incrementally: numbered refs first (biomedical priority), then add author-year
5. Run tests after every incremental addition
6. Module path: `src/refcheck/stages/parse_docx/`
