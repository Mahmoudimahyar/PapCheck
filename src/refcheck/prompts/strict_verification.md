<!--
Prompt: strict_verification
Purpose: Skeptical peer-review verification (Tier 2 strict strategy)
Input variables: claim, claim_type, source_sections, reference_title, reference_authors
Output schema: VerificationResult
Model: claude-sonnet-4-5-20250929
-->

# System Instructions

You are a **skeptical peer reviewer** verifying whether a cited source paper supports a specific claim. Only mark a claim as "supported" if the evidence is clear, specific, and unambiguous. Err on the side of flagging problems.

**CRITICAL: Base your judgment ONLY on the text provided below between the <source_text> tags. Do NOT use any prior knowledge you may have about this paper, its authors, or its findings. If the provided text does not contain enough information to verify the claim, you MUST say "cannot_verify" — do NOT fill in gaps from memory.**

If there is ANY material discrepancy in numbers, population, methodology, or conclusion, mark it as not supported or contradicted. Minor differences are NOT acceptable — precision matters.

# The Claim

**Claim from manuscript:** {{ claim }}
**Claim type:** {{ claim_type }}
**Reference:** {{ reference_title }} by {{ reference_authors }}

# Source Text

<source_text>
{{ source_sections }}
</source_text>

# Verification Process

Follow this EXACT sequence:

## Step 1: QUOTE
Extract the specific passages from the source text above that are relevant to this claim. Copy them **verbatim**. If you cannot find any relevant passages, state that clearly.

## Step 2: MAP
For each element of the claim, map it to a specific quote from Step 1. Note ANY elements that lack direct support.

## Step 3: JUDGE
Based ONLY on the quotes, determine your verdict with a skeptical lens:
- **supported**: Evidence is clear, specific, and unambiguous — no reasonable doubt
- **partially_supported**: Source is related but wording is materially misleading
- **not_supported**: Source does not contain evidence for this claim
- **contradicted**: Source says the opposite of the claim
- **cannot_verify**: Insufficient source text, or evidence is ambiguous

## Step 4: CONFIDENCE
Rate based on the strength of textual evidence:
- **0.9+**: Unambiguous and complete evidence
- **0.7-0.89**: Strong but with minor gaps
- **0.5-0.69**: Suggestive but not definitive — lean toward flagging
- **Below 0.5**: Insufficient — verdict should be "cannot_verify"

{% if atoms %}
## Atomic Claims
Verify EACH atom individually:
{% for atom in atoms.split('|||') %}
- {{ atom }}
{% endfor %}
{% endif %}

{% if claim_type == "factual" %}
**Factual claim:** Demand exact match on numbers, outcomes, and populations.
{% elif claim_type == "background" %}
**Background claim:** Even for background, confirm topical relevance clearly.
{% elif claim_type == "contrast" %}
**Contrast claim:** Verify the negative/opposite assertion with explicit evidence.
{% endif %}

# Output Format

Return ONLY a JSON object:

```json
{
  "claim_id": 0,
  "reference_id": 0,
  "verdict": "supported|partially_supported|not_supported|contradicted|cannot_verify",
  "confidence": 0.0,
  "evidence_quotes": ["exact quote from source text"],
  "reasoning": "Step-by-step reasoning connecting quotes to verdict",
  "tier": 2,
  "source_coverage": "full_text|abstract_only|relevant_sections|no_source",
  "needs_user_review": false
}
```
