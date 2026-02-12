# Feature: Claim-Citation Pair Extraction

**Module:** `src/refcheck/stages/extract_claims/`
**Version:** V1
**Dependencies:** Stage 1 (parse_docx)
**User Intervention:** IP-2 (claim-citation pair review)

---

## Purpose

Use an LLM to analyze the manuscript text and extract structured claim-citation pairs: for every in-text citation, identify the specific claim it supports and classify the citation's role.

**Biomedical focus:** Common biomedical claim patterns include statistical results ("reduced mortality by 30%"), methodological references ("protocol described in [X]"), and epidemiological background ("leading cause of death worldwide").

## Input

- `ParsedManuscript` from Stage 1

## Output

```python
class Claim(BaseModel):
    id: int
    manuscript_text: str          # surrounding context (1-3 sentences)
    extracted_claim: str          # the specific claim this citation supports
    claim_type: Literal[
        "factual",          # "Drug X reduced mortality by 30%"
        "methodological",   # "We used the protocol described in..."
        "background",       # "Cancer is a leading cause of death"
        "attribution",      # "CRISPR was developed by..."
        "contrast",         # "Unlike Jones who didn't do X..."
        "interpretive"      # "Consistent with the broader literature"
    ]
    reference_ids: list[int]
    priority: Literal["high", "medium", "low"]  # based on claim_type
    atomic_claims: list[str]      # V2: factual claims broken into checkable atoms
```

## Implementation Requirements

### Claim Extraction Logic
- Process manuscript section by section
- For each citation, provide the LLM with the surrounding paragraph as context
- LLM must identify: what specific claim is being supported, which reference(s) support it
- For compound citations (multiple refs supporting different sub-claims), separate them
- For group citations (multiple refs collectively supporting one claim), keep them grouped

### Claim Classification
- Classify each citation's role to determine verification scrutiny level
- Priority mapping: factual/contrast → high, methodological → medium, background/attribution/interpretive → low

### Atomic Claim Decomposition (V2)
- For factual claims, break into independently verifiable atoms
- Example: "Smith et al. showed that drug X reduced mortality by 30% in elderly patients (n=500)" → atoms: ["drug X was studied", "mortality was the outcome", "reduction was 30%", "population was elderly", "sample size was 500"]

### Prompt Design
- Prompt template: `src/refcheck/prompts/claim_extraction.md`
- Must include: the paragraph text, the full reference list (for context), and few-shot examples using biomedical language
- Output must be valid JSON matching the Claim model
- LLM calls go through `call_llm()` wrapper (litellm)
- See `docs/prompts/PROMPT_ENGINEERING.md` for anti-hallucination techniques

## Tests & Acceptance Criteria

| Test ID | Test | Pass Criteria |
|---------|------|---------------|
| CE-01 | Single factual claim | Correctly extracts claim, assigns "factual" type, maps to right reference |
| CE-02 | Multiple refs for one claim | Groups references correctly, doesn't split artificially |
| CE-03 | One sentence, different sub-claims | Separates claims and maps each to correct reference |
| CE-04 | Background citation | Correctly classifies as "background", assigns low priority |
| CE-05 | Contrast citation ("unlike Jones...") | Classifies as "contrast", extracts the negative claim |
| CE-06 | Atomic decomposition (V2) | Factual claim broken into ≥3 verifiable atoms |
| CE-07 | Full manuscript extraction | Process entire manuscript, no crashes, ≥85% correct mappings |

### Quality Metrics

| Metric | Target |
|--------|--------|
| Claim-reference mapping accuracy | ≥85% (before user review) |
| Claim type classification accuracy | ≥80% |
| Atomic decomposition relevance (V2) | ≥75% of atoms meaningful and verifiable |
| No claim missed for high-priority citations | ≥95% recall for factual/contrast claims |
