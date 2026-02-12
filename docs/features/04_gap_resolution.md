# Feature: Gap Analysis & Paper Retrieval

**Module:** `src/refcheck/stages/resolve_gaps/`
**Version:** MVP
**Dependencies:** Stage 1 + Stage 3
**User Intervention:** IP-4 (upload paywalled papers, correct metadata)

---

## Purpose

For references not matched by user-uploaded PDFs: verify they exist in academic databases, retrieve open-access versions where available, and provide direct links for paywalled papers the user needs to obtain.

**Biomedical focus:** PubMed/NCBI is the primary lookup API (not a fallback). Most biomedical papers have PMIDs and many are in PubMed Central (full OA text).

## Input

- `list[Reference]` with match status from Stage 3 (some have PDFs, some don't)

## Output

- Updated `list[Reference]` with:
  - `source_status`: "found" | "not_found" | "api_error"
  - `pdf_path`: filled if open-access version downloaded
  - `pdf_source`: "open_access" if auto-retrieved
  - `pmid`: PubMed ID if found
  - `journal_url`: direct link for paywalled papers
  - `retraction_status`: from Retraction Watch (V2)

## Implementation Requirements

### Reference Resolution (`resolve_gaps/resolver.py`)
For each unmatched reference, query APIs in order:
1. **PubMed/NCBI** (priority for biomedical) — by PMID if available, else by title+author → returns PMID, abstract, PMC ID if available
2. **CrossRef** (by DOI if available, else by title+author) → confirms existence, returns metadata
3. **Semantic Scholar** (by title) → returns abstract, citation count, open-access URL

Compare returned metadata against reference to verify it's the same paper. Distinguish clearly between: "found and verified", "found but metadata doesn't match well", "not found in any database", "API error prevented lookup".

### Open-Access Retrieval (`resolve_gaps/retriever.py`)
- For resolved references without PDFs, check **PubMed Central first** (biomedical priority) for full-text
- Then check **Unpaywall** for OA versions
- Download PDF to local cache directory
- Verify downloaded file is a valid PDF (not an error page)

### Gap Dashboard Output
Categorize all references into: "have PDF" | "downloading OA" | "paywalled (link provided)" | "not found" | "API error"

For paywalled papers: provide DOI link (`https://doi.org/{doi}`) so user can download via institutional access. For not-found papers: show what was searched and what failed.

### Caching (diskcache)
- Cache all API responses by query hash
- Cache downloaded PDFs by DOI/title hash
- Never re-download a paper already in cache

### Rate Limiting
- All API calls use `tenacity` for exponential backoff
- Respect per-API rate limits (PubMed: 10/sec with key, CrossRef: 50/sec polite, S2: 100/5min)
- Parallel calls within rate limits using `httpx` async

## Tests & Acceptance Criteria

| Test ID | Test | Pass Criteria |
|---------|------|---------------|
| GR-01 | Resolve by DOI | Known DOI returns correct metadata from CrossRef |
| GR-02 | Resolve by PMID | Known PMID returns correct paper from PubMed |
| GR-03 | Resolve by title | Known title returns correct paper from Semantic Scholar |
| GR-04 | Non-existent paper | Fabricated reference returns "not_found" |
| GR-05 | API error handling | Simulated timeout returns "api_error", not "not_found" |
| GR-06 | OA download (PMC) | Known PMC paper successfully downloaded as valid PDF |
| GR-07 | OA download (Unpaywall) | Known OA paper successfully downloaded |
| GR-08 | Paywalled paper | Paywalled paper returns journal URL, no download attempted |
| GR-09 | Caching | Second run for same reference uses cache, no API calls |
| GR-10 | Rate limiting | 50 references processed without hitting rate limits |

### Quality Metrics

| Metric | Target |
|--------|--------|
| Resolution accuracy (real paper found) | ≥95% for papers with DOIs |
| PubMed resolution for biomedical papers | ≥90% found |
| False "not found" rate | ≤5% |
| OA retrieval success | ≥80% of PMC/Unpaywall-listed papers downloaded |
| API error rate | ≤2% under normal conditions |
