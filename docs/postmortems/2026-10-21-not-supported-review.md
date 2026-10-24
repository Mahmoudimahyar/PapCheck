# Postmortem: 35 of 40 "not supported" verdicts were wrong (2026-10-21)

A manual review of every "not supported" verdict on a real 122-reference manuscript (V5.1
pipeline, 318 claim–reference pairs) found only 5 correct. 4 checked the wrong paper and 31 were
too harsh: the source supported the claim fully (4) or partially (27). Each mistake was traced
to a root cause and fixed with regression tests. Manuscript text is deliberately not quoted here.

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Most false flags (36/40 were "disputed") | `escalation.cross_check_negative` kept the verifier's harsher verdict even when the blind cross-family check found support. The cross-check was right in ~28/36 | `verify_claims/dispute.py`: a disputed `not_supported` is shown as `partially_supported` (never "supported"), `not_relevant` becomes `not_supported`, `contradicted` is kept, and the pair is always queued for review with both views. `REFCHECK_DISPUTE_POLICY=strict` restores the old rule |
| 2 | References judged on parts of a sentence that other references cover (26/40 multi-citation) | `scope_resolver._resolve_multi` gave every citation in a sentence the same scope, and prompts and retrieval used the whole sentence | `detect_citations/cited_for.py` computes the clause each marker is attached to (only when a verb follows, so subject markers don't narrow). Prompts render "CITED FOR", and retrieval and the screen use it |
| 3 | "Not supported" where some content was supported | The `verify_claim.md` rubric treated a compound claim as partial only for single-citation sentences | Two explicit boundaries: `not_supported` only when no cited element is stated; `supported` only when every element is stated without broader, more certain or more specific wording. Synthetic boundary examples added. (The first rewrite blurred the second boundary and lost 4 recall points; fixed in V5.3) |
| 4 | Citations to "2018b" / "2024c" checked against the "a" paper | `reference_extractor.py` year regex could not match "2018a" (year=None), and `reference_mapper.py` stripped the letter and took the first match | `Reference.year_suffix`; the mapper matches author + year + letter exactly; ambiguity is flagged, never silently resolved |
| 5 | Duplicate bibliography entries undetected | `detect_duplicates` existed but was never called | Called in `parse_manuscript`, by DOI and normalised title + first author + year; duplicates inherit the original's PDF and abstract |
| 6 | PDF of a different paper (2020 report for a 2017 reference) accepted | `identity_check.py` used title-word coverage only and needed two negative signals; it never compared the DOI printed in the PDF, the PDF metadata title, or numbers inside titles | DOI-in-PDF, metadata-title and title-number checks → `identity_status="mismatch"` → `cannot_verify(reference_mismatch)` or a correctly labelled abstract fallback |
| 7 | Supporting-Information PDF used as the article | The supplement check only scanned the first 8 lines, and the matcher took the first PDF in folder order | `match_pdfs/supplement_detector.py` (file name, title-area heading, "Figure S1" caption dominance); supplements never win a match |
| 8 | Scanned PDF verified on its repository cover sheet | Image blocks were skipped and image-only pages not counted; any non-empty text counted as full text | `source_scan.py` removes cover sheets and detects image-only PDFs; `source_ocr.py` OCRs them when Tesseract is installed (`REFCHECK_OCR=0` to disable), else `pdf_scanned` and abstract fallback |
| 9 | Some PDF characters unnormalised | The suspected ligature cause was wrong (ligatures were already mapped); text used NFC, leaving µ, full-width characters and ™ | NFKC normalisation (keeping "…") |
| 10 | "Journal Vol, pages" stored as the title | The APA-style title segment was mis-split, the repairer's checks missed DOI- or volume-bearing titles, and enrichment never replaced titles from the Crossref/PubMed record | `apa_parser`, stricter `is_likely_bad_title`, `resolve_gaps/title_repair.py` (title from the DOI/PMID record) |
| 11 | Sentence fragments verified as claims | No claim-quality check | `Claim.claim_quality="fragment"`, shown as "Claim text appears incomplete" |
| 12 | Secondary citations not surfaced | Validated quotes kept only the model's text, losing trailing "[10, 11]" markers | `ValidatedQuote.source_span/source_after`; `post_checks.py` adds a "Secondary citation" note |
| 13 | Unsourced numbers not surfaced | `gates.numeric_mismatch` compared claim numbers only with the quotes | `source_numbers.py` checks claim numbers against the whole source; adds "Numbers not found in the source" and flags for review |
| 14 | Wrong or unusable sources reported as "not supported" | Fallback reasons were lost; any abstract was accepted | `source_fallback.py` keeps the reason (`reference_mismatch`, `pdf_supplement`, `pdf_scanned`); abstract-only checks can never yield `not_supported` |

## Results (live runs, `scripts/eval`)

| Check | Before | After |
|---|---|---|
| Manuscript: agreement with the manual review (40 pairs) | 5/40 | 35/40 |
| Citation-Integrity test (305): problem recall / precision / F1 | 0.928 / 0.883 / 0.905 | 0.911 / 0.866 / 0.888 |
| Citation-Integrity: negative verdicts on supported or partial gold | 30 | 12 |
| SciFact test (210): problem recall / precision / F1 | 0.971 / 0.829 / 0.895 | 0.979 / 0.825 / 0.895 |

Trade-off: a disputed verdict is now shown one severity step milder. On Citation-Integrity
this costs ~1.7 points of problem recall (and 6-way accuracy, since some gold "not supported"
items now read "partially supported") in exchange for 60% fewer false "not supported" flags.
Every disputed or softened item is still flagged and listed under "Check First" in the report.

## Lessons

- Validate verdict policies against human-reviewed real manuscripts, not only public benchmarks.
  Benchmark recall looked fine while 87% of the "not supported" flags on a real review paper were wrong.
- Any rubric change must be re-measured on both boundaries (not_supported/partial *and*
  partial/supported). Fixing one silently loosened the other.
- Treat source identity as a first-class check (DOI in PDF, report year, supplement, scanned).
  A confident verdict on the wrong document is worse than "can't verify".
