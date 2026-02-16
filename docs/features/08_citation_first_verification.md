# Feature Spec: Citation-First Verification System

**Replaces:** Feature 02 (Claim Extraction) — partially
**Modifies:** Feature 05 (Verification), Feature 06 (Report Generation)
**New:** Missing Citation Detection
**Priority:** Critical — current system misses ~65% of citations and has 100% Tier 1 failure rate

---

## Problem Statement

The current system has three critical failures:

1. **LLM-based claim extraction misses most citations.** Of 122 references in a test manuscript, only 43 were ever checked. The LLM has discretion about what to extract and it cherry-picks, skipping routine citations.

2. **Tier 1 verification is 100% broken.** Every single verification attempt at Tier 1 fails with "Verification error occurred," forcing all results to Tier 2/3. This means every verification costs 3-5x what it should.

3. **Citation format handling is incomplete.** The manuscript uses author-year format exclusively (no numbered citations). The system was designed primarily for `[N]` style.

---

## Architecture: The Citation-First Pipeline

The fundamental change: **find citations deterministically first, then use the LLM only for verification.**

### Old Pipeline (LLM-Driven Extraction)
```
Manuscript → [LLM: "find claims"] → Claims → Verify each claim
                  ↑ unreliable
                  ↑ misses 65%+
                  ↑ expensive
```

### New Pipeline (Citation-First)
```
Manuscript → [Regex: find ALL citations] → Citation Instances
         → [Deterministic: extract sentence context] → Verification Units  
         → [LLM: scope resolution for compound citations] → Scoped Units
         → [LLM: verify each unit against its reference] → Results
         → [LLM: scan uncited text for missing citations] → Warnings
```

The LLM is removed from detection entirely. It only does:
1. Scope resolution (which part of a sentence does each citation cover?)
2. Verification (does the paper support the cited text?)
3. Missing citation detection (does uncited text need a reference?)

---

## Part 1: Universal Citation Detector

### 1.1 Supported Citation Formats

The detector must handle ALL of these formats. Organized by style family:

#### Author-Year Parenthetical
```
(Smith, 2020)
(Smith et al., 2020)
(Smith and Jones, 2020)
(Smith & Jones, 2020)
(Smith, Jones, and Park, 2020)
(Smith, Jones, & Park, 2020)
(Smith et al., 2020a)                      ← year suffix
(Smith et al., 2020; Jones et al., 2021)   ← compound (semicolon)
(Smith et al., 2020, 2021)                 ← same author, multiple years
(Smith et al., 2020a, 2020b)               ← same author, year suffixes
(see Smith et al., 2020)                   ← with prefix
(e.g., Smith et al., 2020)                 ← with prefix
(cf. Smith et al., 2020)                   ← with prefix
(reviewed in Smith et al., 2020)           ← with prefix
```

#### Author-Year Narrative (Author is part of the sentence)
```
Smith (2020) showed that...
Smith et al. (2020) demonstrated...
Smith and Jones (2020) found...
Smith & Jones (2020) reported...
Smith, Jones, and Park (2020) observed...
According to Smith et al. (2020), ...
...as Smith et al. (2020) demonstrated, ...
Both Smith (2020) and Jones (2021) found...
Smith et al. (2020a, 2020b) compared...
```

#### Numbered (Square Brackets)
```
[1]
[1,2,3]
[1, 2, 3]
[1-3]
[1, 3-5, 7]
[1–3]          ← en-dash
[1—3]          ← em-dash
```

#### Numbered (Superscript)
```
text¹
text¹,²,³
text¹⁻³
```

#### Numbered (Parenthetical)
```
(1)
(1, 2)
(1-3)
```

### 1.2 Edge Cases (MUST Handle)

**Narrative citations at sentence start:**
```
"Li et al. (2012) developed a novel hydrogel."
→ Citation: Li et al. (2012)
→ Context: entire sentence
→ Scope: "developed a novel hydrogel"
```

**Narrative citation mid-sentence:**
```
"The results, as Smith et al. (2020) demonstrated, showed improvement."
→ Citation: Smith et al. (2020)
→ Context: entire sentence
→ Scope: "The results showed improvement"
```

**Multiple narrative citations in one sentence:**
```
"Both Smith (2020) and Jones (2021) found that hydrogels improve survival."
→ Citation 1: Smith (2020) — scope: "hydrogels improve survival"
→ Citation 2: Jones (2021) — scope: "hydrogels improve survival"
→ Note: shared scope — both cited for the same claim
```

**Compound parenthetical with distinct scopes:**
```
"Hydrogels reduce rejection (Kollar et al., 2018) or promote T-cell regulation (Wang et al., 2024)."
→ Citation 1: Kollar et al., 2018 — scope: "reduce rejection"
→ Citation 2: Wang et al., 2024 — scope: "promote T-cell regulation"
```

**Compound parenthetical with shared scope:**
```
"Hydrogels are biocompatible (Smith et al., 2020; Jones et al., 2021)."
→ Citation 1: Smith et al., 2020 — scope: "Hydrogels are biocompatible"
→ Citation 2: Jones et al., 2021 — scope: "Hydrogels are biocompatible"
→ Both support the same assertion
```

**Citation at end of multi-clause sentence:**
```
"They improve drug delivery, reduce inflammation, and support cell growth (Kim et al., 2023)."
→ Ambiguous: does Kim support all three, or just the last?
→ Default assumption: covers the entire sentence unless LLM scope resolution says otherwise
```

**Parenthetical year inside parenthetical citation (nested parens):**
```
"...tackling mechanical instability (Man et al., 2016), poor vascularization (Huan et al., 2024; Bai et al., 2023)."
→ Two separate citation groups within a larger sentence
→ Man: "mechanical instability"
→ Huan + Bai: "poor vascularization"
```

**Author names with particles:**
```
"(de Vries et al., 2020)"
"(van der Berg, 2019)"
"(O'Brien et al., 2021)"
"(Al-Rashid et al., 2022)"
```

**Same author multiple works:**
```
"(Dzhonova et al., 2018a, 2018b)"
→ Two citations: Dzhonova 2018a AND Dzhonova 2018b
```

**Citations with "n.d." (no date):**
```
"(Desai et al., n.d.)"
→ Valid citation, year = None
```

**Non-citation parentheticals (must NOT match):**
```
"(n = 500)"                    ← sample size
"(p < 0.05)"                  ← p-value
"(i.e., the control group)"   ← parenthetical explanation
"(Figure 3)"                  ← figure reference
"(Table 2)"                   ← table reference
"(see Methods)"               ← section reference
"(approximately 30%)"         ← parenthetical note
"(T1D)"                       ← abbreviation definition
"(CS/DBM)"                    ← abbreviation
"(PEG-MAL 20 kDa)"           ← chemical notation
```

### 1.3 Detection Algorithm

```
Phase 1: REGEX SWEEP
  1a. Find ALL parenthetical author-year patterns
      Regex family for: (Author(s), YEAR) patterns
  1b. Find ALL narrative author-year patterns
      Regex family for: Author(s) (YEAR) patterns
  1c. Find ALL numbered patterns
      Regex family for: [N], [N,N], [N-N], (N), superscript
  1d. Find ALL compound patterns (semicolons inside parentheses)

Phase 2: FALSE POSITIVE FILTER
  2a. Remove matches that are clearly not citations:
      - (n = ...), (p < ...), (p = ...)
      - (Figure N), (Table N), (Fig. N), (Supplementary ...)
      - (i.e., ...), (e.g., ...) without author names
      - Single abbreviations: (T1D), (CS/DBM), (VCA)
      - Chemical/technical: (PEG-MAL ...), (20 kDa)
  2b. Validate author name patterns:
      - Must start with uppercase letter
      - Must be followed by year or "et al."
      - Author names can contain: hyphens, apostrophes, spaces, particles (de, van, von, al-, el-)

Phase 3: COMPOUND CITATION SPLITTING
  3a. Split semicolon-separated compounds:
      "(Smith et al., 2020; Jones et al., 2021)" → 2 citations
  3b. Split same-author multi-year:
      "(Smith et al., 2020, 2021)" → 2 citations (Smith 2020, Smith 2021)
  3c. Split year suffixes:
      "(Smith et al., 2020a, 2020b)" → 2 citations

Phase 4: DEDUPLICATION
  4a. Same author + same year appearing multiple times → keep all instances (different locations)
  4b. Narrative and parenthetical for same reference in same sentence → merge into one citation instance with broader scope
```

### 1.4 Output: CitationInstance

```python
class CitationInstance(BaseModel):
    """A single occurrence of a citation in the manuscript."""
    id: int                                # sequential ID
    raw_marker: str                        # "(Smith et al., 2020)" or "[7]"
    style: Literal["author_year_parenthetical", "author_year_narrative", "numbered_bracket", "numbered_superscript", "numbered_paren"]
    
    # Location in manuscript
    paragraph_index: int                   # which paragraph
    char_start: int                        # start of the citation marker
    char_end: int                          # end of the citation marker
    section_heading: str                   # manuscript section
    
    # Parsed components
    authors: list[str]                     # ["Smith", "Jones"] or [] for numbered
    year: str | None                       # "2020" or "2020a" or None
    year_suffix: str | None                # "a", "b", or None
    number: int | None                     # for numbered styles: 7
    
    # Context
    sentence_text: str                     # full sentence containing this citation
    sentence_start: int                    # char offset of sentence start in paragraph
    sentence_end: int                      # char offset of sentence end in paragraph
    is_narrative: bool = False             # True if author is part of the prose
    
    # Reference mapping (filled in later)
    reference_id: int | None = None        # matched to reference list
    reference_title: str = ""
    mapping_confidence: float = 0.0        # how confident we are in the match
    mapping_method: str = ""               # "exact_author_year", "fuzzy_author", "number", "manual"
```

---

## Part 2: Context Extraction & Sentence Boundary Detection

### 2.1 Sentence Extraction Rules

For each `CitationInstance`, extract the **full sentence** containing it.

**Sentence boundary detection:**
- Split on `.` `!` `?` followed by whitespace + uppercase letter
- DO NOT split on:
  - `et al.` (abbreviation, not sentence end)
  - `Fig.` `Figs.` `Ref.` `Refs.` `Dr.` `Prof.` etc.
  - Decimal numbers: `3.5`, `p = 0.001`
  - Abbreviations: `e.g.` `i.e.` `vs.` `approx.` `ca.`
  - Journal abbreviations: `J. Biol. Chem.`
  - Initials: `Smith, J. A.`
- Handle sentences that span multiple lines in the DOCX

**Context window:**
- Primary: the full sentence containing the citation
- Extended: if the sentence is very short (< 30 chars), include the previous sentence too (the citation likely covers both)
- For narrative citations at sentence start: the scope is the entire sentence after the author mention

### 2.2 Multi-Citation Sentences

When a sentence contains multiple citations, each becomes a separate `CitationInstance` but they share the `sentence_text`. The scope resolution step (Part 3) determines which part of the sentence each citation covers.

Example:
```
"Hydrogels reduce rejection (Kollar, 2018) and promote T-cells (Wang, 2024)."
```
→ CitationInstance 1: Kollar, sentence_text = full sentence
→ CitationInstance 2: Wang, sentence_text = full sentence
→ After scope resolution: Kollar's scope = "reduce rejection", Wang's scope = "promote T-cells"

---

## Part 3: Scope Resolution

### 3.1 When Scope Resolution Is Needed

Not every citation needs LLM-based scope resolution. Use heuristics first:

**Heuristic 1: Solo citation in sentence → scope = entire sentence**
```
"Hydrogels are biocompatible (Smith et al., 2020)."
→ Scope: "Hydrogels are biocompatible" — no LLM needed
```

**Heuristic 2: Compound citation (all in one parenthetical) → shared scope = entire sentence**
```
"Hydrogels are biocompatible (Smith et al., 2020; Jones et al., 2021)."
→ Both Smith and Jones: scope = "Hydrogels are biocompatible" — no LLM needed
```

**Heuristic 3: Multiple separate citations in one sentence → LLM needed**
```
"Hydrogels reduce rejection (Kollar, 2018) and promote T-cells (Wang, 2024)."
→ Need LLM to determine: Kollar = "reduce rejection", Wang = "promote T-cells"
```

**Heuristic 4: Narrative citation → scope = the clause/sentence following the author**
```
"Smith et al. (2020) showed that hydrogels improve survival."
→ Scope: "hydrogels improve survival" — heuristic sufficient
```

### 3.2 LLM Scope Resolution (only when needed)

Prompt: `src/refcheck/prompts/scope_resolution.md`

Input:
- The full sentence
- List of citations found in it, with their positions
- The reference titles (if available)

Output:
```json
{
  "scopes": [
    {
      "citation": "(Kollar et al., 2018)",
      "scope_text": "hydrogels construct an immunosuppressive microenvironment to reduce transplant rejection",
      "scope_start": 45,
      "scope_end": 120
    },
    {
      "citation": "(Wang et al., 2024)",
      "scope_text": "promote the generation of regulatory T cells",
      "scope_start": 124,
      "scope_end": 168
    }
  ]
}
```

### 3.3 When to skip scope resolution entirely

- Sentence has exactly one citation (or one compound citation group) → scope = full sentence
- Narrative citation at sentence start → scope = rest of sentence
- All citations in the sentence map to the same reference → scope = full sentence
- Sentence is short (< 100 chars) → scope = full sentence

This means ~70% of citations won't need an LLM call for scope resolution, saving significant cost.

---

## Part 4: Citation-to-Reference Mapping

### 4.1 For Author-Year Citations

Match each citation to the reference list using cascading strategies:

```
Strategy 1: EXACT AUTHOR+YEAR
  - First author last name matches reference first author
  - Year matches exactly
  - Confidence: 0.95+

Strategy 2: FUZZY AUTHOR+YEAR  
  - First author fuzzy match (rapidfuzz > 0.85)
  - Year matches
  - Handles: spelling variations, transliteration, hyphenated names
  - Confidence: 0.85+

Strategy 3: FULL AUTHOR LIST + YEAR
  - Multiple authors mentioned → match against reference author list
  - "Smith and Jones (2020)" → find reference with Smith + Jones + 2020
  - Confidence: 0.90+

Strategy 4: CONTEXTUAL DISAMBIGUATION
  - If multiple references match (e.g., two "Smith, 2020" papers):
    - Check reference title against sentence context
    - Use the reference whose topic is closer to the sentence content
  - Confidence: 0.70+

Strategy 5: UNRESOLVED
  - No match found → flag for user review
  - Include in report as "Unresolved citation"
```

### 4.2 For Numbered Citations

Straightforward: `[7]` → reference #7. If #7 doesn't exist, flag as error.

### 4.3 Handling Ambiguity

When two references have the same first author and year:
- Check if the citation uses a year suffix: "2020a" vs "2020b" → map by suffix order in reference list
- If no suffix: flag both as candidates, verify against both, present both results to user

---

## Part 5: Verification Unit Construction

### 5.1 The VerificationUnit Model

This replaces the old "Claim" concept but keeps backward compatibility:

```python
class VerificationUnit(BaseModel):
    """A single citation instance ready for verification."""
    id: int
    
    # What to verify
    manuscript_text: str           # the full sentence
    scope_text: str                # the specific part this citation covers
    citation_marker: str           # "(Smith et al., 2020)"
    
    # Where in the manuscript
    location: ClaimLocation        # paragraph_index, char_start, char_end
    section_heading: str
    
    # Which reference
    reference_id: int
    reference_title: str
    reference_authors: list[str]
    
    # Citation metadata
    citation_style: str
    is_narrative: bool
    
    # Classification (determined during scope resolution or by simple heuristics)
    claim_type: Literal["factual", "methodological", "background", "attribution", "contrast", "interpretive"]
    priority: Literal["high", "medium", "low"]
    
    # From atomic decomposition (if applicable)
    atomic_claims: list[str] = []
    
    # Compatibility alias
    @property
    def extracted_claim(self) -> str:
        return self.scope_text
```

### 5.2 Claim Type Classification (Heuristic + LLM)

Classify without LLM when possible:

```
HEURISTIC RULES:
- Contains specific numbers/percentages/statistics → "factual", priority "high"
- Starts with "Author (YEAR) showed/demonstrated/found" → "attribution", priority "medium"
- Contains "unlike", "in contrast to", "whereas", "however" → "contrast", priority "high"
- Contains "is a", "are characterized by", "is defined as" → "background", priority "low"
- Contains "using", "by applying", "the method involves" → "methodological", priority "medium"
- Contains "suggests", "may indicate", "could potentially" → "interpretive", priority "low"

DEFAULT: "factual", priority "medium"
```

Only call the LLM for classification when heuristics can't determine it (saves cost). The LLM is already going to see this text during verification, so misclassification at this stage is not critical.

---

## Part 6: Missing Citation Detection

### 6.1 What Requires a Citation

In scientific writing, these statement types **must** be cited:

**MUST CITE (flag if uncited):**
- Specific numbers, statistics, percentages, prevalence rates
  - "affects 30% of patients" → needs source
  - "n = 500 participants" → needs source  
- Claims about other researchers' findings
  - "Previous studies have shown that X" → needs citation
  - "It has been demonstrated that Y" → needs citation
- Comparative or superlative statements
  - "the most effective treatment" → needs source
  - "superior to conventional methods" → needs source
- Causal claims not from the current study
  - "X causes Y" → needs source
  - "X leads to increased Z" → needs source
- Historical or temporal claims
  - "was first described in 1990" → needs source
  - "has been used since the 1970s" → needs source
- Methodological claims about established protocols
  - "The standard protocol involves..." → needs source
  - "According to established guidelines..." → needs source
- Epidemiological or prevalence data
  - "affects approximately 1.5 million people annually" → needs source
- Claims about mechanisms or pathophysiology
  - "The mechanism involves T-cell mediated destruction" → needs source (unless author's own work)
- Terminology definitions attributed to the field
  - "Hydrogels are defined as three-dimensional networks..." → needs source

**DO NOT FLAG (no citation needed):**
- Authors' own original conclusions and interpretations
  - "We found that..." / "Our results demonstrate..."
  - "We propose that..." / "We hypothesize that..."
  - "Based on our findings, we conclude..."
- Descriptions of the authors' own methodology
  - "We performed X" / "Samples were collected from Y"
  - "The study was approved by..."
- Widely accepted common knowledge
  - "Water is composed of hydrogen and oxygen"
  - "DNA contains four nucleotide bases"
  - But note: field-specific "common knowledge" still needs citations in review papers
- Structural and transitional text
  - "In this section, we review..."
  - "The following subsections describe..."
  - "As discussed above..."
- Logical deductions from data presented in the paper
  - "This suggests that X is related to Y" (if X and Y are the paper's own data)
- Defining abbreviations
  - "vascularized composite allotransplantation (VCA)"

**GRAY AREA (flag with lower confidence):**
- General field knowledge in a review paper
  - "Hydrogels have been widely used in tissue engineering" — could need a citation in a review
  - Flag as "consider adding citation" rather than "missing citation"
- Claims that paraphrase common understanding
  - "Type 1 diabetes is characterized by insulin deficiency" — very well known, but a review paper should cite it

### 6.2 Detection Algorithm

```
Phase 1: IDENTIFY UNCITED SENTENCES
  - From the full manuscript, find all sentences that contain NO citation instances
  - Group by section (Introduction, Methods, Results, Discussion, etc.)
  - Exclude: section headings, figure/table captions (handle separately), author methodology sections

Phase 2: HEURISTIC PRE-FILTER
  - Skip sentences that start with "We ", "Our ", "In this study", "Here, we"
    (likely author's own work)
  - Skip sentences that are purely structural: "The following section...",
    "As described in Section 2..."
  - Skip very short sentences (< 20 chars) — likely fragments
  - Flag sentences containing numbers/statistics as HIGH priority for LLM review
  - Flag sentences containing "has been shown", "studies suggest", "is known to"
    as HIGH priority

Phase 3: LLM CLASSIFICATION
  - For remaining sentences (the ones that passed pre-filter):
  - Send to LLM in batches (5-10 sentences per call for efficiency)
  - Ask: "For each sentence, does it make a claim that requires a citation?
    If yes, what type of citation is needed?"
  - Output per sentence:
    {
      "needs_citation": true/false,
      "confidence": 0.0-1.0,
      "reason": "Contains specific statistic (30%) without source",
      "category": "statistical_claim" | "attribution" | "causal_claim" | ...
      "suggestion": "Add citation for the 30% mortality rate"
    }
```

### 6.3 Output: MissingCitation

```python
class MissingCitation(BaseModel):
    """A sentence that should have a citation but doesn't."""
    id: int
    sentence_text: str
    paragraph_index: int
    char_start: int
    char_end: int
    section_heading: str
    
    confidence: float               # how confident we are it needs a citation
    category: Literal[
        "statistical_claim",        # contains numbers/stats
        "attribution",              # "studies have shown..."
        "causal_claim",             # "X causes Y"
        "comparative_claim",        # "most effective", "superior to"
        "historical_claim",         # "first described in..."
        "methodological_claim",     # "standard protocol involves..."
        "mechanism_claim",          # "the mechanism involves..."
        "general_field_knowledge",  # could use a citation in a review
    ]
    reason: str                     # why it needs a citation
    suggestion: str                 # what kind of citation to add
```

---

## Part 7: Fixing Tier 1 Verification

### 7.1 Diagnosis

The report shows 100% Tier 1 failure rate ("Verification error occurred" on every attempt). Likely causes to investigate:

1. **Response format mismatch**: The grounded_verification prompt expects a specific JSON schema. If the LLM returns slightly different keys or formatting, the Pydantic parser rejects it. Check:
   - Does the prompt clearly specify the exact JSON schema?
   - Does the parser handle optional fields?
   - Does the parser strip markdown code fences from the response?

2. **Timeout**: LLM calls may be timing out. Check:
   - Is there a timeout configured in `call_llm()`?
   - For long source sections, is the prompt exceeding context limits?

3. **Model name mismatch**: The report says "claude-sonnet-4-5-20250514" but the client uses "anthropic/claude-sonnet-4-5-20250929". If these are different, the retry may use the wrong one.

4. **Source section encoding**: If PDF text extraction produces garbage characters, the prompt may confuse the LLM. Check:
   - Are extracted sections clean UTF-8?
   - Are there excessive special characters?

### 7.2 Required Fix

In `src/refcheck/llm/client.py` and `src/refcheck/stages/verify_claims/verifier.py`:

1. Add detailed error logging: catch the SPECIFIC exception from Tier 1 and log it (not just "error occurred")
2. Add response format resilience:
   - Strip markdown fences (```json ... ```) before parsing
   - Handle missing optional fields with defaults
   - Try multiple JSON extraction strategies (full response, regex for JSON block, etc.)
3. Add timeout configuration: default 60 seconds per call, configurable
4. Add source text sanitization: strip non-UTF8 characters before sending to LLM

---

## Part 8: The Complete New Pipeline

### Stage 1: Parse Manuscript (existing, no change)
→ Output: ParsedManuscript with sections and reference list

### Stage 2A: Detect Citations (NEW — replaces LLM extraction)
→ Input: ParsedManuscript
→ Process: Regex-based citation detection (Part 1)
→ Output: list[CitationInstance]
→ **No LLM call. Deterministic. 100% coverage.**

### Stage 2B: Extract Context (NEW)
→ Input: CitationInstances + ParsedManuscript
→ Process: Sentence boundary detection, context extraction (Part 2)
→ Output: CitationInstances with sentence_text populated
→ **No LLM call. Deterministic.**

### Stage 2C: Map Citations to References (NEW)
→ Input: CitationInstances + Reference list
→ Process: Author-year matching, numbered matching (Part 4)
→ Output: CitationInstances with reference_id populated
→ **No LLM call for most. LLM only for ambiguous cases.**

### Stage 2D: Scope Resolution (NEW — LLM only when needed)
→ Input: Multi-citation sentences
→ Process: Heuristics first, LLM for complex cases (Part 3)
→ Output: VerificationUnits with scope_text populated
→ **LLM call for ~30% of citations only.**

### Stage 3: Match PDFs (existing, no change)

### Stage 4: Resolve Gaps (existing, no change)

### Stage 5: Verify Claims (MODIFIED)
→ Input: VerificationUnits + matched PDFs
→ Process: Tier 1 (FIXED) → Tier 2 → Tier 3
→ Output: VerificationResults with evidence_sections
→ **LLM calls. Same tier system but with Tier 1 actually working.**

### Stage 6: Detect Missing Citations (NEW)
→ Input: ParsedManuscript + all detected citation locations
→ Process: Find uncited sentences, classify (Part 6)
→ Output: list[MissingCitation]
→ **LLM call for ~30% of uncited sentences (pre-filtered by heuristics).**

### Stage 7: Generate Report (MODIFIED)
→ Input: All results including missing citations
→ Output: DOCX report + interactive data

---

## Part 9: What Happens to the "Claim" Concept?

**Keep the Claim model but rename it to VerificationUnit.** The existing Claim model fields all still apply:

| Old Claim field | New VerificationUnit field | Change |
|---|---|---|
| `id` | `id` | Same |
| `manuscript_text` | `manuscript_text` | Now always the full sentence |
| `extracted_claim` | `scope_text` | Now deterministic or LLM-scoped |
| `claim_type` | `claim_type` | Now heuristic-first |
| `reference_ids` | `reference_id` (singular) | One unit per citation, not grouped |
| `priority` | `priority` | Same |
| `section_heading` | `section_heading` | Same |
| `atomic_claims` | `atomic_claims` | Only for high-priority factual |
| (new) `location` | `location` | Always populated (deterministic) |
| (new) `citation_marker` | `citation_marker` | The raw citation text |
| (new) `is_narrative` | `is_narrative` | True if author is in prose |
| (new) `citation_style` | `citation_style` | Which format family |

**Backward compatibility:**
- VerificationUnit can alias to Claim in the API
- Existing VerificationResult model works unchanged
- Results API returns the same shape
- Frontend table/chart components work unchanged

**What changes downstream:**
- Results will have MORE entries (every citation, not just LLM-picked ones)
- Results will have complete manuscript coverage
- The report will be much more comprehensive
- The verification prompt gets better input (exact scope instead of LLM-generated claim)

---

## Part 10: Report Additions

### 10.1 Coverage Statistics (new section)
```
Citation Coverage:
  Total citations found in manuscript: 487
  Successfully mapped to references: 479 (98.4%)
  Unresolved citations: 8 (1.6%)
  References with at least one citation: 118 of 122 (96.7%)
  References never cited: 4 (list them)
```

### 10.2 Missing Citation Warnings (new section)
```
Missing Citation Warnings:
  12 sentences flagged as potentially needing citations
  
  HIGH confidence:
  - Section "Introduction", para 3: "The mortality rate exceeds 30% in untreated patients"
    → Statistical claim without source
    
  MEDIUM confidence:
  - Section "Discussion", para 7: "Hydrogels have been widely adopted in clinical practice"
    → General field claim in a review paper — consider adding citation
```

### 10.3 Citation Mapping Issues (new section)
```
Citation Issues:
  - "(Desai et al., n.d.)" — no publication year, mapped to reference 25 by author name only
  - "(Smith et al., 2020)" — ambiguous: could match reference 45 or reference 67
```

---

## Part 11: Tests

### Citation Detector Tests
- CD-01: Single author-year parenthetical detected
- CD-02: Compound semicolon citation split correctly
- CD-03: Narrative citation at sentence start detected with is_narrative=True
- CD-04: Narrative citation mid-sentence detected
- CD-05: Same-author multi-year split: "(Smith, 2020, 2021)" → 2 citations
- CD-06: Year suffix: "(Smith, 2020a, 2020b)" → 2 citations
- CD-07: Numbered [1,2,3] split into 3 citations
- CD-08: Numbered range [1-3] expanded to 3 citations
- CD-09: False positive rejection: "(n = 500)" NOT detected as citation
- CD-10: False positive rejection: "(Figure 3)" NOT detected
- CD-11: False positive rejection: "(T1D)" NOT detected
- CD-12: Author with particle: "(de Vries et al., 2020)" detected
- CD-13: Author with apostrophe: "(O'Brien et al., 2021)" detected
- CD-14: Prefix ignored: "(see Smith, 2020)" → citation is Smith 2020
- CD-15: No-date: "(Desai et al., n.d.)" detected with year=None
- CD-16: Mixed citation in parenthetical: "(reviewed in Smith et al., 2020)" detected
- CD-17: Multiple narrative citations: "Both Smith (2020) and Jones (2021) found..." → 2 citations
- CD-18: Nested parentheticals: "tackling instability (Man, 2016), hypoxia (Huan, 2024)" → 2 citations
- CD-19: Superscript numbered citations detected (if applicable)
- CD-20: Full manuscript parse: ≥95% of citations detected vs manual count

### Context Extraction Tests
- CE-01: Sentence boundary correct (not split on "et al.")
- CE-02: Sentence boundary correct (not split on decimal numbers)
- CE-03: Short sentence extends context to include previous sentence
- CE-04: Multi-line sentence in DOCX joined correctly

### Reference Mapping Tests
- RM-01: Exact author+year match → confidence > 0.95
- RM-02: Fuzzy author match → confidence > 0.85
- RM-03: Multiple-author match (Smith and Jones) → correct reference
- RM-04: Ambiguous citation (two Smith 2020 papers) → both flagged
- RM-05: Numbered citation [7] → reference 7
- RM-06: No-date citation mapped by author name
- RM-07: Author with particle mapped correctly

### Scope Resolution Tests
- SR-01: Single citation → scope = full sentence (no LLM call)
- SR-02: Compound citation → shared scope (no LLM call)
- SR-03: Multiple separate citations → LLM resolves distinct scopes
- SR-04: Narrative at start → scope = rest of sentence (no LLM call)

### Missing Citation Tests
- MC-01: "30% of patients" without citation → flagged
- MC-02: "We found that..." without citation → NOT flagged
- MC-03: "In this section, we review..." → NOT flagged
- MC-04: "Previous studies have shown..." → flagged
- MC-05: "was first described in 1990" → flagged
- MC-06: Section heading → NOT flagged

### Coverage Tests
- COV-01: Full manuscript: every citation instance found
- COV-02: Every found citation mapped to a reference
- COV-03: Every mapped citation produces a verification result
- COV-04: Zero references with zero citation instances (that actually have citations in text)
