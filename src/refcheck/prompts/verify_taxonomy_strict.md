{#-
Prompt partial: verify_taxonomy_strict (included by the "rubric" section of
  verify_claim_strict.md; REFCHECK_STRICT_CLEARANCE=on, V5.6 "no quote, no clearance")
Purpose: partial-verdict taxonomy v1.1 — benign guards, rules R1-R7 (minus the
         eval-labelling rule R2) and the six genuine
         partial types. Rendered from prompts/partial_taxonomy.json (variable `taxonomy`,
         stages/verify_claims/taxonomy_prompt.py); nothing here is hand-copied.
Variables: taxonomy (TaxonomyPrompt; renders nothing when absent)
Owner: P1 (verdict logic)
-#}
{%- if taxonomy %}
# Partial verdicts: guards first, then exactly one type
Split the cited part into elements (facts, specifics, connectives, quantifiers, framing). Apply the guards in order to each absent, mismatched or overstated element; one a guard explains is no problem: add it to "dismissed" with the exact verbatim quote (5+ words) that clears it (from this source's passages; for cocited_share and secondary_source one that states the element; for cocited_share from the co-cited abstract). No quote, no clearance: the element stays a problem. Wording, framing or a secondary report never clears a time frame, mechanism or cause, recommendation or need, population or model, frequency word or number. If none survives, answer supported: the guards define what is NOT material in step (4).
G1 evidence_gap: list each element you could not find in "unsupported_elements" (≤5 short phrases from the claim); the full text is then searched for them.
{% for g in taxonomy.guards -%}
G{{ loop.index + 1 }} {{ g.id }}: {{ g.definition if g.full else g.head }} {{ g.rule }}
{% endfor -%}
Then partial_type = the FIRST genuine type that fits a surviving element: {{ taxonomy.precedence }}. Severity is major unless stated.
{% for t in taxonomy.genuine -%}
- {{ t.id }}: {{ t.rule }}{% if t.severity %} Severity: {{ t.severity }}.{% endif %} E.g. {{ t.example }}
{% endfor -%}
- coverage_limited: abstract only, and an element is merely absent from it (not contradicted).
Rules: {% for key, text in taxonomy.rules.items() %}{{ key }} {{ text }} {% endfor %}
Partial and negative verdicts need one genuine partial_type; supported needs "none" and no unsupported_elements. problem_type: the matching legacy tag ({{ taxonomy.legacy }}; or wrong_direction, wrong_population, unrelated_source).
{% endif -%}
