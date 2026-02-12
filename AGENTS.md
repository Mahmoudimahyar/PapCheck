# RefCheck AI — Agent Instructions

## Project Summary
RefCheck AI verifies scientific manuscript references for biomedical research. It parses DOCX manuscripts, extracts claim-citation pairs, matches user-uploaded PDFs to references, retrieves open-access papers via PubMed/CrossRef/Semantic Scholar, and uses LLM verification to check if cited sources support the claims made. Web UI from day one.

## Tech Stack
- **Backend:** Python 3.11+ / FastAPI / Pydantic / SQLModel (SQLite)
- **Frontend:** Next.js 15 (App Router) / shadcn/ui / Tailwind CSS v4 / Recharts / TanStack Query
- **LLM:** litellm (unified interface) → Claude Sonnet 4.5 primary, GPT-4o secondary
- **PDF parsing:** PyMuPDF + GROBID (Docker sidecar)
- **Academic APIs:** httpx (async) + CrossRef, PubMed/NCBI, Semantic Scholar, Unpaywall
- **Matching:** rapidfuzz (fuzzy string matching)
- **Caching:** diskcache (file-based)
- **Testing:** pytest / ruff / mypy
- **Infra:** Docker Compose (local) / AWS Bedrock + Lambda + S3 (future cloud)

## Project Structure
```
refcheck/
├── pyproject.toml
├── docker-compose.yml              # GROBID + backend
├── AGENTS.md / CLAUDE.md / README.md
├── docs/                           # All documentation (see below)
├── src/refcheck/                   # Python backend package
│   ├── models/                     # Pydantic data models ONLY
│   │   ├── reference.py
│   │   ├── claim.py
│   │   ├── verification.py
│   │   └── pipeline.py
│   ├── stages/                     # Pipeline stages (one folder per feature spec)
│   │   ├── parse_docx/
│   │   ├── extract_claims/
│   │   ├── match_pdfs/
│   │   ├── resolve_gaps/
│   │   ├── verify_claims/
│   │   └── generate_report/
│   ├── llm/                        # LLM abstraction (litellm wrapper)
│   │   ├── client.py               # call_llm() — template + API + validation
│   │   └── templates.py            # Jinja2 template loader
│   ├── prompts/                    # LLM prompt templates (Jinja2 .md files)
│   ├── api/                        # FastAPI routes (thin layer)
│   │   ├── main.py
│   │   └── routes/
│   ├── services/                   # Business logic orchestration
│   └── utils/                      # Shared utilities (small)
├── frontend/                       # Next.js app (separate package)
│   ├── src/app/                    # App Router pages
│   ├── src/components/ui/          # shadcn auto-generated
│   ├── src/components/refcheck/    # Custom components
│   ├── src/lib/                    # API client, SSE, types, utils
│   └── src/hooks/                  # React hooks
└── tests/                          # Mirrors src/ structure
    ├── unit/
    ├── integration/
    ├── e2e/
    ├── canary/
    └── fixtures/
```

## Core Commands
```bash
# Backend
pip install -e ".[dev]" --break-system-packages
uvicorn refcheck.api.main:app --reload --port 8001   # Dev server on :8001
pytest tests/ -v                                      # All tests
pytest tests/unit/test_parse_docx.py -v              # Single module
ruff check src/                                       # Lint
mypy src/                                             # Type check

# Frontend
cd frontend && npm install
npm run dev                                           # Dev server on :3000

# Infrastructure
docker compose up -d                                  # Start GROBID sidecar
```

## Code Standards (enforced — read `docs/CODE_STANDARDS.md`)
- No file exceeds 200 lines (split it)
- No `print()` — use `logging`
- No `Any` type hints — figure out the actual type
- No inline prompt strings — use Jinja2 templates in `src/refcheck/prompts/`
- No wildcard imports, no mutable defaults, no bare `except:`
- Type hints on ALL function signatures
- Pydantic models for all data structures — never raw dicts
- Every external call has explicit error handling
- Always distinguish "couldn't check" from "checked and failed"
- Comments explain WHY, not WHAT

## Architecture Decisions
- Pipeline stages are independent — never import from each other
- Models are the contract — Pydantic everywhere
- LLM layer is isolated — no direct anthropic/openai imports, use litellm via `call_llm()`
- Prompts are separate files — Jinja2 templates in `src/refcheck/prompts/`
- API layer is thin — validate → call service → return
- Frontend and backend are separate packages in one monorepo
- SSE for real-time pipeline progress (not polling, not WebSocket)
- Auth deferred — no auth for local, pluggable when moving to cloud

## Critical Constraints
- NEVER hardcode API keys — use environment variables
- NEVER skip Pydantic validation on LLM outputs
- NEVER feed entire papers to verification LLM — use RAG to find relevant sections
- NEVER conflate "paper not found" with "API unreachable"
- ALWAYS include confidence scores with every LLM judgment
- ALWAYS validate evidence quotes against source text post-hoc

## Deeper Documentation
| Document | When to read |
|----------|-------------|
| `docs/PRD.md` | Requirements, success metrics, user intervention points |
| `docs/ARCHITECTURE.md` | System design, data flow, stage connections |
| `docs/ROADMAP.md` | Version plan (MVP→V1→V2→V3), feature×version matrix |
| `docs/TECH_STACK.md` | Tech decisions with rationale |
| `docs/CODE_STANDARDS.md` | Anti-slop rules, naming, patterns |
| `docs/FRONTEND.md` | UI spec, component map, design system |
| `docs/API_CONTRACT.md` | All API endpoints between frontend and backend |
| `docs/features/01-06_*.md` | Detailed spec per pipeline stage |
| `docs/prompts/PROMPT_ENGINEERING.md` | LLM prompt design guidelines |
| `docs/tests/TEST_STRATEGY.md` | Test strategy, fixtures, agent loop protocol |
| `docs/DOCUMENTATION_GUIDE.md` | How this doc system works |
