# RefCheck AI — Version Roadmap

**Principle:** Each version is a usable product. No version ships broken features — every feature included must work end-to-end. V3 is feature-complete running locally; cloud deployment is a separate effort after V3.

---

## Version Overview

| Version | Codename | Goal | Timeline |
|---------|----------|------|----------|
| **MVP (v0.1)** | Foundation | Parse manuscripts, match PDFs, verify references exist, basic web UI | First |
| **V1 (v1.0)** | Verification | Add LLM-powered claim verification — the core value proposition | Second |
| **V2 (v2.0)** | Intelligence | Multi-model voting, retraction checking, interactive review | Third |
| **V3 (v3.0)** | Complete | All features polished, performance optimized, ready for public use locally | Fourth |

---

## Feature × Version Matrix

Each feature has an overall goal and sub-features. Sub-features are assigned to the version where they ship.

### Feature 1: DOCX Parsing & Reference Extraction

**Goal:** Extract every reference and citation from a biomedical manuscript with ≥95% accuracy, handling Vancouver (numbered) style as priority and all major reference managers.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| Basic numbered reference extraction | ✅ | | | |
| DOI detection and normalization | ✅ | | | |
| Section-by-section text extraction | ✅ | | | |
| In-text citation detection (numbered: [1], [1-5]) | ✅ | | | |
| Zotero field code extraction | ✅ | | | |
| Mendeley/EndNote field code extraction | | ✅ | | |
| Author-year citation style support | | ✅ | | |
| Citation range expansion ([1-5] → [1,2,3,4,5]) | ✅ | | | |
| Supplementary reference list handling | | | ✅ | |
| Unicode author name normalization | | ✅ | | |
| Duplicate reference detection | | | ✅ | |
| BibTeX/RIS import as alternative to parsing | | | | ✅ |
| Confidence scoring per parsed reference | | ✅ | | |

**MVP acceptance:** Correctly parses ≥95% of references from a Vancouver-style biomedical manuscript with 100+ references.

---

### Feature 2: Claim-Citation Pair Extraction (DEPRECATED — Replaced by Feature 8: Citation-First Verification)

**Goal:** For every citation in the manuscript, identify what specific claim it supports and classify the citation's role, with ≥85% accuracy.

**Note:** This feature is superseded by Feature 8 (Citation-First Verification) in V4. LLM-based claim extraction is replaced by deterministic citation detection. The atomic decomposition concept may still be applied to VerificationUnits in future versions.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| Basic claim-citation pair extraction via LLM | | ✅ | | |
| Claim type classification (factual/methodological/background/attribution/contrast/interpretive) | | ✅ | | |
| Priority assignment based on claim type | | ✅ | | |
| Compound citation separation (multiple refs, different sub-claims) | | ✅ | | |
| Group citation handling (multiple refs, one claim) | | ✅ | | |
| Atomic claim decomposition for factual claims | | | ✅ | |
| User review UI for claim-citation pairs | | ✅ | | |
| Claim editing, splitting, merging in UI | | | ✅ | |
| User priority override (mark claims as high/low priority) | | | ✅ | |
| LLM prompt optimization based on biomedical terminology | | | | ✅ |

**V1 acceptance:** ≥85% of claim-citation mappings correct on biomedical manuscripts. Claim type classification ≥80% accurate.

---

### Feature 3: PDF Upload & Smart Matching

**Goal:** Match uploaded PDFs to manuscript references with ≥98% precision at auto-accept threshold and ≤2% false match rate.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| DOI-based exact matching | ✅ | | | |
| PDF metadata extraction (PyMuPDF) | ✅ | | | |
| Title fuzzy matching (rapidfuzz) | ✅ | | | |
| Three-tier confidence scoring (auto/confirm/reject) | ✅ | | | |
| Drag-and-drop PDF upload UI | ✅ | | | |
| Bulk upload (50+ PDFs at once) | ✅ | | | |
| GROBID first-page structured extraction | | ✅ | | |
| LLM-assisted matching (fallback for ambiguous cases) | | ✅ | | |
| Version mismatch detection (preprint vs published) | | ✅ | | |
| Visual confirmation UI (PDF first page preview) | | | ✅ | |
| OCR fallback for scanned PDFs | | | ✅ | |
| Extra PDF detection (uploaded but not in reference list) | ✅ | | | |
| Re-matching after metadata correction | | | | ✅ |

**MVP acceptance:** ≥90% of PDFs correctly matched for a 100-reference biomedical manuscript. DOI matching works perfectly.

---

### Feature 4: Gap Analysis & Paper Retrieval

**Goal:** For every unmatched reference, determine if it exists, retrieve open-access versions, and provide direct links for paywalled papers.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| CrossRef lookup by DOI | ✅ | | | |
| CrossRef lookup by title+author | ✅ | | | |
| PubMed/NCBI lookup (priority for biomedical) | ✅ | | | |
| Semantic Scholar lookup | ✅ | | | |
| Unpaywall open-access PDF retrieval | ✅ | | | |
| PubMed Central full-text retrieval | ✅ | | | |
| API response caching (diskcache) | ✅ | | | |
| Gap dashboard UI (have/downloading/paywalled/not found) | ✅ | | | |
| Direct journal links for paywalled papers | ✅ | | | |
| Rate limiting with exponential backoff | ✅ | | | |
| "I know this exists" user confirmation | | ✅ | | |
| Metadata correction and re-search | | ✅ | | |
| OpenAlex as additional fallback API | | | ✅ | |
| Retraction Watch integration | | | ✅ | |
| Correction/erratum detection | | | ✅ | |
| Persistent reference library across sessions | | | | ✅ |
| Batch resolution progress with SSE | ✅ | | | |

**MVP acceptance:** ≥95% of real biomedical papers with DOIs found. ≥80% of Unpaywall-listed OA papers successfully downloaded. Clear distinction between "not found" and "API error".

---

### Feature 5: LLM Claim Verification

**Goal:** For each claim-citation pair, verify whether the cited source supports the claim, with ≥80% agreement with expert human reviewers.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| Relevant section extraction from PDF (RAG) | | ✅ | | |
| Single-LLM forced-grounding verification (Tier 1) | | ✅ | | |
| Evidence quote extraction and validation | | ✅ | | |
| Confidence scoring with calibration prompt | | ✅ | | |
| Verdict assignment (supported/partial/not/contradicted/cannot) | | ✅ | | |
| Claim-type-specific verification behavior | | ✅ | | |
| Anti-hallucination: knowledge boundary instruction | | ✅ | | |
| Post-hoc quote validation against source text | | ✅ | | |
| Canary testing infrastructure | | ✅ | | |
| Abstract-only verification fallback | | ✅ | | |
| Dual-strategy verification (Tier 2) | | | ✅ | |
| Multi-model voting (Claude + GPT) | | | ✅ | |
| Human review escalation UI (Tier 3) | | | ✅ | |
| Real-time ambiguity resolution via SSE | | | ✅ | |
| Atomic claim verification for factual claims | | | ✅ | |
| Confidence calibration tuning | | | | ✅ |
| Verification caching (skip re-verified claims) | | | | ✅ |
| Parallel verification (concurrent LLM calls) | | | | ✅ |

**V1 acceptance:** Single-model verification with ≥80% expert agreement, ≤15% false positive rate, 100% canary pass rate.

---

### Feature 6: Report Generation

**Goal:** Generate a professional, layered DOCX report that researchers can submit alongside their manuscript, with clear action items identifiable within 2 minutes.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| Basic existence report (reference found/not found) | ✅ | | | |
| Metadata accuracy report (DOI, year, author mismatches) | ✅ | | | |
| DOCX generation with python-docx | ✅ | | | |
| Download from web UI | ✅ | | | |
| Executive summary with color-coded counts | | ✅ | | |
| Full verification report with verdicts and evidence | | ✅ | | |
| Critical findings section (red flags) | | ✅ | | |
| Methodology note (models used, tiers, coverage) | | ✅ | | |
| User override logging in report | | | ✅ | |
| Interactive report preview in web UI | | | ✅ | |
| Accept/override/re-verify per finding | | | ✅ | |
| Report regeneration after corrections | | | | ✅ |
| Report diff (changes between versions) | | | | ✅ |
| Export to PDF | | | | ✅ |

**MVP acceptance:** Generates valid DOCX with reference existence status for 100+ references in <60 seconds.

---

### Feature 7: Web UI

**Goal:** A clean, scientific-aesthetic web interface that guides researchers through the entire verification workflow with real-time progress and clear status at every step.

| Sub-feature | MVP | V1 | V2 | V3 |
|------------|-----|----|----|-----|
| Upload page (drag-drop DOCX + PDFs) | ✅ | | | |
| Reference list review page | ✅ | | | |
| PDF matching confirmation page | ✅ | | | |
| Gap dashboard (have/need/missing) | ✅ | | | |
| Pipeline progress tracker with SSE | ✅ | | | |
| Basic results table (existence check results) | ✅ | | | |
| Report download button | ✅ | | | |
| Light/dark mode toggle | ✅ | | | |
| Claim-citation review page | | ✅ | | |
| Full verification results dashboard | | ✅ | | |
| Expandable reference rows with evidence | | ✅ | | |
| Recharts summary visualizations | | ✅ | | |
| Confidence badge color coding | | ✅ | | |
| Real-time verification progress (per-claim) | | ✅ | | |
| Tier 3 human review modal | | | ✅ | |
| Interactive report preview | | | ✅ | |
| Accept/override/re-verify controls | | | ✅ | |
| User settings page | | | | ✅ |
| Session history (past verifications) | | | | ✅ |
| Keyboard shortcuts | | | | ✅ |
| Mobile-responsive layout | | | | ✅ |

**MVP acceptance:** Full upload → resolve → download workflow functional for a single manuscript. SSE progress works. Dark/light mode works.

---

## Version Summaries

### MVP (v0.1) — "Does It Exist?"

**What it does:** Upload a manuscript and PDFs → system extracts references, matches PDFs, resolves gaps via academic APIs, tells you which references exist and which don't, generates a basic existence report.

**What it doesn't do yet:** No claim extraction. No LLM verification. No "does this paper support the claim?" — just "does this paper exist?"

**Why this is valuable on its own:** Even without LLM verification, a tool that automatically finds and matches 100+ references, downloads open-access versions, and identifies missing/unfindable papers saves hours of manual work.

**Key sub-features (24 total):**
- DOCX parsing with numbered refs, DOI detection, field codes
- PDF upload, matching (DOI + fuzzy title), bulk upload
- Full API resolution cascade (CrossRef → PubMed → S2 → Unpaywall)
- Gap dashboard, caching, rate limiting
- Basic existence report (DOCX download)
- Web UI: upload, review, match, resolve, download
- SSE pipeline progress, light/dark mode

---

### V1 (v1.0) — "Does It Support the Claim?"

**What's new:** LLM-powered claim extraction and single-model verification. The system now reads the papers and tells you whether they actually support what you're claiming.

**Key additions (23 total):**
- Claim-citation extraction with classification
- Single-LLM forced-grounding verification (Tier 1)
- Evidence quote extraction and validation
- Canary testing
- Full verification report with verdicts
- Results dashboard with charts and expandable rows

---

### V2 (v2.0) — "Are You Sure?"

**What's new:** Multi-model voting for uncertain cases, retraction checking, human review escalation, and interactive report editing.

**Key additions (19 total):**
- Dual-strategy and multi-model verification (Tiers 2+3)
- Retraction Watch integration
- Atomic claim verification
- Human review modal
- Interactive report with accept/override
- Advanced UI: visual PDF confirmation, claim editing

---

### V3 (v3.0) — "Production Ready"

**What's new:** Performance optimization, persistent data, polish, and everything needed to share with the world. Still runs locally.

**Key additions (13 total):**
- Parallel LLM verification
- Persistent reference library
- Report diffing and PDF export
- BibTeX/RIS import
- Session history
- Mobile responsive
- Performance optimization for 200+ references

---

## Definition of Done (per version)

A version is complete when:
1. All sub-features for that version pass their unit tests
2. Integration tests for all active stages pass
3. E2E test with a real biomedical manuscript (100+ refs) passes
4. `ruff check` and `mypy` report zero errors
5. Web UI is functional for all included workflows
6. Documentation is updated (feature specs, API contract, ARCHITECTURE)
7. A researcher can complete the full workflow without reading code
