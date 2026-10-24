# RefCheck AI — API Contract

**Base URL:** `http://localhost:8001` (development)
**Format:** JSON (except file uploads which use multipart/form-data)
**Auth:** None (MVP). Pluggable via middleware when moving to cloud.
**Errors:** All errors return `{ "error": string, "detail": string | null }`

---

## Sessions

A session represents one manuscript verification run. All pipeline data lives under a session.

### `POST /api/sessions`

Create a new verification session by uploading a manuscript and optional PDFs.

**Request:** `multipart/form-data`
```
manuscript: File (.docx, required)
pdfs: File[] (optional, multiple)
```

**Response:** `201 Created`
```json
{
  "id": "sess_abc123",
  "status": "created",
  "created_at": "2026-02-11T14:30:00Z",
  "manuscript_filename": "my_paper.docx",
  "pdf_count": 47
}
```

**Errors:**
- `400` — No manuscript provided or wrong file type
- `413` — File too large (limit: 50MB manuscript, 500MB total PDFs)

---

### `GET /api/sessions/{session_id}`

Get session status and summary.

**Response:** `200 OK`
```json
{
  "id": "sess_abc123",
  "status": "running" | "paused" | "complete" | "error",
  "created_at": "2026-02-11T14:30:00Z",
  "manuscript_filename": "my_paper.docx",
  "stages": {
    "parse": { "status": "complete", "elapsed_seconds": 12 },
    "detect_citations": { "status": "complete", "elapsed_seconds": 5 },
    "match_pdfs": { "status": "complete", "elapsed_seconds": 8 },
    "resolve_gaps": { "status": "running", "progress": { "current": 34, "total": 95 } },
    "verify_claims": { "status": "pending" },
    "detect_missing_citations": { "status": "pending" },
    "generate_report": { "status": "pending" }
  },
  "summary": {
    "total_references": 142,
    "pdfs_matched": 47,
    "pdfs_needing_confirmation": 3,
    "references_resolved": 34,
    "references_not_found": 5,
    "interventions_pending": 3
  }
}
```

---

### `POST /api/sessions/{session_id}/start`

Start (or resume) the verification pipeline.

**Request:** `204 No Content` (no body)

**Response:** `202 Accepted`
```json
{
  "message": "Pipeline started"
}
```

---

### `GET /api/sessions/{session_id}/events`

SSE endpoint for real-time pipeline progress.

**Response:** `text/event-stream`
```
data: {"stage": 1, "status": "running", "message": "Parsing manuscript..."}

data: {"stage": 1, "status": "complete", "message": "142 references extracted", "elapsed_seconds": 12}

data: {"stage": 2, "status": "running", "progress": {"current": 10, "total": 47}, "message": "Matching PDFs..."}

data: {"stage": 2, "status": "needs_input", "intervention": {"type": "confirm_match", "count": 3}}

data: {"stage": 3, "status": "running", "progress": {"current": 34, "total": 95}, "message": "Resolving gaps..."}

data: {"stage": 6, "status": "complete", "message": "Report ready"}

data: {"type": "pipeline_complete"}
```

**Event types:**
- Stage updates (status changes, progress, messages)
- Intervention requests (pipeline pauses, needs user action)
- Pipeline complete / pipeline error

---

## References

### `GET /api/sessions/{session_id}/references`

List all extracted references with current status.

**Query params:**
- `status` — Filter: `all` | `matched` | `needs_confirmation` | `unmatched` | `resolved` | `not_found`
- `sort` — Sort by: `id` | `status` | `confidence` (default: `id`)
- `page`, `per_page` — Pagination (default: page=1, per_page=50)

**Response:** `200 OK`
```json
{
  "references": [
    {
      "id": 1,
      "raw_text": "Smith J, et al. Drug X reduces mortality...",
      "title": "Drug X reduces mortality in elderly patients",
      "authors": ["Smith J", "Doe A", "Lee B"],
      "year": 2020,
      "doi": "10.1234/example.2020.001",
      "journal": "Lancet",
      "pmid": "32456789",
      "source_status": "found",
      "pdf_status": "matched",
      "pdf_source": "user_upload",
      "match_confidence": 0.99,
      "match_method": "doi"
    }
  ],
  "total": 142,
  "page": 1,
  "per_page": 50
}
```

---

### `GET /api/sessions/{session_id}/references/{ref_id}`

Get full detail for a single reference.

**Response:** `200 OK` — Same as list item plus:
```json
{
  "...reference fields...",
  "resolution_details": {
    "crossref_found": true,
    "pubmed_found": true,
    "semantic_scholar_found": true,
    "unpaywall_oa": true,
    "oa_url": "https://pmc.ncbi.nlm.nih.gov/...",
    "journal_url": "https://doi.org/10.1234/..."
  },
  "claims": [  # Note: In V4, this is replaced by VerificationUnit from Stage 2 (detect_citations)
    {
      "id": 1,
      "manuscript_text": "Drug X reduced mortality by 30% [1]",
      "extracted_claim": "Drug X reduced mortality by 30%",
      "claim_type": "factual",
      "priority": "high"
    }
  ],
  "verification": {
    "verdict": "contradicted",
    "confidence": 0.91,
    "evidence_quotes": ["non-significant 12% reduction (p=0.08)"],
    "reasoning": "Manuscript claims 30% but source reports 12%, non-significant",
    "tier": 1,
    "source_coverage": "full_text"
  }
}
```

---

## PDF Matching

### `POST /api/sessions/{session_id}/matches/{ref_id}/confirm`

Confirm or reject a suggested PDF match.

**Request:**
```json
{
  "confirmed": true
}
```

**Response:** `200 OK`
```json
{
  "reference_id": 2,
  "pdf_status": "matched",
  "match_confidence": 1.0,
  "match_method": "user_confirmed"
}
```

---

### `POST /api/sessions/{session_id}/references/{ref_id}/upload-pdf`

Upload a PDF for a specific reference (for paywalled papers).

**Request:** `multipart/form-data`
```
pdf: File (.pdf, required)
```

**Response:** `200 OK`
```json
{
  "reference_id": 4,
  "pdf_status": "matched",
  "pdf_source": "user_upload",
  "match_confidence": 1.0
}
```

---

### `PUT /api/sessions/{session_id}/references/{ref_id}/metadata`

Correct reference metadata and trigger re-resolution. (V1)

**Request:**
```json
{
  "title": "Corrected Title Here",
  "doi": "10.1234/corrected",
  "year": 2020
}
```

**Response:** `200 OK` — Updated reference object. Pipeline re-runs resolution for this reference.

---

## Verification Results (V1+)

### `GET /api/sessions/{session_id}/results`

Get all verification results.

**Query params:**
- `verdict` — Filter: `all` | `supported` | `partially_supported` | `not_supported` | `contradicted` | `cannot_verify`
- `priority` — Filter: `all` | `high` | `medium` | `low`
- `min_confidence` — Float 0.0-1.0
- `sort` — `verdict` | `confidence` | `priority` | `ref_id`

**Response:** `200 OK`
```json
{
  "summary": {
    "total": 142,
    "supported": 112,
    "partially_supported": 18,
    "not_supported": 5,
    "contradicted": 2,
    "cannot_verify": 5
  },
  "results": [
    {
      "claim_id": 1,
      "reference_id": 7,
      "verdict": "contradicted",
      "confidence": 0.91,
      "evidence_quotes": ["..."],
      "reasoning": "...",
      "tier": 1,
      "source_coverage": "full_text",
      "needs_user_review": false,
      "claim": {
        "manuscript_text": "Drug X reduced mortality by 30% [7]",
        "extracted_claim": "Drug X reduced mortality by 30%",
        "claim_type": "factual",
        "priority": "high"
      }
    }
  ],
  "total": 142,
  "page": 1,
  "per_page": 50
}
```

**V5.4 partial sub-types** (taxonomy ids and labels: `src/refcheck/models/partial_types.py`):
- Query param `partial_type` — a type id (`tangential_source`, `specific_detail_mismatch`,
  `unsupported_inference`, `scope_overgeneralized`, `missing_element`, `certainty_overstated`,
  `coverage_limited`), `unclassified` (partial results without a recorded type: older runs or
  reviewer overrides), `guarded`
  (supported results with `guards_applied`), `guarded:<guard>`, or `all`. Only partially
  supported verdicts are grouped by type; ANDed with the other filters; paging unchanged.
- Each result (and each verification of `GET /api/sessions/{id}/evidence/{claim_id}`) adds
  `partial_type` (str | null), `partial_severity` (`minor` | `major` | null), `author_action`
  (one sentence), `unsupported_elements` (list[str]) and `guards_applied` (list of
  `evidence_recheck` | `cocited_share` | `author_framing_or_example` | `overliteral_wording`).
  Missing severity / action on older rows are filled from the taxonomy defaults. When a reviewer
  override changed the verdict, these fields are empty (they explained the model's verdict).
- `summary` adds `partial_types` (every type id plus `unclassified`, 0 included),
  `partial_severity` (`{"major": n, "minor": n}`), `guarded` (int) and `guards` (per guard).

**V5.8 degraded mode:** `summary.degraded_notices` (list[str]) has one sentence per LLM role
that ran degraded in the run (screen skipped, BM25-only retrieval, confirm on a same-family
fallback...), then each fix once (e.g. "Add credits to the OpenAI account..."); `[]` for a
normal run. Read from `<session_dir>/llm_degradations.json`; `GET /api/sessions/{session_id}`
returns the same list as `degraded_notices`. The Results page shows it as an amber banner.

### `GET /api/sessions/{session_id}/partial-breakdown` (V5.4)

Partially supported results by sub-type, and supported results whose concern a benign guard
cleared.

**Response:** `200 OK`
```json
{
  "total_partial": 18,
  "types": [
    {"type": "specific_detail_mismatch", "label": "Wrong or missing specifics",
     "meaning": "...", "severity": "major", "count": 3, "major": 3, "minor": 0,
     "author_action": "...", "claim_ids": [4, 9, 31]}
  ],
  "guarded": 12,
  "guards": [
    {"guard": "cocited_share", "label": "Co-cited reference", "explanation": "...",
     "count": 7, "claim_ids": [2, 5]}
  ]
}
```
`types` lists every type in taxonomy order, then `unclassified`; `guards` lists every guard.

---

### `POST /api/sessions/{session_id}/results/{claim_id}/override` (V2)

User overrides a verification verdict.

**Request:**
```json
{
  "verdict": "supported",
  "reason": "I verified manually — the 30% figure is in Table 3"
}
```

**Response:** `200 OK` — Updated result with `user_override: true`.

---

## Reports

### `GET /api/sessions/{session_id}/report`

Download the generated DOCX report.

**Response:** `200 OK`
- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `Content-Disposition: attachment; filename="refcheck_report_sess_abc123.docx"`

**Errors:**
- `404` — Report not yet generated
- `409` — Pipeline still running

---

### `POST /api/sessions/{session_id}/report/regenerate` (V2)

Regenerate report after user overrides.

**Response:** `202 Accepted`
```json
{
  "message": "Report regeneration started"
}
```

---

## Health

### `GET /api/health`

Query: `deep=true` probes every LLM role with one tiny real call (cached 10 minutes; a role down
for a persistent cause re-tests exhausted keys first, so added credits take effect at once).

**Response:** `200 OK` (`HealthResponse`, `api/routes/health.py`)
```json
{
  "status": "ok",
  "grobid": "connected" | "unavailable",
  "database": "connected" | "disconnected",
  "version": "3.0.0",
  "llm": "ok" | "degraded" | "unavailable" | "unknown",   // "unavailable" only when the verifier is dead
  "decisions_api": "available" | "unavailable" | "disabled" | "unknown",
  "privacy_profile": "standard" | "anthropic_only",
  "deep": false,
  "models": {
    "confirm": {                                  // RoleHealth (api/routes/health_llm.py)
      "role": "confirm", "model_id": "claude-sonnet-5-5", "available": true, "enabled": true,
      "last_error": null, "fallback_index": 0, "candidates": ["gpt-6-luna", "gpt-6.1-sol"],
      "probed": true, "probe_ok": true, "latency_ms": 840, "checked_at": 1761200000.0,
      // V5.8 degraded mode
      "degraded": true,
      "degraded_mode": "fallback" | "skipped" | "bm25_only" | "unavailable" | null,
      "cause": "billing" | "auth" | "no_key" | "not_found" | "network" | "rate_limit" | "budget" | "other" | null,
      "persistent": true,                         // will not fix itself
      "effect": "cross-check runs on claude-sonnet-5-5, the same model family as the verifier: ...",
      "action": "Add credits to the OpenAI account (or set a key with credit), then re-run."
    }
  },
  "degraded_notices": ["confirm: OpenAI no credits / quota exhausted — ..."],
  "actions": ["Add credits to the OpenAI account (or set a key with credit), then re-run."]
}
```

---

## Implementation Notes

### Pipeline Stages (V4)

The pipeline now consists of 7 stages:
1. **Parse DOCX** — Extract references and manuscript structure
2. **Detect Citations** — Deterministic citation detection (replaces LLM-based claim extraction)
3. **Match PDFs** — Match uploaded PDFs to references
4. **Resolve Gaps** — Retrieve missing papers via academic APIs
5. **Verify Claims** — LLM verification of citation-claim pairs
6. **Detect Missing Citations** — Identify claims that should have citations but don't
7. **Generate Report** — Create DOCX verification report

**Note:** Stage 2 now uses `VerificationUnit` instead of `Claim`. The citation-first approach detects citations deterministically rather than using LLM extraction.

### FastAPI Router Structure

```python
# src/refcheck/api/routes/
#   sessions.py    — POST/GET sessions, start pipeline
#   references.py  — GET references, confirm matches, upload PDFs
#   events.py      — SSE streaming endpoint
#   results.py     — GET results, POST overrides (V1+)
#   reports.py     — GET/POST reports
#   health.py      — Health check

# src/refcheck/api/main.py — ties them together
app = FastAPI(title="RefCheck AI", version="0.1.0")
app.include_router(sessions_router, prefix="/api")
app.include_router(references_router, prefix="/api")
# ...
```

### CORS (Development)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Response Models

Every endpoint uses a Pydantic response model. FastAPI auto-generates OpenAPI spec from these models. Frontend TypeScript types in `lib/types.ts` should mirror these exactly (V5.8: `lib/types.ts` is a barrel over `reference-types.ts`, `session-types.ts`, `result-types.ts`, `evidence-types.ts`, `cascade-types.ts`, `signal-types.ts` and the partial-type module; `lib/api.ts` re-exports `api-client.ts`, `api-sessions.ts`, `api-references.ts`, `api-results.ts` and `api-reports.ts`).

### Versioning Strategy

No URL versioning for MVP. If breaking changes are needed before V1, bump the API version header. Full URL versioning (`/api/v2/`) only if public API is exposed (post-V3).
