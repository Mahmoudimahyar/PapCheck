# RefCheck AI — Scientific Reference Verification System

RefCheck AI verifies the accuracy and validity of references in biomedical research manuscripts. Upload a DOCX manuscript and your reference PDFs, and the system automatically extracts references, matches papers, retrieves open-access versions, and uses LLMs to verify whether each cited source genuinely supports the claims made.

## The Problem

Biomedical manuscripts typically contain 100-200 references. Currently there is no scalable way to verify that:
1. Each reference actually exists and is correctly cited (correct authors, title, year, DOI)
2. The cited paper's content actually supports the claim being made
3. References haven't been retracted or corrected since publication

Manual verification is impractical. Reviewers spot-check a few references at best. Errors range from innocent typos to fabricated references and misrepresented findings.

## The Solution

A web-based AI-powered pipeline that:
- Parses DOCX manuscripts and extracts structured reference lists
- Lets you bulk-upload PDFs, then smart-matches them to references
- Automatically retrieves open-access papers (PubMed Central, Unpaywall)
- Provides direct links for paywalled papers you need to obtain
- Uses tiered LLM verification to check every claim against its source
- Produces a structured DOCX verification report with actionable findings
- Shows real-time progress via a clean, scientific web interface

## Quick Start

```bash
# Clone and install backend
git clone <repo-url> && cd refcheck
pip install -e ".[dev]" --break-system-packages

# Start GROBID (PDF parsing sidecar)
docker compose up -d

# Start backend API server
uvicorn refcheck.api.main:app --reload

# In a new terminal — install and start frontend
cd frontend && npm install && npm run dev

# Open http://localhost:3000
```

### Environment Variables
```bash
# .env file in project root
ANTHROPIC_API_KEY=sk-ant-...          # Required for LLM verification
OPENAI_API_KEY=sk-...                 # Optional (multi-model voting in V2)
SEMANTIC_SCHOLAR_API_KEY=...          # Optional (higher rate limits)
NCBI_API_KEY=...                      # Optional (higher PubMed rate limits)
UNPAYWALL_EMAIL=your@email.com        # Required for Unpaywall API
```

## Documentation

| Document | Description |
|----------|-------------|
| [Product Requirements (PRD)](docs/PRD.md) | What we're building and why |
| [Architecture](docs/ARCHITECTURE.md) | System design and data flow |
| [Roadmap](docs/ROADMAP.md) | Version plan: MVP → V1 → V2 → V3 |
| [Tech Stack](docs/TECH_STACK.md) | Technology choices with rationale |
| [Code Standards](docs/CODE_STANDARDS.md) | Coding rules and patterns |
| [Frontend Spec](docs/FRONTEND.md) | UI design, components, pages |
| [API Contract](docs/API_CONTRACT.md) | All API endpoints |
| [Feature Specs](docs/features/) | Detailed spec per pipeline stage |
| [Prompt Engineering](docs/prompts/PROMPT_ENGINEERING.md) | LLM prompt guidelines |
| [Test Strategy](docs/tests/TEST_STRATEGY.md) | Testing approach and metrics |

## Version Roadmap

| Version | What it does |
|---------|-------------|
| **MVP** | Parse manuscripts, match PDFs, resolve via APIs, existence report, web UI |
| **V1** | Add LLM claim extraction and single-model verification |
| **V2** | Multi-model voting, retraction checking, interactive review |
| **V3** | Full polish, performance optimization, ready for public local use |

See [ROADMAP.md](docs/ROADMAP.md) for the full feature × version matrix.

## License

TBD
