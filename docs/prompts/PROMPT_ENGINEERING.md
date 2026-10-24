# Prompt Engineering Guidelines

## Core Principles

### 1. Forced Grounding (Anti-Hallucination)
Every verification prompt must force the LLM to quote before it judges. The sequence is always:
1. Extract relevant passages verbatim from the provided source text
2. Map each claim element to a specific passage (or note its absence)
3. Make judgment with explicit reasoning tied to the quotes
4. Assign confidence

If the model cannot produce a direct quote supporting its judgment, the result is automatically "cannot_verify" with low confidence.

### 2. Prompts Are Code
- All prompts live in `src/refcheck/prompts/` as Jinja2 `.md` templates
- Never write prompts as inline strings in Python code
- Version control prompts like code — every change should be tested
- Prompt template variables must be explicitly documented in each template's header
- All LLM calls go through `call_llm()` in `src/refcheck/llm/client.py` (which uses litellm under the hood)

### 3. Structured Output Only
- All LLM calls use JSON mode
- All responses are validated against Pydantic models
- If validation fails: retry once with the error message appended, then fail gracefully

### 4. Separation of Concerns
- One prompt per task — don't combine claim extraction and verification in one call
- Each prompt should have a single, clear objective
- Simpler prompts with focused tasks produce more reliable output than complex multi-task prompts

## Prompt Template Format

```markdown
<!-- 
Prompt: {name}
Purpose: {one-line description}
Input variables: {list of Jinja2 variables}
Output schema: {Pydantic model name}
Role: {LLM role, e.g., verifier / judge / utility — models are resolved by role, never named here}
-->

# System Instructions

{role and task description}

# Context

{{ context_variable }}

# Task

{specific instructions}

# Output Format

Return ONLY a JSON object matching this schema:
{schema}

# Examples

{few-shot examples if applicable — use biomedical examples}
```

## Anti-Hallucination Techniques

### Technique 1: Explicit Knowledge Boundary
Include in every verification prompt:
> "Base your judgment ONLY on the text provided below between the <source_paper> tags. Do NOT use any prior knowledge you may have about this paper, its authors, or its findings. If the provided text does not contain enough information to verify the claim, you MUST say 'cannot_verify' — do NOT fill in gaps from memory."

### Technique 2: Quote Validation
Post-process every LLM response: check that `evidence_quotes` actually appear in the source text (fuzzy match with ≥90% similarity to handle minor whitespace/formatting differences). If a quote doesn't match → flag the result.

### Technique 3: Canary Testing
Periodically modify a well-known paper's key finding (e.g., change "30% reduction" to "45% reduction") and run verification. The LLM MUST catch this discrepancy. If it doesn't, it's using memory instead of the provided text. Track canary test results to monitor model reliability.

### Technique 4: Confidence Calibration Prompt
Include in prompts:
> "Your confidence should reflect ONLY the strength of evidence in the provided text. A confidence of 0.9+ means the source text clearly and unambiguously supports or refutes the claim. A confidence of 0.5-0.7 means the evidence is suggestive but not definitive. Below 0.5 means insufficient evidence."

### Technique 5: Dual-Strategy Verification (Tier 2, V2)
Run the same claim through two different prompt framings:
- **Strict prompt:** "You are a skeptical reviewer. Only mark a claim as 'supported' if the evidence is clear and specific. When in doubt, flag it."
- **Generous prompt:** "You are a charitable reader. Only flag a claim if it clearly misrepresents the source. Give benefit of the doubt for reasonable paraphrasing."
Agreement between both = high confidence. Disagreement = genuine ambiguity worth human review.

### Technique 6: Rendered partial-verdict taxonomy (V5.4)
The verifier/judge/confirm rubric must never hand-copy the taxonomy. `prompts/verify_taxonomy.md`
(included by the `rubric` section of `verify_claim.md`) renders the benign guards, rules R1–R7
(minus R2, an eval-labelling rule) and the six genuine partial types in precedence order (decision
sentence + first synthetic example each) from `prompts/partial_taxonomy.json` at build time via
`stages/verify_claims/taxonomy_prompt.system_variables()`. **Always pass those system variables**:
the partial renders nothing without `taxonomy`, so a call that passes only `{"section": "system"}`
silently loses the rubric. The model returns `partial_type` (one id or `"none"`),
`unsupported_elements` (≤5 phrases; they drive the evidence re-check) and `benign_notes`.
- **Co-cited block:** the user prompt lists up to 3 other references of the same sentence
  (number, title, abstract ≤250 tokens) as untrusted context; an element one of them states is
  not this reference's problem (`cocited_share`).
- **Evidence re-check:** `pack_kind="recheck"` labels a pack made of the standard passages plus
  passages searched for each unsupported element (layer `verifier_recheck`, ≤8,000 tokens).
- **Size:** the taxonomy adds ~1.8k tokens to the cached system prompt (verifier ≈3.9k o200k
  tokens). Keep additions to the rubric in the JSON file, not in the template.
- Synthetic examples only (the taxonomy shares no 6-word phrase with the evaluation manuscript);
  never paste real manuscript or paper text into a prompt file.

### Technique 7: Cache-pinned prompts and targeted new calls (V5.7)
Every V5.7 change is deterministic code or a NEW call on a small subset, so the default-mode
verifier / judge / confirm prompts and the V5.5 output schema stay byte-identical (hash-pinned in
`tests/unit/test_verify_clearance_mode.py`) and cached answers are reused; the element adjudicator
(`adjudicate_elements.md`) and union (`adjudicate_cocited.md`) prompts are unchanged too.
- **Slot audit (#2):** reuses `adjudicate_elements.md` with slot elements such as
  "time frame: 'every year'" (layer `adjudicate_slots`).
- **Slot probe (#15, experimental, `REFCHECK_SLOT_PROBE=on`):** `prompts/slot_probe.md`, role
  adjudicator, task `verify_slot_probe`. The model sees the pack and the cited span with its
  relation / direction / population words masked — never the claim's own words (CoVe / QAGS) —
  and code compares its answers; a differing answer with an exact ≥5-word quote becomes an
  element for one element-adjudicator call (layer `slot_probe`).

## LLM Call Pattern

```python
# All LLM calls go through this wrapper — never call litellm/anthropic/openai directly
from refcheck.llm import call_llm
from refcheck.models.verification import JudgeOutput

result = await call_llm(
    template="verify_claim",               # → loads prompts/verify_claim.md
    variables={"claim": claim, "passages": render_pack(pack)},  # retrieved passages, never whole papers
    output_model=JudgeOutput,              # Pydantic validation (strict JSON schema)
    role="verifier",                       # model picked by role (llm/model_registry.py), never by name
    system_template="verify_claim",        # cacheable rubric ...
    system_variables=system_variables(),   # ... with the taxonomy (verify_claims/taxonomy_prompt.py)
    cost_tracker=tracker, task="verify_verifier",
)
```

The `call_llm()` function handles: template rendering (Jinja2), litellm API call, JSON parsing, Pydantic validation, retry on failure, logging.

## Prompt Testing Protocol

When modifying any prompt:
1. Run against the existing test fixtures BEFORE deploying
2. Compare results against previous prompt version
3. Check for regressions: did any previously-correct verdicts change?
4. Run canary tests to verify grounding still works
5. Document the change and reasoning in a comment in the prompt file
