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
    │  PDF parse  │  │ PubMed    │  │ Claude/GPT        │
    │             │  │ CrossRef  │  │ via Bedrock or    │
    │             │  │ S2, Unpw  │  │ direct API        │
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
  → Stage 2: Extract Claims ► list[Claim]           ← user reviews
  → Stage 3: Match PDFs ──► list[MatchResult]        ← user confirms
  → Stage 4: Resolve Gaps ─► list[Reference]         ← user uploads
  → Stage 5: Verify Claims ► list[VerificationResult] ← user resolves (V2)
  → Stage 6: Full Report ──► DOCX (verification report)
```

### Stage Details

| Stage | Module | Input | Output | User Intervention | Feature Spec |
|-------|--------|-------|--------|-------------------|-------------|
| 1 | `stages/parse_docx/` | DOCX file | `ParsedManuscript` | IP-1: confirm refs | `01_docx_parsing.md` |
| 2 | `stages/extract_claims/` | `ParsedManuscript` | `list[Claim]` | IP-2: review claims | `02_claim_extraction.md` |
| 3 | `stages/match_pdfs/` | `list[Reference]` + PDFs | `list[MatchResult]` | IP-3: confirm matches | `03_pdf_matching.md` |
| 4 | `stages/resolve_gaps/` | `list[Reference]` | Updated refs with PDFs | IP-4: upload paywalled | `04_gap_resolution.md` |
| 5 | `stages/verify_claims/` | Claims + References | `list[VerificationResult]` | IP-5,6: resolve ambiguity | `05_verification.md` |
| 6 | `stages/generate_report/` | All pipeline data | DOCX report | IP-7: accept/override | `06_report_generation.md` |

**Key rule:** Stages never import from each other. They communicate only through Pydantic models defined in `src/refcheck/models/`.

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

All LLM calls go through a unified abstraction layer using litellm:

```
Python code → call_llm() → Jinja2 template → litellm → Claude/GPT/Bedrock
                  │
                  ├── Loads prompt from src/refcheck/prompts/{name}.md
                  ├── Renders with Jinja2 variables
                  ├── Calls litellm.acompletion() (async)
                  ├── Parses JSON response
                  ├── Validates against Pydantic output model
                  ├── Retries once on validation failure
                  └── Logs full prompt + response
```

**Why litellm:** Swap between Anthropic direct API, AWS Bedrock, Google Vertex AI, or OpenAI with a config change. No code changes needed.

See `docs/prompts/PROMPT_ENGINEERING.md` for prompt design guidelines.

## Caching Strategy

- **API responses:** diskcache (file-based, keyed by query hash)
- **PDF text extractions:** cached alongside original PDF
- **LLM responses:** cached by prompt hash (for identical re-verification)
- **Cache location:** `~/.refcheck/cache/`
- **Invalidation:** manual only (future: TTL-based)

## Error Handling Philosophy

- **API errors** → retry with backoff via tenacity, then mark as `api_error`
- **Parse errors** → surface to user with context, never silently skip
- **LLM errors** → retry once, then mark as `cannot_verify` with explanation
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
