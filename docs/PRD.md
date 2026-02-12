# RefCheck AI — Product Requirements Document (PRD)

**Version:** 0.2.0
**Last Updated:** 2026-02-11
**Status:** Design Phase — documentation complete, implementation pending

---

## 1. Problem Statement

Biomedical publications rely on references to establish credibility, provide evidence for claims, and situate work within existing literature. However, reference integrity is rarely verified systematically:

- **Fabricated references** — Papers cite sources that don't exist
- **Misrepresented findings** — The cited paper says something different from what the manuscript claims
- **Incorrect metadata** — Wrong authors, year, title, or DOI
- **Retracted sources** — Cited papers have been retracted or corrected post-publication
- **Weak citations** — Vague claims supported by only tangentially related papers

A typical biomedical manuscript has 100-200 references. Manual verification is impractical. Reviewers typically spot-check a few references at best. There is no widely available tool that automates comprehensive reference verification.

## 2. Solution Overview

A web-based AI-powered pipeline that accepts a DOCX manuscript, extracts all references and the claims they support, collects the source papers (via user upload + automated retrieval), and verifies each claim against its cited source using LLMs.

### Core Workflow (User Perspective)
1. User uploads DOCX manuscript and bulk-uploads PDFs via web UI
2. System extracts and displays reference list → user confirms/corrects
3. System matches PDFs to references → user confirms uncertain matches
4. System identifies gaps, retrieves open-access papers automatically (PubMed Central, Unpaywall)
5. System provides links for paywalled papers → user uploads remaining
6. System extracts claim-citation pairs → user reviews (V1)
7. System runs tiered LLM verification on all claim-citation pairs (V1+)
8. User resolves ambiguous cases flagged during verification (V2)
9. System generates DOCX verification report
10. User can accept, override, or re-verify findings (V2)

### Key Design Principles
- **Quality first** — Optimize for accuracy, not speed or cost
- **Smart user intervention** — AI does 90% of the work; user confirms, corrects, or resolves the remaining 10%
- **Every intervention is optional** — User can accept all AI suggestions to go fast, or review everything for maximum accuracy
- **Progressive confidence** — Every judgment comes with a confidence score and evidence trail
- **Fail transparently** — When the system can't verify something, it says so clearly with the reason

## 3. Target Users & Deployment

### Users
- **Initially:** The developer and lab mates (trusted small group, biomedical research)
- **Later:** Public release for broader research community

### Deployment
- **Local-first:** Runs on localhost via Docker Compose (backend + GROBID + frontend)
- **Cloud later:** AWS Bedrock + Lambda + S3 (architecture is portable via litellm)
- **Auth deferred:** No authentication for local use; pluggable via middleware when moving to cloud

### Field Focus
- **Primary:** Biomedical / life sciences
- **Citation style priority:** Vancouver (numbered) — the dominant biomedical style
- **Database priority:** PubMed/NCBI is primary, CrossRef and Semantic Scholar are complementary
- **Test fixtures:** All based on real biomedical papers

## 4. Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------| 
| Reference extraction accuracy | ≥95% of references correctly parsed | Test against 20+ biomedical manuscripts |
| Claim-citation pair accuracy | ≥85% correct before user review | Human evaluation on 10+ manuscripts |
| PDF-to-reference matching | ≥90% correct at high confidence | Test with bulk PDF uploads |
| Reference existence verification | ≥98% correct (exists/doesn't exist) | Cross-validate against manual checks |
| Claim verification accuracy | ≥80% agreement with expert reviewers | Blind comparison study |
| False positive rate | ≤15% of flagged references are fine | Track user overrides |
| Processing time (100 refs) | < 15 minutes end-to-end | Wall clock measurement |
| Cost per manuscript (100 refs) | ~$3-5 per run | API cost tracking |

## 5. Version Plan

Implementation follows four versions, each a usable product. See `docs/ROADMAP.md` for the full feature × version matrix.

### MVP (v0.1) — "Does It Exist?"
Upload manuscript + PDFs → extract references → match PDFs → resolve via APIs → existence report → web UI with real-time progress.

**Value even without LLM verification:** Automatically finding and matching 100+ references, downloading OA versions, and identifying missing papers saves hours.

### V1 (v1.0) — "Does It Support the Claim?"
Add LLM-powered claim extraction and single-model forced-grounding verification. Full verification report with verdicts, evidence quotes, and confidence scores.

### V2 (v2.0) — "Are You Sure?"
Multi-model voting, retraction checking, human review escalation, interactive report editing, atomic claim verification.

### V3 (v3.0) — "Production Ready"
Performance optimization, persistent reference library, report diffing, BibTeX/RIS import, session history, mobile responsive. Everything works locally, ready for public use.

**Cloud deployment** is a separate effort after V3.

## 6. User Intervention Points

Each intervention follows the principle: **AI presents its best guess, user confirms or corrects.**

| ID | Stage | Trigger | User Action | Version |
|----|-------|---------|-------------|---------|
| IP-1 | Reference extraction | After parsing | Confirm/edit reference list | MVP |
| IP-2 | Claim extraction | After LLM extraction | Review claim-citation pairs | V1 |
| IP-3 | PDF matching | After smart matching | Confirm uncertain matches | MVP |
| IP-4 | Missing papers | After gap analysis | Upload paywalled PDFs, correct metadata | MVP |
| IP-5 | Version mismatch | When detected | Proceed with available version or upload correct one | V1 |
| IP-6 | Verification ambiguity | When LLM uncertain | Answer focused multiple-choice question | V2 |
| IP-7 | Report review | After report generated | Accept, override, or request re-verification | V2 |
| IP-8 | Metadata correction | User-initiated | Correct reference metadata, trigger re-search | V1 |

## 7. Data Models (High Level)

```
Reference:
  id: int
  raw_text: str
  authors: list[str]
  title: str
  year: int | None
  journal: str | None
  doi: str | None
  pmid: str | None                    # PubMed ID — biomedical priority
  source_status: "pending" | "found" | "not_found" | "api_error"
  pdf_path: Path | None
  pdf_source: "user_upload" | "open_access" | "not_available" | None
  retraction_status: "ok" | "retracted" | "corrected" | "expression_of_concern" | None

Claim:
  id: int
  manuscript_text: str
  extracted_claim: str
  claim_type: "factual" | "methodological" | "background" | "attribution" | "contrast" | "interpretive"
  reference_ids: list[int]
  priority: "high" | "medium" | "low"
  atomic_claims: list[str]            # V2: independently verifiable atoms

VerificationResult:
  claim_id: int
  reference_id: int
  verdict: "supported" | "partially_supported" | "not_supported" | "contradicted" | "cannot_verify"
  confidence: float (0.0 - 1.0)
  evidence_quotes: list[str]
  reasoning: str
  tier: 1 | 2 | 3
  source_coverage: "full_text" | "abstract_only" | "relevant_sections"
  user_override: str | None
```

## 8. External API Dependencies

| API | Purpose | Rate Limit | Auth | Priority |
|-----|---------|-----------|------|----------|
| PubMed/NCBI | Biomedical paper search, PMID lookup | 10/sec with key | API key (free) | Primary |
| CrossRef | DOI resolution, metadata lookup | 50/sec polite | None (polite header) | Primary |
| Semantic Scholar | Paper search, abstracts, OA URLs | 100/5min | API key (free) | Secondary |
| Unpaywall | Open-access PDF URLs | 100k/day | Email as key | Primary |
| PubMed Central | Full-text retrieval for OA papers | Per NCBI limits | Same key as PubMed | Primary |
| Retraction Watch | Retraction status | TBD | TBD | V2 |
| Anthropic (via Bedrock/litellm) | LLM verification (Claude) | Per plan | API key | V1+ |
| OpenAI (via litellm) | Multi-model voting (GPT) | Per plan | API key | V2+ |

## 9. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| LLM relies on memory instead of provided text | High | Medium | Forced-grounding prompts, canary tests, post-hoc quote validation |
| PDF matching assigns wrong paper | High | Medium | Conservative thresholds, visual confirmation UI, GROBID structured extraction |
| False positive rate erodes trust | High | Medium | Tiered verification, confidence calibration, user override tracking |
| 100-200 refs overwhelm processing | Medium | High | Parallel API calls, chunked LLM processing, SSE progress tracking |
| PubMed rate limits slow resolution | Medium | Medium | API key, caching, parallel with backoff |
| Paywalled papers unavailable | Medium | High | User upload flow, abstract-only verification fallback |
| Context window overflow with long papers | Medium | Medium | RAG-based section retrieval, never full paper feeding |

## 10. Out of Scope (all versions, pre-cloud)

- LaTeX manuscript support (DOCX only)
- Real-time multi-user collaboration
- Automated manuscript correction
- Citation recommendation ("you should cite X instead")
- Non-English manuscripts
- User authentication (deferred to cloud deployment)
