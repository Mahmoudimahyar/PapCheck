# Feature: Tiered LLM Claim Verification

**Module:** `src/refcheck/stages/verify_claims/`
**Version:** V1 (Tier 1), V2 (Tiers 2+3)
**Dependencies:** Stage 2 (claims) + Stage 4 (resolved references with PDFs)
**User Intervention:** IP-5 (version mismatch), IP-6 (ambiguity resolution)

---

## Purpose

For each claim-citation pair, verify whether the cited source paper genuinely supports the claim made in the manuscript. This is the core value of the entire system.

## Input

- `list[Claim]` from Stage 2
- `list[Reference]` with PDF paths from Stages 3-4

## Output

```python
class VerificationResult(BaseModel):
    claim_id: int
    reference_id: int
    verdict: Literal["supported", "partially_supported", "not_supported", "contradicted", "cannot_verify"]
    confidence: float              # 0.0 - 1.0
    evidence_quotes: list[str]     # exact quotes from source paper supporting the judgment
    reasoning: str                 # chain of reasoning
    tier: Literal[1, 2, 3]        # which tier produced this result
    source_coverage: Literal["full_text", "abstract_only", "relevant_sections"]
    needs_user_review: bool
    atomic_results: list[AtomicVerification] | None  # V2: for factual claims

class AtomicVerification(BaseModel):
    atom: str                      # e.g., "reduction was 30%"
    verified: bool | None          # True, False, or None (insufficient info)
    evidence: str | None           # quote from source
```

## Implementation Requirements

### Retrieval-Augmented Verification (NOT full paper feeding)
- NEVER feed the entire source paper to the verification LLM
- Use keyword search or embedding similarity to find the 3-5 most relevant sections/paragraphs from the source paper
- Feed only these excerpts to the verification LLM alongside the claim
- This reduces noise, cost, and context window pressure

### Verification Prompt Design (Forced Grounding)
The verification prompt must enforce this sequence:
1. **Quote:** LLM must first extract relevant passages from the provided source text verbatim
2. **Map:** For each atomic claim, map it to a specific quoted passage (or note absence)
3. **Judge:** Make a verdict with explicit reasoning
4. **Confidence:** Assign confidence with justification
5. If no relevant quote can be produced → verdict must be "cannot_verify", confidence must be low

Prompt template: `src/refcheck/prompts/grounded_verification.md`
All LLM calls go through `call_llm()` wrapper (litellm).

### Anti-Hallucination Measures
- Explicit instruction: "Base your judgment ONLY on the text provided below"
- Canary tests: periodically feed modified versions of known papers to verify LLM reads provided text
- If LLM's evidence quotes don't appear in source text → automatic downgrade to "cannot_verify"
- All evidence quotes validated against source text post-hoc (fuzzy match ≥90%)

### Tiered Escalation

**Tier 1: Single LLM (V1 — all claims)**
- Run Claude Sonnet 4.5 (via litellm) with forced-grounding prompt
- If confidence ≥ 0.80 and verdict is clear → accept
- If confidence < 0.80 OR verdict is ambiguous → escalate to Tier 2

**Tier 2: Dual-strategy verification (V2 — uncertain claims only, ~10-15%)**
- Run same model with two different prompting strategies:
  - "Strict" prompt: err on the side of flagging problems
  - "Generous" prompt: only flag clear mismatches
- If both agree → accept with higher confidence
- If they disagree → escalate to Tier 3

**Tier 3: Human review (V2 — disagreements only, ~3-5%)**
- Present user with: the claim, both strategies' reasoning, the relevant source excerpts
- Multiple-choice: "Supported / Partially supported / Not supported / I'll check manually"

### Verdict Rubric
- **Supported:** Source findings, fairly summarized, would lead a reasonable scientist to make the same statement
- **Partially supported:** Source is related but manuscript wording is materially misleading about magnitude, certainty, population, or mechanism
- **Not supported:** Source doesn't contain evidence for this claim
- **Contradicted:** Source says the opposite of the claim
- **Cannot verify:** Insufficient source text available, or confidence too low

### Claim-Type-Specific Behavior
- **Factual:** Full verification, strict evidence requirements
- **Methodological:** Verify method described matches source's method
- **Background:** Light check — confirm topical relevance only
- **Attribution:** Verify authorship/contribution claim
- **Contrast/negative:** Extra caution — verifying absence requires reading more
- **Interpretive:** Flag as inherently subjective, low-confidence verification only

## Tests & Acceptance Criteria

| Test ID | Test | Pass Criteria |
|---------|------|---------------|
| V-01 | Clearly supported claim | Verdict: "supported", confidence ≥ 0.85 |
| V-02 | Clearly contradicted claim | Verdict: "contradicted", confidence ≥ 0.80 |
| V-03 | Partially supported (wrong number) | Verdict: "partially_supported", identifies discrepancy |
| V-04 | Unrelated paper cited | Verdict: "not_supported" |
| V-05 | Forced grounding works | Evidence quotes all appear in source text |
| V-06 | Canary test (modified number) | LLM catches modification, doesn't rely on memory |
| V-07 | Abstract-only verification | Works with abstract, notes "abstract_only" coverage |
| V-08 | Tier escalation (V2) | Low-confidence Tier 1 result triggers Tier 2 |
| V-09 | Background claim light check | Background citation verified with less scrutiny |
| V-10 | Batch of 50 claims | Completes without error, results consistent |

### Quality Metrics

| Metric | Target |
|--------|--------|
| Agreement with expert human reviewers | ≥80% |
| False positive rate (flagged but actually fine) | ≤15% |
| False negative rate (missed a real problem) | ≤10% |
| Canary test pass rate | 100% |
| Evidence quote validation rate | ≥95% quotes found in source |
| Average time per claim verification | <30 seconds |
