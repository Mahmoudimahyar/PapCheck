# RefCheck AI — Tech Stack Decision Document

**Date:** 2026-02-11
**Status:** Decided
**Decision Criteria:** AI-buildability, library maturity, cloud portability, cost

---

## Executive Summary

Python monorepo with FastAPI, running locally first via Docker Compose. Cloud deployment via **AWS (Bedrock + Lambda + S3)** as primary, with architecture that can swap to Google Vertex AI if pricing shifts. Claude Sonnet as the primary verification LLM. GROBID as a sidecar service for PDF parsing.

---

## 1. Language & Runtime

### Decision: **Python 3.11+**

**Why:**
- AI agents (Claude Code, Cursor, Codex) generate Python more reliably than any other language — there's more Python training data, more Stack Overflow answers, more library documentation
- Every library we need exists in Python with mature, well-documented APIs
- The entire scientific computing ecosystem is Python-native (no bridging needed)
- FastAPI + async gives us sufficient performance for our workload (we're I/O bound, not CPU bound)
- Type hints with Pydantic give us structured LLM outputs with validation "for free"

**What we considered and rejected:**
- TypeScript/Node: Strong ecosystem but worse scientific library support, fewer academic API clients
- Go: Faster but fewer ML/NLP libraries, harder for AI agents to generate correctly
- Rust: Overkill for our use case, much harder for AI agents to build

---

## 2. Application Framework

### Decision: **FastAPI**

```
pip install fastapi uvicorn python-multipart
```

**Why:**
- Native async support — critical because our pipeline is I/O heavy (API calls, file reads, LLM calls)
- Pydantic integration is native — our data models become API schemas automatically
- Auto-generated OpenAPI docs — helpful for debugging and future web frontend integration
- Background tasks built-in — long verification jobs don't block the API
- Dependency injection — clean way to manage API clients, database connections, LLM clients
- Most popular Python API framework in 2025 — AI agents have extensive training data for it

**Architecture:**
- Web UI from day one — FastAPI backend serves API, Next.js frontend consumes it
- Phase 2: HTTP API server for potential web frontend
- Cloud: Each pipeline stage becomes a separate endpoint, can be split into microservices later

**What we considered:**
- Flask: Simpler but no native async, no Pydantic integration
- Django: Too heavy for our use case, ORM we don't need
- Plain scripts: Works for MVP but doesn't scale to web or microservices

---

## 3. Pipeline Stage Libraries

### Stage 1: DOCX Parsing

| Library | Purpose | Why This One |
|---------|---------|--------------|
| **python-docx** | DOCX text extraction | Standard, well-maintained, handles styles and structure |
| **lxml** | XML parsing for field codes | Needed to extract Zotero/Mendeley/EndNote metadata embedded in DOCX XML |

**Implementation note:** python-docx handles paragraph/table extraction well. For citation field codes, we need to access the raw XML via `lxml` because python-docx doesn't expose `w:fldChar` elements. This is well-documented and AI agents can handle it.

### Stage 2: Claim-Citation Extraction

| Library | Purpose | Why This One |
|---------|---------|--------------|
| **anthropic** SDK | Claude API calls | Primary LLM for claim extraction |
| **jinja2** | Prompt templating | Keeps prompts separate from code, supports variables |
| **pydantic** | Output validation | Validates LLM JSON output against our schemas |

### Stage 3: PDF Processing & Matching

| Library | Purpose | Why This One |
|---------|---------|--------------|
| **PyMuPDF (fitz)** | PDF text & metadata extraction | Fastest Python PDF library, extracts text + metadata + DOIs. Also has built-in OCR |
| **GROBID** (Docker sidecar) | Scientific PDF structure parsing | Production-grade (.87 F1 on reference parsing), used by ResearchGate, Mendeley, Internet Archive. Parses PDF into structured sections: title, abstract, authors, references, body sections |
| **grobid-client-python** | Python client for GROBID | Official client, handles batch processing |
| **rapidfuzz** | Fuzzy string matching | MIT-licensed, C++ backend (100x faster than fuzzywuzzy), perfect for title matching |

**Why GROBID as a sidecar instead of pure Python PDF parsing:**
GROBID is a Java service but we run it as a Docker container and call it via REST API. This gives us:
- .87-.90 F1 score on reference extraction from PDFs (far better than anything we could build)
- Structured output: sections, figures, tables, references all parsed
- The Python client makes it feel native
- In cloud deployment, it becomes its own microservice naturally

```yaml
# docker-compose.yml (local development)
services:
  grobid:
    image: lfoppiano/grobid:0.8.1
    ports:
      - "8070:8070"
```

### Stage 4: Reference Resolution & Retrieval

| Library | Purpose | Why This One |
|---------|---------|--------------|
| **httpx** | Async HTTP client | Async-native, connection pooling, automatic retries. Replaces requests for async work |
| **semanticscholar** | Semantic Scholar API client | Official Python client, handles pagination and rate limiting |
| **tenacity** | Retry logic | Decorator-based retries with exponential backoff, works with async |
| **diskcache** | Local response caching | Simple file-based cache, survives restarts, no database needed |

**API integration details:**

| API | Client | Auth | Rate Limit |
|-----|--------|------|-----------|
| CrossRef | httpx (direct, their API is simple REST) | Polite header with email | 50/sec polite pool |
| Semantic Scholar | `semanticscholar` Python package | API key (free tier) | 100 requests/5 min |
| PubMed/NCBI | httpx + Entrez URL patterns | API key (free) | 10/sec with key |
| Unpaywall | httpx (simple REST) | Email as parameter | 100k/day |
| OpenAlex | httpx (REST, free) | Polite header | Generous |

**Why we're using multiple APIs instead of just one:**
CrossRef is best for DOI resolution. Semantic Scholar has the best abstract database and open-access links. PubMed covers biomedical literature most comprehensively. Unpaywall specifically finds free PDF versions. OpenAlex is a fallback with good coverage. By querying in sequence and caching, we maximize the chance of finding any given paper.

### Stage 5: LLM Verification

| Library | Purpose | Why This One |
|---------|---------|--------------|
| **anthropic** SDK | Claude API (primary verifier) | Best for structured reasoning with long context |
| **openai** SDK | GPT API (Tier 2 second opinion) | Different training data = independent second opinion |
| **litellm** | Unified LLM interface | Single interface for Claude, GPT, Gemini — makes multi-model voting easy. Also handles retries and fallbacks |

**LLM Selection:**

| Role | Model | Why |
|------|-------|-----|
| Primary verifier (Tier 1) | **Claude Sonnet 4.5** | Best price/performance for structured reasoning. ~$3/1M input tokens. Excellent at following complex instructions and producing valid JSON |
| Second opinion (Tier 2) | **GPT-4o** | Different training data from Claude = genuinely independent second opinion |
| Claim extraction | **Claude Sonnet 4.5** | Same model, different prompt. Claim extraction is simpler than verification |
| PDF section retrieval | **Claude Haiku 4.5** | Cheap and fast, just needs to identify relevant paragraphs |

**Why Claude Sonnet as primary (not Opus):**
- Sonnet is ~10x cheaper than Opus
- For structured verification with forced grounding, Sonnet follows instructions just as well
- A manuscript with 60 references = ~60-80 LLM calls. At Opus pricing, that's expensive. At Sonnet pricing, it's a few dollars total
- We can always escalate individual uncertain cases to Opus in Tier 2

**Why not fully open-source LLMs:**
- For verification accuracy, we need the best models available
- Llama/Mistral are good but measurably worse at complex multi-step reasoning with grounding
- Cost reduction phase can experiment with local models later

### Stage 6: Report Generation

| Library | Purpose | Why This One |
|---------|---------|--------------|
| **python-docx** | DOCX report creation | Same library used for parsing, familiar API, handles tables and formatting |

---

## 4. Data Layer

### Decision: **File-based + SQLite (no heavy database)**

| Component | Technology | Why |
|-----------|-----------|-----|
| Pipeline state | JSON files (Pydantic → JSON serialization) | Simple, portable, human-readable, git-friendly |
| API response cache | **diskcache** (file-based) | No database server needed, survives restarts |
| Reference library (persistent) | **SQLite** via **SQLModel** | Zero-config, file-based, SQL when we need it, ORM with Pydantic |
| PDF storage | Local filesystem | Simple, no object storage needed locally |

**Why not PostgreSQL or MongoDB:**
- We're running locally first. Users shouldn't need to install a database server.
- SQLite handles our query patterns fine (lookup by DOI, title search)
- SQLModel (by the FastAPI creator) gives us Pydantic models that are also database tables — zero mapping overhead
- When we move to cloud, SQLite → PostgreSQL is a straightforward migration via SQLModel

---

## 5. Development & Testing

| Tool | Purpose | Why |
|------|---------|-----|
| **pytest** | Testing framework | Industry standard, excellent fixture system |
| **pytest-asyncio** | Async test support | Needed for testing async pipeline stages |
| **pytest-recording** (VCR.py) | API response recording | Record real API responses once, replay in tests forever |
| **ruff** | Linting + formatting | 10-100x faster than flake8+black combined, one tool instead of two |
| **mypy** | Type checking | Catches type errors before runtime, works with Pydantic |
| **pyproject.toml** | Project config | Single config file for all tools (ruff, mypy, pytest) |
| **uv** | Package management | Extremely fast Python package installer (written in Rust), drop-in pip replacement |
| **Docker Compose** | Local services | Runs GROBID sidecar, potentially other services |

---

## 6. Cloud Deployment Strategy

### Decision: **AWS as primary, architecture portable to GCP**

**Why AWS over GCP:**
- AWS Bedrock provides Claude access with the same API shape as Anthropic's direct API — minimal code changes
- Bedrock's Intelligent Prompt Routing can auto-route between Sonnet and Haiku for cost optimization
- S3 for PDF storage is cheapest and most mature
- Lambda for pipeline stages is cost-effective (pay per invocation, not per hour)
- Bedrock pricing for Claude is comparable to direct API pricing, sometimes cheaper with caching

**Why not GCP:**
- Vertex AI also offers Claude, at similar pricing (with a 10% premium for regional endpoints)
- Vertex is stronger for custom model training (which we don't need)
- If GCP becomes cheaper for our workload, the switch is straightforward because we use `litellm` as our LLM abstraction layer

### Cloud Architecture (Future)

```
                    ┌─────────────────┐
                    │  API Gateway     │
                    │  (REST/WebSocket)│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Lambda:  │  │ Lambda:  │  │ Lambda:  │
        │ Parse    │  │ Resolve  │  │ Verify   │
        │ DOCX     │  │ & Match  │  │ Claims   │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             │              │              │
             ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ S3:      │  │ ECS:     │  │ Bedrock: │
        │ PDFs +   │  │ GROBID   │  │ Claude   │
        │ State    │  │ Service  │  │ Sonnet   │
        └──────────┘  └──────────┘  └──────────┘
```

| Local Component | Cloud Equivalent | Migration Effort |
|----------------|-----------------|-----------------|
| Local filesystem | S3 | Low (boto3 + path abstraction) |
| SQLite | DynamoDB or RDS PostgreSQL | Medium (SQLModel migration) |
| Direct Anthropic API | AWS Bedrock | Low (litellm handles this) |
| Docker GROBID | ECS Fargate service | Low (same Docker image) |
| Web UI | API Gateway + Lambda | Medium (FastAPI → Lambda via Mangum) |
| diskcache | ElastiCache or DynamoDB | Medium |

**Key portability decision:** By using `litellm` as our LLM abstraction, switching between Anthropic direct API → AWS Bedrock → Google Vertex AI is a config change, not a code change.

---

## 7. Containerization

### Decision: **Docker Compose for local, separate containers per service for cloud**

```yaml
# docker-compose.yml
services:
  refcheck:
    build: .
    volumes:
      - ./data:/app/data          # manuscripts, PDFs, reports
      - ./cache:/app/cache        # API response cache
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SEMANTIC_SCHOLAR_API_KEY=${SEMANTIC_SCHOLAR_API_KEY}
    depends_on:
      - grobid

  grobid:
    image: lfoppiano/grobid:0.8.1
    ports:
      - "8070:8070"
    deploy:
      resources:
        limits:
          memory: 4G
```

---

## 8. Full Dependency List

```toml
# pyproject.toml
[project]
name = "refcheck"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # Framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "python-multipart>=0.0.12",

    # Data models
    "pydantic>=2.10.0",
    "sqlmodel>=0.0.22",

    # DOCX processing
    "python-docx>=1.1.0",
    "lxml>=5.0.0",

    # PDF processing
    "PyMuPDF>=1.24.0",
    "grobid-client-python>=0.0.9",

    # String matching
    "rapidfuzz>=3.10.0",

    # HTTP & APIs
    "httpx>=0.27.0",
    "semanticscholar>=0.8.0",
    "tenacity>=9.0.0",

    # LLM
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "litellm>=1.50.0",

    # Prompts
    "jinja2>=3.1.0",

    # Caching
    "diskcache>=5.6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-recording>=0.13.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]
```

---

## 9. Cost Estimate (Per Manuscript, 60 References)

| Component | Estimate | Notes |
|-----------|----------|-------|
| Claude Sonnet (claim extraction, ~60 calls) | ~$0.30 | Short prompts, structured output |
| Claude Sonnet (verification, ~60 calls) | ~$1.50 | Longer prompts with source text |
| Claude Haiku (section retrieval, ~60 calls) | ~$0.05 | Very short prompts |
| GPT-4o (Tier 2 second opinion, ~10 calls) | ~$0.30 | Only for uncertain cases |
| API calls (CrossRef, S2, Unpaywall) | $0.00 | Free APIs |
| GROBID (self-hosted) | $0.00 | Runs locally |
| **Total per manuscript** | **~$2.15** | |

This is very affordable. Even processing 100 manuscripts would cost ~$215.

---

## 10. Why This Stack Is AI-Agent Friendly

1. **Python + FastAPI + Pydantic** — the most commonly generated stack by AI agents in 2025. Massive training data.
2. **All libraries are pip-installable** — no complex build steps, no C++ compilation (except rapidfuzz which ships pre-built wheels)
3. **GROBID via Docker** — agent just runs `docker-compose up`, no Java installation
4. **Standard patterns** — async/await, Pydantic models, pytest fixtures. AI agents have seen millions of examples.
5. **pyproject.toml** — single config file, no scattered setup.cfg/requirements.txt/tox.ini
6. **Type hints everywhere** — helps the AI agent understand function contracts and catch errors via mypy
7. **litellm abstraction** — agent doesn't need to learn multiple LLM SDKs, one interface handles all
8. **diskcache** — zero configuration caching, no Redis/Memcached setup
9. **SQLModel** — Pydantic + SQLAlchemy in one, AI agents understand both individually

---

## 11. Tech Stack Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| GROBID Docker image is large (~4GB) | Slow first startup | Pre-pull in setup script, document expected wait |
| litellm introduces abstraction bugs | Medium | We also keep direct anthropic/openai SDKs as fallback |
| PyMuPDF licensing (AGPL) | Low for our use | We're not distributing; if needed, switch to pymupdf4llm or pdfplumber |
| Semantic Scholar API changes | Low | We cache responses; API has been stable for years |
| AWS Bedrock Claude pricing increases | Low | litellm lets us switch to Vertex AI or direct API with config change |
