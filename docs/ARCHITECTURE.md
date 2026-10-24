# RefCheck AI — Architecture Overview

## System Architecture

RefCheck is a web application with a FastAPI backend running a sequential verification pipeline and a Next.js frontend providing real-time progress via SSE. Pipeline stages are independently testable and produce typed Pydantic output.

```
┌──────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js 15)                          │
│  Upload → Progress (SSE) → Review → Results → Report Download    │
└──────────────────────────┬───────────────────────────────────────┘
                           │ HTTP + SSE
┌──────────────────────────▼───────────────────────────────────────┐
│                    BACKEND (FastAPI)                               │
│  API Routes (thin) → Services (orchestration) → Stages (logic)   │
└──────────┬───────────────┬───────────────────┬───────────────────┘
           │               │                   │
    ┌──────▼──────┐  ┌─────▼─────┐  ┌─────────▼─────────┐
    │  GROBID     │  │ Academic  │  │ LLM Layer         │
    │  (Docker)   │  │ APIs      │  │ (litellm)         │
    │  PDF parse  │  │ PubMed    │  │ roles → models    │
    │             │  │ CrossRef  │  │ OpenAI + Anthropic│
    │             │  │ S2, Unpw  │  │ (+ Decisions API) │
    └─────────────┘  └───────────┘  └───────────────────┘
```

## Pipeline Stages

### Pipeline Flow (MVP)
```
Upload (DOCX + PDFs)
  → Stage 1: Parse DOCX ──► ParsedManuscript
  → Stage 3: Match PDFs ──► list[MatchResult]      ← user confirms uncertain
  → Stage 4: Resolve Gaps ─► list[Reference] (updated) ← user uploads paywalled
  → Stage 6: Basic Report ─► DOCX (existence report)
```

### Pipeline Flow (V1+)
```
Upload (DOCX + PDFs)
  → Stage 1: Parse DOCX ──► ParsedManuscript
  → Stage 2: Detect Citations ► list[VerificationUnit] ← user reviews
  → Stage 3: Match PDFs ──► list[MatchResult]        ← user confirms
  → Stage 4: Resolve Gaps ─► list[Reference]         ← user uploads
  → Stage 5: Verify Claims ► list[VerificationResult] ← user resolves (V2)
  → Stage 6: Missing Citation Detection ► list[MissingCitation] ← user reviews
  → Stage 7: Full Report ──► DOCX (verification report)
```

### Stage Details

| Stage | Module | Input | Output | User Intervention | Feature Spec |
|-------|--------|-------|--------|-------------------|-------------|
| 1 | `stages/parse_docx/` | DOCX file | `ParsedManuscript` | IP-1: confirm refs | `01_docx_parsing.md` |
| 2 | `stages/detect_citations/` | `ParsedManuscript` | `list[VerificationUnit]` | IP-2: review citations | `08_citation_first_verification.md` |
| 3 | `stages/match_pdfs/` | `list[Reference]` + PDFs | `list[MatchResult]` | IP-3: confirm matches | `03_pdf_matching.md` |
| 4 | `stages/resolve_gaps/` | `list[Reference]` | Updated refs with PDFs | IP-4: upload paywalled | `04_gap_resolution.md` |
| 5 | `stages/verify_claims/` | VerificationUnits + References | `list[VerificationResult]` (V5 cascade, below) | IP-5,6: resolve ambiguity | `05_verification.md` |
| 6 | `stages/detect_citations/` (missing) | `ParsedManuscript` | `list[MissingCitation]` | IP-2b: review missing | `08_citation_first_verification.md` |
| 7 | `stages/generate_report/` | All pipeline data | DOCX report | IP-7: accept/override | `06_report_generation.md` |

**Key rule:** Stages never import from each other. They communicate only through Pydantic models defined in `src/refcheck/models/`.

**Stage 3 re-match (V5.4, `stages/match_pdfs/rematch.py`):** after the first matching pass, every
reference left without a usable PDF (none, a supplement, a scan without text, or a PDF the
identity check calls another paper) gets a second try against the uploaded PDFs — before it can
reach stage 4 and the abstract fallback. `rematch_doi`: the reference DOI printed on page 1 (or
page 2), tolerant of line breaks, spaces and "=" for "/", plus title or first-author surname on
page 1. `rematch_title`: the whole title aligned on page 1 (score ≥90) + first author + year ±1
+ identity "verified". Supplements, scans and identity mismatches are never linked; ambiguous
candidates link nothing; a PDF another reference holds firmly is reused only for a duplicate
entry. The identity check is injected by `services/stage_runners.py` (stages stay independent);
on any error the first-pass matches are kept.

**Stage 4 library re-match (V5.8, `stages/match_pdfs/library_match.py`, `services/library.py`):**
before the API lookups, a reference still without a usable PDF is re-matched against the local
PDF library with the same evidence rules; an open-access download is opt-in
(`REFCHECK_OA_FETCH`, default off; it also gates the resolver's own PMC / Unpaywall
downloads). See "V5.8" below.

## Stage 5: Verification Cascade (V5.1)

Each claim–reference pair runs through a cheap-first cascade. Every layer sees retrieved
passages, never the whole paper. V5.1 was chosen by replaying saved benchmark runs on the
Citation-Integrity test split (see "Model selection evidence" below): the cheap verifier alone
beat every verifier→judge cascade, so the expensive judge is off the main path.

```
PREFLIGHT  one tiny real call per role (screen/verifier/judge/confirm); V5.8: only the verifier
           (HARD_ROLES) fails stage 5 loudly (event + session error). Other roles degrade (G1,
           below): confirm without OpenAI → same-family claude-sonnet-5-5 (review, cost-capped),
           screen skipped, embeddings → BM25 only. A model that fails its probe is benched
           until the next probe, so real calls use the fallback that answered
SOURCE     once per reference: sanitized PDF text → 3-sentence windows (section + page) + the
           abstract as unit "A" (PubMed / Semantic Scholar / Crossref or the PDF)
RETRIEVE   BM25 top-30 ∪ embedding top-30, reciprocal-rank fusion → standard pack ≤3,000 tokens
           (abstract + best windows, labelled [A], [P1]…); expanded pack ≤8,000 tokens.
           Gold-evidence recall in the standard pack: 0.87 (old keyword finder: 0.52)
L1 SCREEN  Decisions API (gpt-6-luna), 6 predicates, one request per pair, run for ALL sourced
           pairs first (≈3 s for 300 pairs). s = min(predicates); P(problem) = 1 − s is stored for
           risk ranking, and a strong "finding_conflicts" sends a positive verdict to the judge.
           Auto-clear only if every code gate holds (full text, no non-year numbers, no negation,
           ≤60 words, not a contrast claim, no refusal, no injected instructions, s ≥ t_accept)
           AND the calibration file allows it. Current calibration (1,202 Citation-Integrity dev
           pairs, α=3%, Clopper–Pearson): no threshold certified → auto_clear=false
L2 VERIFY  role "verifier" (claude-haiku-5-5, effort low) on every sourced pair; verbatim quotes
           are validated against the passages. A positive verdict with a validated "supports"
           quote and no screen conflict is final. "insufficient" on full text → one re-run on the
           expanded pack → still insufficient → cannot_verify(insufficient_in_source)
CROSS-CHECK a NEGATIVE verdict gets a blind check by role "confirm" (gpt-6-luna — a different
           model family) on the same pack: agree → "confirmed by 2 model families"; disagree →
           "disputed", review queue, both views kept. V5.2: when the cross-check found support
           the shown verdict moves one step toward it (not_supported → partially_supported,
           not_relevant → not_supported; contradicted kept) — `verify_claims/dispute.py`;
           REFCHECK_DISPUTE_POLICY=strict keeps the verifier's verdict instead. V5.5: a figure
           credit line ("Adapted/Reproduced from X") whose cross-check quotes the depicted work
           shows the cross-check's verdict — V5.6: only for a provenance-only credit (no
           legend panel text found); a credit with panel text is judged on the panel.
           V5.8 #20 (experimental, opt-in): a not_supported verdict whose cross-check says
           supported with a validated supports quote, with a recorded screen
           finding_stated ≥ 0.7 and topic_match ≥ 0.8, is shown supported (still disputed,
           reviewed). Without OpenAI the cross-check runs same-family (G1) and says so
UNUSUAL    a POSITIVE with no validated quote, with elements still listed, or with a screen
POSITIVE   conflict / topic mismatch, gets the same cheap cross-check: if it finds a problem it
           is shown ("disputed"), softened one step like above (V5.5; unsoftened after an
           evidence re-check overturned a negative, since two of three runs were negative);
           either way the pair is queued for review.
           Opt-in REFCHECK_JUDGE_UNUSUAL_POSITIVES=1 uses the claude-sonnet-5-5 judge instead
           (measured: lower recall, ~5× the cost)
ELEMENT    V5.5: a partially_supported outcome (any path) goes ONCE to role "adjudicator"
CHECK      (claude-haiku-5-5, effort low; fallback gpt-6-luna) with one narrow question per
           listed element (dispute: both sides' elements, ≤6): stated / cocited / framing /
           wording / absent / overstated / contradicted, on the same evidence pack + co-cited
           abstracts (`verify_claims/adjudicate*.py`, `prompts/adjudicate_elements.md`, guards
           G2-G4 rendered from the taxonomy). Code clears an element only with a verbatim quote
           validated against the pack (stated) or a co-cited abstract (cocited), or a note
           (framing / wording). All cleared → supported (guards from the categories; a dispute
           stays in review); some → partial with the survivors; failure → unchanged. Layer
           `adjudicate`, consensus `adjudicated`. REFCHECK_ADJUDICATE=off disables it
CO-CITED   V5.5b: still partial after the adjudicator, with elements it found absent, and the
UNION      sentence has co-cited references with a loaded source (the run's own documents:
           full text, else abstract)? If THIS reference backs its own share (a validated
           supports / stated quote; else skipped), ONE more adjudicator call sees per-element
           passages retrieved from those references (≤3 refs, ≤3,000 tokens, ids "R12-P3";
           `verify_claims/cocited_union*.py`, `prompts/adjudicate_cocited.md`). An element
           clears only with an exact ≥5-word quote of the reference it names (numbers /
           quantifiers kept). All cleared → supported + guard cocited_share (citation-placement
           note); a dispute / failed cross-check → held (partial, review); some → fewer
           elements; failure → unchanged. Layer `adjudicate_cocited`. REFCHECK_COCITED_UNION=off
POST       contradicted → review; abstract-only not_supported → cannot_verify(abstract_insufficient);
           numeric mismatch → note + review; any LLM failure → cannot_verify(llm_error);
           refusals fall back to another model family; >5% llm_error → stage event "error".
           V5.2 notes (never change the verdict): claim numbers found nowhere in the source →
           note + review; a supporting quote that itself cites other work → "secondary
           citation". A PDF that is another paper / a scan / the supplement / a metadata page
           is never used as the article: abstract fallback, and the result names the reason
           (V5.6: only a judgeable abstract — see below)
RULES      V5.6, after the element check: deterministic number / lineage rules may turn a
           supported verdict partial (layer `post_rules`); see "Review-driven fixes (V5.6)".
           V5.8: + the figure colour-key rule (`figure_key.py`, major; a weak reading
           only adds a note)
SLOTS      V5.7 #2, before the rules: a supported verdict whose cited span adds a time frame /
           mechanism / population / recommendation stated nowhere in the source gets ONE
           adjudicator call (layer `adjudicate_slots`); a survivor → minor partial. V5.8 #31
           (opt-in): also a polarity element when a supports quote negates the span
CHECK      V5.7 #9, last: a supported verdict with a weak signal (screen finding_stated < 0.3,
FIRST      only secondary / future-work quotes, a cleared slot audit, an overturned first run
           without a supports quote) gets a "Check first" note + review flag, verdict unchanged;
           see "V5.7" below
```

### Model selection evidence (2026-10-21, `scripts/eval/compare_models.py`)

Citation-Integrity test (Sarol et al. 2024; real biomedical citations, full text), 200 pairs
common to all runs; "problem" = any gold label other than supported:

| Configuration | 6-way acc | Problem F1 (P/R) | $ / 1k pairs |
|---|---|---|---|
| **V5.1b (as shipped), live cascade run, 205 pairs** | **0.49** | **0.903 (0.90/0.91)** | **1.34** |
| V5.1 with Sonnet judge on unusual positives, same 205 pairs | 0.47 | 0.884 (0.91/0.86) | 6.29 |
| haiku-5-5 verifier + gpt-6-luna cross-check (offline replay, 200 pairs) | 0.48 | 0.907 (0.90/0.92) | ≈1.0 |
| gpt-6-luna verifier alone (low) | 0.38 | 0.879 | 0.5 |
| luna → Sonnet 5.5 judge → Sol confirm (first V5 design) | 0.40 | 0.824 | 21 |
| Sonnet 5.5 judge on everything (low / medium) | 0.39 / 0.37 | 0.822 / 0.813 | 27 |
| gpt-6.1-sol judge on everything | 0.38 | 0.773 | 18 |
| claude-opus-5-5 judge | – | refused 24% of pairs (content filter) | 41 |

Fine-grained labels in this corpus have low human agreement (κ 0.18–0.31), so 6-way accuracy is
a weak signal; problem F1 is the primary metric. SciFact test (abstracts, 210 non-synthetic
claims, live V5.1 run): problem F1 0.895 (P 0.83 / R 0.97), 6-way 61%, $0.97 per 1k pairs.
Results: `~/.refcheck/eval/results/`.

Every layer's output is appended to `VerificationResult.model_reasoning` (one entry per layer,
in `layer_path` order) and summarised in `decided_by`, `screen_p_support` / `_contradict` /
`_topic`, `layer_path`, `cost_usd`, `latency_ms` and `quotes_validated`. `tier` / `final_tier`
are 1 = screen, 2 = verifier, 3 = judge; `escalation_path` adds 4 for confirm. The results API
derives `screen_p_problem` and `confirmation` (`confirmed` / `disputed` / `same_family` /
`none`); the UI shows "Decided by", P(problem) and the per-layer trace.

### Accuracy after the V5.2/V5.3 fixes (2026-10-21)

Fixes came from a manual review of the 40 "not supported" verdicts on the V4.9 manuscript
(only 5 were right). Live re-runs with the fixes:

| Check | Before | After |
|---|---|---|
| V4.9: agreement with the manual review (40 pairs) | 5/40 | 35/40 (2 of the 5 misses are now checked against the correct paper; 1 is a scanned PDF now read with OCR) |
| Citation-Integrity test (305): problem recall / precision / F1 | 0.928 / 0.883 / 0.905 | 0.911 / 0.866 / 0.888 |
| Citation-Integrity: "not supported / not relevant" on OK or partial citations | 30 | 12 |
| SciFact test (210): problem recall / precision / F1 | 0.971 / 0.829 / 0.895 | 0.979 / 0.825 / 0.895 |

The rubric (V5.3) keeps two boundaries apart: not_supported only when nothing the reference
is cited for is stated; supported only when every element is stated without broader,
more certain or more specific wording (an earlier V5.2 rubric blurred the second boundary
and lost 4 recall points on Citation-Integrity).

### Citation & source signals (V5.2)

Each claim is one citation of one reference. Stage 2 stores the clause that reference is
cited for (`Claim.cited_for`; in "A does X (Ref1) and Y (Ref2)" Ref2 is judged on "Y" only;
V5.7 #10: in a verbless list or noun-phrase chain, "including A [2], B [3] and C [1]", the
phrases under another reference's marker are dropped and the shared main clause kept),
`claim_quality` ("fragment" = incomplete sentence) and `mapping_ambiguous` +
`candidate_reference_ids` ("Wang et al., 2024" with 2024a/b/c in the list);
`Reference.year_suffix` keeps the "2018b" letter. All are DB columns (`V52_MIGRATIONS` in
`db/engine.py`) — re-verification and report regeneration reload claims from the DB, so an
unpersisted field silently reverts to whole-sentence checking. A marker that tags a subject
or context ("Hydrogels, e.g. alginate (Ref1), reduce …", "In islets (Ref1), gels …") does not
narrow: narrowing to a bare noun phrase would let a paper that merely mentions it count as
support. Retrieval queries lead with the cited clause (`cascade.focus_query`). A duplicate
entry (`duplicate_of`) without its own PDF is verified with its original's PDF/abstract
(`verify_claims/duplicate_sources.py`), and an abstract standing in for an unusable PDF
names the problem (`source_fallback.annotate_source_fallback`, applied in `verifier.py`).

`stages/generate_report/` turns stored results into signals, shared by the report and the API:
`claim_signals.py` (cited-for clause, fragment, mapping note), `result_signals.py` (both views
of a dispute from `model_reasoning`, secondary citation, numbers not in the source, unusable
PDF) and `source_issues.py` (duplicates from `duplicate_of`, ambiguous citations, wrong /
scanned / supplement / metadata-only PDFs, titles replaced from the DOI/PMID record,
retractions). The verify stage records some of these only as notes in `reasoning`; their
wording is pinned by `tests/unit/test_result_signals.py`. Surfaces: `ResultItem.claim`
(`cited_for`, `mapping_note`, …) and `ResultItem.signals` in the results API,
`GET /api/sessions/{id}/source-issues`, `ReportPreview.source_issues`; the DOCX report's
"Bibliography & Source Issues" section and, per flagged pair, "Cited for", warnings and the
disputed views; its "Check First" section (after Critical Findings) lists the partial verdicts
that may hide a real problem — a verifier "not supported" softened by the dispute rule, or
claim figures absent from the source (`result_signals.check_first`) — so they are not filed
with the other partial findings (the preview API marks them `check_first` and lists them first); the UI's results row badges, claim card, review modal, reference badges and
the issues card on the review page.

Under `REFCHECK_PRIVACY_PROFILE=anthropic_only` the screen and embeddings are off (BM25-only
retrieval); the verifier is claude-haiku-5-5 and judge/confirm are claude-sonnet-5-5, so the
cross-check is same-family and every negative verdict is flagged for review.

### Partial verdict sub-types (V5.4)

Taxonomy v1.1 (`prompts/partial_taxonomy.json`, synthetic examples only; constants and labels
in `models/partial_types.py`) says WHY a citation is only partially supported. Routing:

```
GUARDS   benign, applied first, in order; a concern a guard clears is not a problem:
         evidence_recheck  verifier lists unsupported_elements on a partial/negative with full
                           text → targeted BM25+embedding retrieval per element over the whole
                           document → verifier re-run ONCE on standard pack + those passages
                           (≤8,000 tokens, layer `verifier_recheck`, pack kind `recheck`);
                           the second verdict is used; never together with the expanded
                           re-run; skipped when the per-pair time/cost budget is short
         cocited_share     the verifier sees the sentence's co-cited references (≤3: number,
                           title, abstract); an element another one states is not this
                           reference's problem (note: place each citation next to its clause)
         author_framing_or_example → overliteral_wording
GENUINE  exactly one partial_type per partial verdict, most severe first:
         tangential_source > specific_detail_mismatch > unsupported_inference >
         scope_overgeneralized > missing_element > certainty_overstated;
         coverage_limited = only the abstract/part was available (never a negative)
SEVERITY major, except missing_element (minor unless a whole clause is absent),
         certainty_overstated (minor unless the outcome class is upgraded), coverage_limited
```

The rubric is rendered from the JSON at prompt-build time (`verify_claims/taxonomy_prompt.py`
→ `prompts/verify_taxonomy.md`). On abstract-only partials, `missing_element` and an
uncontradicted `specific_detail_mismatch` are reported as `coverage_limited` (the raw layer type
stays in `LayerRecord.partial_type`). Numeric checks (`verify_claims/numeric_text.py`) normalise
comparison symbols (unicode ≥ ≤ ± ~ to ASCII; on the source side, symbol-font glyphs glued to a
figure such as "Z65"/"³65" for "≥65" and "pr0.05" for "p≤0.05") and ignore digits inside names
(α-1,3; 1,25-dihydroxy; 5-HT; IL-6; CD4); a quoted number only counts as a mismatch when it is
missing from the whole source. A disputed partial keeps the verifier's `partial_type` unless the
shown verdict came from the cross-check (V5.8: a verifier's `tangential_source` is kept even
then; `subtype_rules.py`).

Fields: `JudgeOutput.partial_type` / `unsupported_elements` (≤5) / `benign_notes`;
`VerificationResult.partial_type`, `partial_severity`, `author_action` (one sentence for the
author), `unsupported_elements`, `guards_applied` — all DB columns (`V54_MIGRATIONS`; NULL-safe
for older rows, whose partials are grouped as "unclassified").
`stages/generate_report/partial_findings.py` buckets results for the API and the report
(severity and author action fall back to the taxonomy defaults when not stored). A reviewer
override changes only the verdict: when it differs from the model's, the stored type,
elements, action and guards are hidden everywhere (a reviewer's partial is "unclassified"),
and "Cleared: <guard>" notes are shown on supported results only.

Surfaces: results API item fields, a `partial_type` filter (type id, `unclassified`, `guarded`
= supported with `guards_applied`, or `guarded:<guard>`; ANDed with the other filters) and
summary counts `partial_types` (every type, 0 included), `partial_severity`, `guarded`,
`guards`; `GET /api/sessions/{id}/partial-breakdown` (per type: label, meaning, major/minor,
author action, claim ids; per guard). UI: the Results page's "Partially supported — by type"
card and filter chips, a "Why partial" block (type, severity, elements not in the source,
what to do) and "Cleared: …" notes in the claim card, review dialog and evidence card; the
labels are copied to `frontend/src/lib/partial-types.ts`, pinned by
`tests/unit/test_partial_types_ts_sync.py`. DOCX: "Check First" stays; "Minor Issues" is
replaced by "Partially Supported Findings by Type" — a "How to read partial verdicts" legend,
an overview table and one sub-section per type in the taxonomy's report order (specifics,
weak/misplaced citation, inference, scope, missing pieces, certainty, coverage), each finding
with its issue type, the elements not in the source and "What to do"; then "Supported with a
Note" groups guarded results by guard (counts + short list).

Gold benchmark `refcheck_v49_gold` (`~/.refcheck/eval/refcheck_v49_gold{,.dev,.test}.jsonl`,
kept outside the repo because the manuscript is unpublished; built by
`scripts/eval/build_refcheck_gold.py --session <id> --labels labels_final.json labels_supported.json`): 186
manually reviewed (sentence, reference) pairs of the V4.9 manuscript (185 kept; dev 105 / test
80, split by reference; V5.6 extends it to 281 kept pairs — see below). 141 are pairs the tool had flagged (review A/B disagreements
adjudicated against the paper); 45 (`gold_source` "review_C") are a stratified sample of pairs
the tool rated supported, so missed problems can be measured (3 of the 45 are partial: tool
miss rate 6.7%, Wilson 95% 2.3–17.9%). Every gold partial carries its taxonomy type (two
independent labellers, κ 0.91 before reconciliation). Baseline before V5.4 (recorded verdicts,
no API calls), all 185 rows: 3-way accuracy 64.9%, over-harsh 59/106, missed partial 4/76,
missed problem 0/3 (the original 140 rows: 55.7%, 59/64, 1/73, 0/3).

Measured V5.5 results (2026-10-21; paid runs, `--max-cost` capped):

| Set | Version | 3-way acc | Over-harsh | Missed partial | Missed problem | Problem F1 |
|---|---|---|---|---|---|---|
| gold dev (105) | before (recorded) | 63.8% | 34/58 | 2/45 | 0/2 | 0.714 |
| | V5.5 | 72.4% | 20/58 | 4/45 | 0/2 | 0.782 |
| gold test (80, held out) | before (recorded) | 66.2% | 25/48 | 2/31 | 0/1 | 0.690 |
| | V5.5 | 72.5% | 17/48 | 5/31 | 0/1 | 0.711 |
| Citation-Integrity test.bal (305) | V5.3 | – | 33/70 | – | 21/235 (any problem) | 0.888 |
| | V5.5 | – | 27/70 | – | 25/235 (any problem) | 0.890 |

Dev ablation on cached layer answers: rubric + re-check 65.7% → + element adjudicator
(claude-haiku-5-5; gpt-6-luna reached 68.6%) 70.5% → + co-cited union check 72.4%. Partial
type accuracy (tool partial on gold partial): dev 66%, test 46% (eval run; 42% in the app
run). Cost per 1k pairs: Citation-Integrity $1.54 → $2.54, gold test $2.77. The app run of the
same manuscript reproduces the verdict-level gold numbers exactly (`score_recorded.py`). Held disputes (all elements cleared but the models disagreed) were
right to stay partial in 4 of 6 dev cases, so the dispute rule is kept. Trade-off: fewer
false alarms, a few more missed partials (all five held-out misses were medium/low-confidence
gold); REFCHECK_ADJUDICATE=off / REFCHECK_COCITED_UNION=off restore the stricter behaviour.

### Review-driven fixes (V5.6)

A manual review of the 191 "supported" verdicts of one app run (12 lenient: L1–L4; evidence
problems E1–E7) led to these changes. Model-facing parts are synthetic; the review data stay
outside the repo.

**Strict clearance is off by default** (`REFCHECK_STRICT_CLEARANCE=on|off`, default off; eval
`--strict-clearance on|off`; `stages/verify_claims/clearance_mode.py`). Measured on the 281-pair
gold set, the strict verifier clearance (quote `states`, "no quote, no clearance" `dismissed`
list, dismissal audit) made the verifier itself answer partially_supported on paraphrases:
over-harsh 66/198 gold-supported (V5.5: 37), missed partial 2/80, 3-way 72.2% (V5.5: 80.4%).
Off = the V5.5 verifier: prompts `verify_claim.md` / `judge_claim.md` / `verify_taxonomy.md`
and output schema (`models/verification_v55.py`, no `states` / `dismissed`) byte-identical to
V5.5 (prompt hashes verify_claim 8a9f32632e6d90a2, judge_claim b8bd3166f9dcba35), so the LLM
cache reuses the V5.5 verifier / re-check / confirm / judge answers; guards come from
benign_notes, and cocited_share is dropped unless a co-cited abstract was shown. On = the
`*_strict.md` prompts, the full `JudgeOutput` schema and the QUOTES `states` / CLEARING rules
below. Both modes keep front-matter quote exclusion and quote de-dup (E1/E6), CREDIT, SOURCE,
RULES, NOTES and the adjudicator / co-cited union rules. **Strict-mode answers are not
cached**: the 281-pair strict measurement ran without `--reuse-cache` (throw-away cache dir),
so the LLM cache holds none of its answers (offline cache check: 0/281 strict verifier hits).
Budget a strict re-run as a full paid run (about $0.74 for the 281 pairs; cap it with
`--max-cost`), or run it once with `--reuse-cache` so later strict runs reuse its answers.

```
QUOTES   (layer_audit.py, run on every layer's parsed output before routing)
         strict only: each quote names the part of the cited span it `states`; a "supports" quote with
         states "" is context only (kept in the trace as "Context only, not evidence", never
         an evidence quote; a missing field — older cache, code-built outputs — still counts).
         Front matter is never evidence (quote_context.py): the reference title, the
         author/affiliation block (author names only; journal words are header vocabulary,
         and a quote with statistics, "vs" or running text never is one), the journal
         header before the abstract (up to the first running-text sentence). Quotes
         contained in a longer quote of the same role are
         dropped, closing punctuation ignored (per layer, and across layers in the stored
         evidence_quotes). Elements no quote states go to unsupported_elements
CLEARING strict only: a guard needs a validated `dismissed` entry {element, guard, passage_id, quote}
         (dismissals.py, the adjudicator's quote rules from clear_rules.py): a ≥5-word
         quote found EXACTLY in this source and not front matter (for cocited_share: in a
         co-cited abstract shown, not its title); cocited_share / secondary_source need a
         quote about the element that keeps its figures; wording / framing /
         secondary_source never clear an element clear_rules.disqualifier() names (time
         frame, mechanism, recommendation, population/model, frequency word, number).
         benign_notes alone clear nothing. A rejected clearance becomes an unsupported
         element (normal routing). A co-cited clearance of an element this source itself
         states (an exact quote of it, or an evidence quote whose TEXT states it — never
         the model's `states` label) is kept without the citation-placement note.
         Adjudicator / co-cited union check: never a title / author block / header quote
         (also the co-cited reference's own title / header); "framing" needs a ≥5-word
         quote; rule elements ("number:", "lineage:") are never sent to the model
CREDIT   a figure credit ("Adapted from X") is judged on its legend panel
         (credit.credit_panel: the text from the panel label — or the end of the previous
         credit, which may end in "et al." — to the credit; ≤1,200 chars; legend
         boilerplate such as "*p < 0.05", "n = 3 per group", scale bars, "mean ± SEM"
         removed: legend_boilerplate.py): CITED FOR = "Figure panel adapted from this
         source: <panel>". Credit formats: a ", 2019" / "(2019)" year, a licence tail, a
         leading "Image / Figure", "(Adapted from X)", "..., adapted from X", captions
         "Supplementary Figure" / "Extended Data Fig.". No panel text, or an abstract-only
         source (credit.without_panel) → provenance only (V5.5 dispute rule) and a
         supported verdict gets "Figure credit: provenance verified; the panel content was
         not checked." + review
SOURCE   an abstract under 300 chars, a single sentence under 50 words or mostly the
         title never stands in for a mismatched / scanned / supplement PDF →
         cannot_verify (reference_mismatch or the PDF reason) without a model call
         (source_fallback.judgeable_abstract; a sentence may start with "18F", "mRNA",
         "p53"; "et al." / "e.g." never end one)
RULES    after the element check (outcome_rules.py; the only post-routing checks that
         change a verdict; layer `post_rules`, "Rule check", label layer, review flag):
         number  full text only: a cited-span figure stated nowhere in the source
                 ("10 000" / thin-space thousands are one figure) while the source states
                 figures of the same kind (unit, label or words, and the object after
                 "in / of"), all >2× different and none of the same unit within rounding
                 (<1.25×) → partial, specific_detail_mismatch, major. A bound ("more
                 than X") that any same-kind figure satisfies → only a gross
                 understatement (>5×), minor, naming the satisfying figure. Source
                 figures of 0 / "000" are never compared
         lineage "Building on these results" / "Following this," / "Subsequently" … (a
                 result noun or a bare determiner; never "Later-stage", "Following this
                 protocol") while this reference is older than the work cited in the
                 previous sentence by a real author-year marker ("(Smith et al., 2018)",
                 "Lee (2019)"; never "Over 2020 grafts", "DSPE-PEG 2000") → partial
                 (minor; a partial gains the element)
         A supported verdict demoted by a rule drops the element check's "supported
         instead of partially supported" note; consensus_type becomes "rule" (a disputed
         / unconfirmed consensus is kept)
NOTES    quoted-number warning: figures glued to units/words are split ("10mg", "8-mm")
         and a figure the whole text states with the same kind is not a mismatch;
         secondary-citation note only when the paper does not state the point itself
         (a marker-free supporting quote in its Abstract / Results / Conclusion —
         elsewhere only when it reports data: a figure, "we found", "in the X group" —
         or such a sentence from a BM25 search of the abstract + best windows; never for
         a review: reference type, "review" / "meta-analysis" in the title, "this review"
         / "we summarize" in the abstract; own_statement.py)
```

Gold set V5.6: review D (the 191 cases, 174 pairs, `gold_source` "review_D") is added to
`refcheck_v49_gold` — 281 kept pairs (dev 162 / test 119; 78 pairs were already gold and keep
their label). Rebuild: `scripts/eval/build_refcheck_gold.py --session <V5.3 session>
--labels labels_final.json labels_supported.json labels_review_d.json --source-session
review_D=<V5.5 session>`. Recorded scores (no API): V5.3 73.7% 3-way, V5.5 80.4% (dev 81.5 /
test 79.0; over-harsh 37/198, missed partial 13/80). The review_D rows were drawn from V5.5's
own "supported" verdicts, which flatters V5.5; `score_recorded.py` reports a separate
review_D block (V5.5: missed partial 13/13, over-harsh 0/161) to measure later versions.

Measured V5.6 (default, strict clearance off; 281 gold pairs, `--reuse-cache`, $0.24):
3-way 81.1% (V5.5 80.4%), missed partial 7/80 (13/80), over-harsh 39/198 (37/198), missed
problem 0/3, problem F1 0.768 (0.737). 2 gold-supported pairs became cannot_verify by the
intended wrong-PDF rule (mismatched PDF, 99-character abstract), counted as 3-way errors.
Strict clearance on: 72.2%,
missed partial 2/80, over-harsh 66/198.

### V5.7: missed problems and over-harsh flags (2026-10-22)

Every change is deterministic or a NEW targeted call on a small subset: the default-mode
verifier / judge / confirm prompts and the V5.5 output schema are byte-identical (hash-pinned),
and the element-adjudicator / union prompts are unchanged, so cached answers are reused. Each
proposal can be switched off for an ablation with `REFCHECK_V57_DISABLE="1,3,..."`
(`verify_claims/v57.py`); #14 and #15 are experimental and off by default.

| # | Change | Where |
|---|---|---|
| 1 | Re-check closure: a re-check upgrade to "supported" is final only when the first run was partial with a validated supports quote; otherwise the first run's elements go to the element adjudicator on the re-check pack (exact quotes clear; a survivor keeps the pair partial), also on the overturn path | `recheck_closure.py`, `cascade.run_cascade` |
| 2 | Slot audit of a "supported" verdict: a time-frame / mechanism / population / recommendation phrase of cited_for absent from the whole source, the validated quotes and a synonym lexicon (trigger only; frequency and species groups never bridge a duration or another species) becomes an element for ONE adjudicator call (layer `adjudicate_slots`); a survivor gives a minor partial typed by class | `slot_audit.py`, `slot_lexicon.py`, `slot_apply.py` |
| 3 | Diff-based disqualifier: only a disqualifying phrase the clearing quote does not state in its OWN words blocks framing / wording (no synonym groups: a frequency only by the same unit's frequency, a population only by a form of the same one, `slot_lexicon.stated_strictly`); modal author readings exempt; specificity and relational words added | `clear_rules.py` (+ callers) |
| 4 | Union holds released when every element is cleared with exact quotes (dispute + review flag kept) | `cocited_union_apply.py`, `adjudicate_result.hold_reason` |
| 5 | Loose about-check (Schwartz–Hearst abbreviations, meta words stripped, ≥40% of the content words and at least 2 of them, exact quotes only) | `clear_rules.about_element`, `abbrev.py` |
| 6 | Credit-panel rubric: a visual-only survivor the adjudicator found "absent" (a time-point label only when the text states no time point) or a number-free survivor whose note says the SOURCE hedges on a figure credit becomes a note ("check the source figure"), not a survivor | `credit_rubric.py` |
| 7 | Fragment / anaphoric spans (not "such as X" / "both X and Y" lists): no dispute softening, no clearing to supported | `fragment.py`, `dispute.disputed_verdict` |
| 8 | The cross-check never upgrades a partial verifier verdict | `escalation.cross_check_positive` |
| 9 | "Check first" triage of supported verdicts (screen finding_stated < 0.3, only secondary / future-work quotes, a cleared slot audit, a re-check flip of a first run without a supports quote): note + review flag, verdict unchanged | `check_first.py`, `result_signals.check_first` |
| 10 | Positional attribution in multi-marker sentences: list / noun-phrase phrases under another reference's marker leave this reference's cited_for (Stage 2) | `detect_citations/cited_for_positional.py` |
| 11 | Sub-types: survivor types on "unchanged" outcomes, an "absent" survivor no longer vetoes the others' type, all-absent on abstract-only → coverage_limited, a same-element re-check keeps the first type | `adjudicate_result.py`, `partial_fields.py`, `recheck_closure.keep_first_type` |
| 13 | Co-cited-only clearance (every substantive element only "cocited") → not_supported / tangential_source + citation-placement note | `adjudicate_tangential.py` |
| 14 | Experimental, `REFCHECK_SUBJECT_PREPEND=on`: sentence subject prepended to a subjectless cited_for | `detect_citations/cited_subject.py` |
| 15 | Experimental, `REFCHECK_SLOT_PROBE=on`: one blind slot-probe call for a triaged supported verdict (`prompts/slot_probe.md`, layer `slot_probe`) | `slot_probe*.py` |

#12 is eval hygiene (below); #16 (auto-fetch of the correct full text for a mismatched PDF) is
not implemented. Note that cited_for is computed at detection time, so an existing session
picks up #10 / #14 only when citation detection runs again.

Eval (`scripts/eval`): `--screen-from <run>` reuses a run's recorded screen answers (a pair whose
cited_for a V5.7 rule changed is screened again, `eval_parity.fresh_screens`); `--offline` is
cache-only (keys blanked, a missed call is never sent: the pair is marked `needs_call` and scored
from `--fallback-from`, and `summary.json` reports the calls and a lower-bound $; with
`--live-roles adjudicator --live-keys ANTHROPIC_API_KEY_BACKUP` that role's uncached chat calls
are sent through the normal client and cached, every other key stays blank, `--max-cost` caps
them, and `--live-check` lists them as `live-chat:<role>` without sending; `eval_live`); gold rows get
the current cited_for (`eval_parity.gold_row_cited_for`, 4 of 281 rows change) and
Citation-Integrity rows only a V5.7-narrowed one (`ci_cited_for`). Scoring (#12): evidence_gap ≡
coverage_limited, a merged gold row is scored on its most severe copy, every block reports
TPR / TNR, near vs far misses, review-tier recall (a missed partial with needs_review or "check
first") and review load, with dev / test / eval-flag / gold-source groups.
`scripts/eval/ablate_v57.py` replays offline once with everything on and once per disabled
proposal; `scripts/eval/build_ci_subset.py` writes the 108-row Citation-Integrity subset.

Measured offline (281 gold pairs, `--offline --screen-from gold-v56-off-all`, $0; with every
proposal disabled the replay reproduces V5.6 exactly). 8 pairs need new calls (#1: 2,
#2: 2, #10: 4) and are scored with their V5.6 verdict here:

| | V5.6 dev | V5.7 dev | V5.6 test | V5.7 test | V5.6 all | V5.7 all |
|---|---|---|---|---|---|---|
| 3-way | 81.9% | 85.6% | 81.5% | 84.0% | 81.7% | 84.9% |
| over-harsh | 22/112 | 18/112 | 17/84 | 14/84 | 39/196 | 32/196 |
| missed partial | 2/46 | 2/46 | 5/34 | 5/34 | 7/80 | 7/80 |
| type acc (flagged) | 28/44 | 29/44 | 13/29 | 13/29 | 41/73 | 42/73 |
| review-tier recall (partial) | 97.8% | 97.8% | 91.2% | 94.1% | 95.0% | 96.2% |

9 pairs fixed, 0 broken. Ablation (dev): every proposal is neutral or helpful; disabling #4
costs +2 over-harsh, #3 / #5 +1 each, #7 / #13 one 3-way error each, #11 one type; on test
#5 +2 and #6 +1 over-harsh. No proposal raised dev over-harsh or missed partials, so none was
switched off. #2 fires on no dev pair: its two true positives and the choice not to exempt
slot phrases found in co-cited full texts were informed by TEST pairs, so #2's test numbers
are not held-out.

Review fixes (same day, offline replay unchanged: every headline number above is identical,
per-pair only one dev gold-partial credit keeps its partial without the rubric and two dev
union checks clear fewer elements): #3 judges the clearing quote on the element's own slot
words (the synonym groups had merged species, "transplant" / "recipients" with "in vivo",
and let "years" state "every year"); #5 needs >= 2 shared content words (the
token_set_ratio branch accepted one shared word); #6 never clears a "contradicted"
survivor or a bare "may" note; #7 no longer treats "such as" / "both ... and" lists as
anaphors.

Measured with live adjudicator calls (2026-10-22, `--offline --live-roles adjudicator`,
Anthropic backup key, $0.004; the OpenAI account had no credits left, so the 4 #10 pairs that
need a new verifier call + embedding + screen are still scored with their V5.6 verdict):
3-way 85.4% (V5.6 81.1%), missed partial 4/80 (7/80), over-harsh 32/198 (39/198), missed
problem 0/3, problem F1 0.814 (0.768), partial type 43/73; 12 pairs fixed, 0 broken; all 4
remaining missed partials carry the "check first" review flag (review-tier recall 100%).
Citation-Integrity was not re-measured (OpenAI credits exhausted).

### V5.8: outages, colour keys, library re-match, sub-types, round-2 fixes (2026-10-23)

Default-mode verifier / judge / confirm / adjudicator prompts and the V5.5 schema are
unchanged (hash-pinned), so cached answers are reused. Every accuracy change below is
deterministic or switchable (`REFCHECK_V57_DISABLE`, numbers 11 and 20-33). The rules
without DEV evidence (#20, #24, #25, #29, #31, #32, #33: derived from TEST errors or never
measured live) are an experimental tier, OFF unless `REFCHECK_V57_ENABLE` lists them
(`v57.OPT_IN`); `ablate_v57.py --opt-in` measures them as with<n> runs.

**G1 provider outages degrade instead of aborting** (`llm/candidates.py`, `degradation.py`,
`degraded_guard.py`, `role_checks.py`). Only the verifier is a hard role (`HARD_ROLES`):
stage 5's preflight (`verifier._preflight`) and the eval preflight (`eval_roles.check_roles`;
a single-role mode still needs the role it measures) fail only when it is dead. When no
normal confirm model works (no key, no credits, benched by a failed probe — never after a
single refusal) the cross-check runs on `claude-sonnet-5-5` (effort low; haiku only when the
verifier is sonnet; never the verifier's own model): `families_match` is true, so a
confirmation is "same family only" + review, and dispute notes say "a second model of the
same family (degraded cross-check)" (`dispute.who`). Spend per degraded role per run is capped
(`REFCHECK_DEGRADED_MAX_USD`, default min($2, 25% of the run budget); past it the layer fails
and the verifier's verdict goes to review). Each degraded call reserves its estimated cost
(the role's mean degraded call, else $0.03) under the tracker's lock before it is sent and
releases it afterwards, so 12 concurrent pairs cannot all pass the cap: spend stays within
the cap plus about one call (`degraded_guard.guard_degraded`, `CostTracker.reserve`).
`REFCHECK_DEGRADED_FALLBACKS=off` disables the fallback. A dead screen is skipped; failed
embeddings mean BM25-only retrieval. Each degradation records role, mode, cause (billing /
auth / no_key / not_found = persistent, with an action such as "Add credits to the OpenAI
account…"; network / rate limit = temporary) and effect. A soft role (screen / embedding) is
reported degraded at once for a persistent cause, but for a transient one only from the third
failure in the run, with the count ("… for 4 failed calls; the other calls ran normally");
a persistent cause replaces a transient one on the run's tracker, never the reverse. It is shown by `/api/health` (see LLM Integration), the model-status card (amber dot;
the fix is shown even when the card is collapsed), the stage-5 SSE message ("Degraded: …") and
the report: stage 5 saves `<session>/llm_degradations.json` (also when it fails) and the
report's methodology note gains a "Degraded mode" paragraph that qualifies the "different
family" re-check (`report_sections._add_degraded_note`).

**G2 figure colour keys** (`figure_key_claims.py`, `figure_key_source.py`, `figure_key.py`,
`figure_colors.py`; called from `outcome_rules` next to the number / lineage rules). A legend
colour claim ("CD8⁺ (green)", "red: CD8", "CD8/CD4/DAPI (red/green/blue)"; marker-like names
only) is compared with the source figure's key: coloured text spans of the PDF text layer, else
local Tesseract OCR of the figure rendered at 300 dpi (min-channel image for OCR; the colour
is read on the glyph pixels only — the ink must be the minority of the word box and the
background must not itself be coloured, so a white or black label over a stained micrograph
has no key colour), on pages that name every claimed marker. The whole read is cached per
(PDF, modification time, markers), failures included, under a per-PDF lock; it runs off the
event loop (`cascade.run_cascade`) and the rule's second call is a cache hit. A verdict
changes only for a decisive conflict: ≥ 2 claimed markers in ≥ 2 claimed colours, a key group
with a confident colour for every claimed marker and ≥ 2 colours among those markers, no group
that agrees, and either every claimed marker contradicted (not red vs orange) or two markers
swapped → partially_supported / specific_detail_mismatch / major, element "colour key: …"
first (locked: `adjudicate_rules.LOCKED_PREFIXES`). A weaker reading (one marker, one of two
contradicted, a second colour supplied only by another word such as DAPI) adds a review note
only. Free, no model call. Offline check on the validation session: 12 pairs mention colours,
5 carry a checkable colour claim, 2 are flagged — both the one legend swap the manual review
found; 0 false positives. Not checked by design: plot elements ("blue line", "red bars") and
keys drawn as coloured boxes beside black text.

**G3 local-library re-match** (`stages/match_pdfs/library_match.py`, `services/library.py`,
`library/store.py`; stage 4, before the API lookups, off the event loop). A reference with no
PDF, or whose PDF is another paper, a supplement, a scan or unreadable, is looked up in the
shared library (`REFCHECK_SHARED_LIBRARY_DIR`, default `~/.refcheck/library`): its DOI / title
key, `library.db`, then a title + first author + year scan of every library PDF, with the V5.4
re-match evidence rules (never a mismatch, supplement, scan, byte-identical copy of the
rejected upload, or ambiguous match; a file under the reference's own key only when the
identity check says "verified"). The library no longer stores mismatches, supplements or scans,
and a stored wrong copy is replaced only by a verified PDF. Optional open-access fetch
(`library/oa_*.py`): `REFCHECK_OA_FETCH=on` (default **off**; refused under pytest), Unpaywall
by DOI with `REFCHECK_CONTACT_EMAIL` (sent only to Unpaywall), Europe PMC, PMC; HTTP 200 + PDF
type + size cap + signature, ≤ 3 candidates per reference, ≤ 25 references per run, each
identity-checked before use. Offline audit of the V4.9 session: 19 references without a usable
PDF (14 none, 3 wrong paper, 1 scan, 1 supplement); the library holds no correct copy of any of
them (its copies of refs 22 / 34 are the same wrong uploads, ref 108's is the supplement — all
now rejected), so the dry run changes nothing: they need correct PDFs from the user or a
consented OA fetch. The resolver's own PMC / Unpaywall PDF downloads run only with
`REFCHECK_OA_FETCH=on` and never under pytest (`resolver.downloads_allowed`); otherwise a found
reference keeps its journal link. Its Unpaywall client no longer falls back to a placeholder
contact address (`UNPAYWALL_EMAIL`, else Unpaywall is skipped). When a library / OA copy
replaces an unusable upload, the rejection is kept (`Reference.replaced_upload_reason`,
persisted) and the report / UI list it as a source issue ("replaced_pdf": the uploaded PDF is
a different paper / the supplement / a scan; replace the attached file).

**G4 gold reconciliation** (outside the repo: `~/.refcheck/eval/gold_work/reconciliation_v58.md`,
`labels_*_v58.json`, `validate_gold_v4.py`). The 9 review-D conflicts were re-read against the
full texts: 2 labels changed (Hoffman 2013, dev: partial → supported, the co-cited March paper
states the link; Liu 2022, test: supported → partial / unsupported_inference / major), 1 type
changed (Zhou 2020: specific_detail_mismatch → scope_overgeneralized), 1 confidence lowered;
splits and totals unchanged (198 / 80 / 3). Rebuild: `build_refcheck_gold.py --session
sess_e1830471df0b --labels gold_work/labels_final_v58.json gold_work/labels_supported_v58.json
gold_work/labels_review_d_v58.json --source-session review_D=sess_1282425ded60`. Both label
changes go against V5.7's verdicts, so V5.7 re-scored on this gold is 85.3% (85.4% before).

**G5 sub-types** (`subtype_rules.py`, in the #11 bundle). Adjudicator side: own share
unsupported (full text, the shown partial is the cross-check's, the element check cleared only
"cocited", every survivor absent / overstated / a refused cocited clearance) →
`tangential_source` (the verdict stays partial); survivors that are only exclusive terms the
source contradicts or overstates → `certainty_overstated`; a cross-check
`specific_detail_mismatch` whose survivors are all absent and number-free → `missing_element`.
Shown-result side (`partial_fields.corrected_type`): a cross-check partial keeps the verifier's
`tangential_source`; a softened "not relevant" that the cross-check typed scope → scope; an
untyped re-check inherits the earlier genuine type.

**G6 round-2 fixes** (switches 20-33, `v57.py`; `round2_rules.py`, `framing_rules.py`,
`subtype_round2.py`, `slot_polarity.py`). Default on: #21 a clearing quote is retried without
leading / trailing function words; #22 a "stated" answer whose note hedges ("not explicitly",
"paraphrase-level") counts as overstated; #23 author-framing scaffolds — an "absent" element
that is NOTHING but an enumeration ("three phases"), positioning contrast ("rather than"), meta
word or concessive link ("even if"), with the scaffold in the cited span and no disqualifier
(time frame, mechanism, population, number…); any content word left ("unlike tacrolimus",
"prevented rejection even when given 7 days after transplantation") keeps it; never an
overstated / broadened / contradicted element; #26 noun-phrase lists → missing_element; #27 a
trigger-free "overstated" is re-checked as wording only when the model's own note calls the
difference wording / paraphrase ("the source only says anti-inflammatory" stays
overstated); #28 "check first" when a supported verdict's own "missing" names absent content
(triage only); #30 deficit terms in the union query for property shortfalls (live).
Experimental (opt-in): #20 screen tie-break — a not_supported verdict whose cross-check says
supported WITH a validated supports quote and whose recorded screen has finding_stated ≥ 0.7
and topic_match ≥ 0.8 is shown supported (disputed + review kept; never not_relevant, a
fragment, the strict policy or without a screen); #24 an "absent" / "cocited" survivor that
restates an element cleared with a quote (every content word matched both ways, no negation,
quantifier, exclusivity, number or population word added or dropped) is cleared WITHOUT a
quote, so it never releases a dispute; #25 the co-cited about-check accepts one side of
"X or Y" and initialisms of consecutive content words ("FBR" = "foreign body reaction", never
"For Both Rats"); #29 overstated / broadened survivors also go to the co-cited union check
(live); #31 a polarity trigger in the slot audit (live); #32 contradicted exclusivity /
consequence sub-types; #33 a quantifier survivor → scope_overgeneralized. Eval: `coverage_limited` matches a gold `missing_element` whose
secondary types include `evidence_gap` (F15, `eval_partial`).

**G7 code health**: ruff clean on src / scripts / tests, mypy clean on src, frontend `tsc` and
`npm run lint` (0 warnings); `lib/types.ts` and `lib/api.ts` are barrels over domain modules,
`claims/page.tsx` is split (`claims-table.tsx`); pytesseract is loaded through a typed Protocol
in `match_pdfs/ocr_extractor.py`.

Eval: `--embedding-miss bm25` (with `--offline`) turns an uncached embedding into BM25-only
retrieval instead of a needs_call pair — what the app does without OpenAI — so pending
adjudicator calls can be measured live while OpenAI has no credits.

Measured offline (281 gold pairs, `--offline --screen-from gold-v56-off-all --fallback-from
gold-v57-live-adj --embedding-miss bm25`, $0) after the V5.8 review fixes (strict #23 / #27,
the experimental tier off). V5.7 = the 2026-10-22 hybrid run re-scored on the V5.8 gold. 5
default pairs need new calls (1 adjudicator; 4 verifier + screen, #10) and are scored with
their V5.7 verdict. The default V5.8 numbers below contain no rule tuned on TEST errors, so
the test column is the held-out figure:

| | V5.7 dev | V5.8 dev | V5.7 test | V5.8 test | V5.7 all | V5.8 all |
|---|---|---|---|---|---|---|
| 3-way | 85.6% | 86.9% | 84.9% | 85.7% | 85.3% | 86.4% |
| over-harsh | 19/113 | 18/113 | 14/83 | 14/83 | 33/196 | 32/196 |
| missed partial | 1/45 | 0/45 | 4/35 | 3/35 | 5/80 | 3/80 |
| missed problem | 0/2 | 0/2 | 0/1 | 0/1 | 0/3 | 0/3 |
| type acc (flagged) | 31/44 | 38/45 | 14/31 | 18/32 | 45/75 | 56/77 |
| review-tier recall (partial) | 100% | 100% | 97.1% | 100% | 98.8% | 100% |
| review load | 17/95 | 17/95 | 19/73 | 21/72 | 36/168 | 38/167 |
| problem F1 | 0.821 | 0.839 | 0.780 | 0.795 | 0.804 | 0.821 |

Experimental tier on (`REFCHECK_V57_ENABLE=20,24,25,29,31,32,33`), NOT held out: dev
unchanged; test 86.6%, over-harsh 13/83 (#20), type 21/32 (#32 / #33); 19 pairs need live
adjudicator / verifier calls (15 from #29). Before the review fixes the same replay gave
88.5% all (dev 88.1 / test 89.1): of that gain, 6 pairs came from the unsafe parts now
removed or opt-in — 2 DEV pairs from #23 "three phases of <content>" and #27 cleared without
a wording note, 4 TEST pairs from #20 / #24 / #25 / #23 — so those numbers overstated V5.8.
Dev ablation (`ablate_v57.py --split dev --proposals 11,21,22,23,26,27,28,30 --opt-in
20,24,25,29,31,32,33`): switching off #21 costs +1 over-harsh, #22 +1 missed partial, #11
type 84.4% → 66.7%, #26 → 82.2%; #23, #27, #28 are now neutral on dev (they only hold
conservative cases); every opt-in rule is neutral on dev (#29 adds 8 pairs needing live
calls). The G2 colour-key pair is still fixed (decisive swap). Citation-Integrity was not
re-measured (OpenAI has no credits).

Live check (2026-10-23, `--live-roles adjudicator --live-keys ANTHROPIC_API_KEY_BACKUP`,
$0.0004): default V5.8 3-way 86.4%, missed partial 3/80, over-harsh 32/196, missed problem
0/3, type 56/77 (experimental tier on: 87.1%, over-harsh 30, type 59/77 — not held out, so
it stays opt-in).

**#34 unconfirmed negatives (V5.8, `dispute.unconfirmed_verdict`).** When the cross-check
cannot run (error, outage, degraded-mode budget cap), a verifier `not_supported` is shown one
step milder (`partially_supported`, reviewed; `not_relevant` → `not_supported`; contradicted,
fragments and the strict policy keep the verifier's verdict). Evidence: a verifier's first
`not_supported` matched gold in 2 of 33 gold pairs (25 were partial). Normal-mode gold numbers
are unchanged (free replay: 0 pairs differ).

**Degraded-mode app run (OpenAI without credits; screen skipped, BM25-only retrieval,
confirm on `claude-sonnet-5-5` capped at $0.375/run).** V4.9 manuscript, 322 pairs, scored on
the 281 gold pairs: before #34 72.7% 3-way (27 not_supported, 23 of them unconfirmed because
the cap stopped 40 Sonnet cross-checks), $0.90; after #34 79.2% (8 not_supported), $0.43 with
the LLM cache. Normal mode (OpenAI available): 86.4%.

## Data Flow

All inter-stage data flows as Pydantic models. The orchestrator maintains pipeline state:

```python
class PipelineState(BaseModel):
    session_id: str
    manuscript: ParsedManuscript | None = None
    references: list[Reference] = []
    claims: list[Claim] = []                       # V1+
    match_results: list[MatchResult] = []
    verification_results: list[VerificationResult] = []  # V1+
    user_interventions: list[UserIntervention] = []
    current_stage: int = 0
    status: Literal["created", "running", "paused", "complete", "error"] = "created"
```

State is serializable to JSON at every stage, enabling: resume after interruption, re-run individual stages, full audit trail.

## Real-Time Communication (SSE)

The frontend receives pipeline progress via Server-Sent Events:

```
Frontend                         Backend
   │                                │
   │ GET /api/sessions/{id}/events  │
   │ ─────────────────────────────► │
   │                                │
   │ ◄── data: {stage:1, status:"running"} ──
   │ ◄── data: {stage:1, status:"complete", refs:142} ──
   │ ◄── data: {stage:3, status:"running", progress:{10/47}} ──
   │ ◄── data: {stage:3, status:"needs_input", type:"confirm_match"} ──
   │                                │
   │ POST /api/sessions/{id}/matches/{ref}/confirm
   │ ─────────────────────────────► │
   │                                │
   │ ◄── data: {stage:3, status:"running"} ──  (pipeline resumes)
```

When pipeline hits a user intervention point, it emits a `needs_input` event and pauses. Frontend shows the intervention UI. User responds via REST API. Pipeline resumes.

## LLM Integration

All LLM calls go through `src/refcheck/llm/` (litellm is never imported elsewhere). Callers ask
for a **role**, not a model; the registry (`llm/model_registry.py`) maps each role to an ordered
fallback list and `llm/roles.py` picks the first available model (key present and not disabled
by a hard auth/billing/404 failure).

| Role | Default model (effort) | Fallbacks | Used by |
|------|------------------------|-----------|---------|
| screen | Decisions API `gpt-6-luna` | none → screen disabled | L1 screen |
| verifier | `claude-haiku-5-5` (low) | `gpt-6-luna` | L2 (decides most pairs) |
| judge | `claude-sonnet-5-5` (low) | `gpt-6.1-sol` | L3 (unusual positives only) |
| confirm | `gpt-6-luna` (low) | `gpt-6.1-sol`; degraded (V5.8): `claude-sonnet-5-5` (low), never the verifier's model | cross-family check of negative verdicts |
| utility | `gpt-6-luna` (none) | `claude-haiku-5-5` | title repair etc. |
| embedding | `text-embedding-3-small` | `text-embedding-3-large` (1024-d) | retrieval |

Overrides: `REFCHECK_<ROLE>_MODEL` (comma list), `REFCHECK_<ROLE>_EFFORT`,
`REFCHECK_SCREEN_ENABLED`, `REFCHECK_PRIVACY_PROFILE` (see `.env.example`).

```
Python code → call_llm(template, vars, OutputModel, role=...) → Jinja2 template → litellm
                  │
                  ├── Loads prompt from src/refcheck/prompts/{name}.md (stable prefix cached)
                  ├── Strict JSON schema from the Pydantic model (never sends temperature)
                  ├── Runs litellm in a worker thread; per-provider semaphores; 429/5xx backoff
                  ├── Rotates to the backup key on billing/auth errors; falls back to the
                  │   next model of the role on hard failures; a refusal skips the
                  │   whole model family
                  ├── Validates against the Pydantic output model (one repair retry)
                  └── Records cost per model / task / role (CostTracker, budget checked first)
```

Other entry points: `decide()` (Decisions API predicates), `embed()` (cached embeddings) and
`preflight()` / `role_status()` (`llm/health.py`, `llm/roles.py`). `GET /api/health` returns
the per-role status (resolved model, availability, last error, Decisions API status);
`?deep=true` probes every role with one tiny real call (cached 10 minutes; V5.8: a role down
for a persistent cause re-tests exhausted keys and benched models, so added credits take
effect without a restart). V5.8 fields: per role `degraded`, `degraded_mode`, `cause`,
`persistent`, `effect`, `action`; top level `degraded_notices`, `actions`; `llm` is
"unavailable" only when the verifier is dead, else "degraded" (`llm/degradation.py`,
`api/routes/health_llm.py`).

**Why litellm:** Swap between Anthropic direct API, AWS Bedrock, Google Vertex AI, or OpenAI with a config change. No code changes needed.

See `docs/prompts/PROMPT_ENGINEERING.md` for prompt design guidelines.

## Caching Strategy

- **API responses:** diskcache (file-based, keyed by query hash)
- **PDF text extractions:** cached alongside original PDF
- **LLM responses:** cached by prompt hash (for identical re-verification)
- **Embeddings:** cached by sha256(model + text); source documents cached per PDF path + mtime
- **Cache location:** `~/.refcheck/cache/`
- **Invalidation:** manual only (future: TTL-based)

## Error Handling Philosophy

- **API errors** → retry with backoff via tenacity, then mark as `api_error`
- **Parse errors** → surface to user with context, never silently skip
- **LLM errors** → backoff/retry and model fallback, then `cannot_verify` with reason `llm_error`;
  a dead verifier at preflight fails stage 5 instead of producing silent `cannot_verify`s;
  V5.8: other roles degrade visibly (confirm → same-family fallback + review, screen skipped,
  BM25-only retrieval), recorded with cause and fix in `/api/health`, the stage-5 event, the
  model-status card and the report's "Degraded mode" note
- **Provider outages** are never silent: billing / quota / auth / missing key are persistent
  causes with an action ("Add credits to the OpenAI account…"); network / rate-limit errors
  are temporary and retried
- **File errors** → fail fast with clear message
- **Cardinal rule:** Never conflate "we couldn't check" with "we checked and it failed"

## Folder Structure

```
refcheck/
├── pyproject.toml                    # Single config (deps, ruff, mypy)
├── docker-compose.yml                # GROBID + backend services
├── .env.example                      # Required environment variables
├── AGENTS.md / CLAUDE.md / README.md
│
├── docs/
│   ├── PRD.md                        # Product requirements
│   ├── ARCHITECTURE.md               # This file
│   ├── ROADMAP.md                    # Version plan with feature matrix
│   ├── TECH_STACK.md                 # Technology decisions
│   ├── CODE_STANDARDS.md             # Coding rules and patterns
│   ├── FRONTEND.md                   # UI specification
│   ├── API_CONTRACT.md               # All API endpoints
│   ├── DOCUMENTATION_GUIDE.md        # How the doc system works
│   ├── features/                     # One spec per pipeline stage
│   ├── prompts/                      # LLM prompt guidelines
│   └── tests/                        # Test strategy
│
├── src/refcheck/                     # Backend Python package
│   ├── __init__.py
│   ├── models/                       # Pydantic models (the contract)
│   ├── stages/                       # Pipeline stages (one folder each)
│   ├── llm/                          # litellm wrapper
│   ├── prompts/                      # Jinja2 .md templates
│   ├── api/                          # FastAPI routes
│   ├── services/                     # Orchestration logic
│   └── utils/                        # Small shared utilities
│
├── frontend/                         # Next.js 15 app
│   ├── src/app/                      # App Router pages
│   ├── src/components/               # UI components
│   ├── src/lib/                      # API client, types, utils
│   └── src/hooks/                    # React hooks
│
└── tests/                            # All tests
    ├── unit/                         # Per-module tests
    ├── integration/                  # Per-stage tests
    ├── e2e/                          # Full pipeline tests
    ├── canary/                       # LLM grounding tests
    └── fixtures/                     # Sample data
```
