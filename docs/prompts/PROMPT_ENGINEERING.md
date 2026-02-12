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
Model: {recommended model, e.g., claude-sonnet-4-5-20250514}
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

## LLM Call Pattern

```python
# All LLM calls go through this wrapper — never call litellm/anthropic/openai directly
from refcheck.llm.client import call_llm
from refcheck.models.verification import VerificationResult

result = await call_llm(
    template="grounded_verification",      # → loads prompts/grounded_verification.md
    variables={"claim": claim, "source_text": source_text},
    output_model=VerificationResult,       # Pydantic validation
    model="claude-sonnet-4-5-20250514",    # or configured via litellm
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
