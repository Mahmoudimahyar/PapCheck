# Documentation System Guide

## Why This Structure Exists

This project is designed to be built primarily by AI coding agents (Claude Code, Cursor, Codex, etc.). The documentation is structured to give these agents the right context at the right time, following the principle of **progressive disclosure**: agents see high-level context first and drill into details only when working on a specific feature.

## Design Principles

### 1. Progressive Disclosure
Agents have limited context windows. Cramming everything into one file degrades performance. Instead:
- **Root level** (AGENTS.md): project overview, structure, commands, conventions (~100 lines)
- **Architecture level** (docs/ARCHITECTURE.md): how stages connect, data flow
- **Feature level** (docs/features/XX.md): deep detail for each pipeline stage
- **Specialist docs** (FRONTEND.md, API_CONTRACT.md, etc.): loaded only when working in that area

An agent working on PDF matching reads AGENTS.md (always loaded) + `docs/features/03_pdf_matching.md` (loaded when needed). It doesn't need the frontend spec cluttering its context.

### 2. Specs Are Executable
Every feature spec includes concrete tests and metrics. The agent's loop is:
1. Read the spec
2. Implement
3. Run tests
4. Fix until tests pass

This is not aspirational — it's how the agent is instructed to work (see `docs/tests/TEST_STRATEGY.md`).

### 3. Cross-Tool Compatibility
- `AGENTS.md` — read by Cursor, Codex, Jules, Aider, Zed, and most modern agents
- `CLAUDE.md` — read by Claude Code (points to AGENTS.md)
- All docs are plain Markdown — universally readable

### 4. Living Documents
These docs evolve with the project. When implementation reveals something doesn't work as specified, the spec should be updated. When user feedback reveals a missing edge case, add it.

## File Map

```
refcheck/
├── README.md                              # Human-facing: what is this, how to use it
├── AGENTS.md                              # Agent-facing: project context, structure, conventions
├── CLAUDE.md                              # Claude Code compatibility (points to AGENTS.md)
│
├── docs/
│   ├── PRD.md                             # Product requirements (the "what and why")
│   ├── ARCHITECTURE.md                    # System design and data flow (the "how, high level")
│   ├── ROADMAP.md                         # Version plan: MVP→V1→V2→V3 with feature matrix
│   ├── TECH_STACK.md                      # Technology decisions with rationale
│   ├── CODE_STANDARDS.md                  # Anti-slop rules, naming, patterns
│   ├── FRONTEND.md                        # UI spec, design system, component map, pages
│   ├── API_CONTRACT.md                    # All API endpoints between frontend and backend
│   ├── DOCUMENTATION_GUIDE.md             # This file — explains the doc system itself
│   │
│   ├── features/                          # One spec per pipeline stage (the "how, detailed")
│   │   ├── 01_docx_parsing.md
│   │   ├── 02_claim_extraction.md
│   │   ├── 03_pdf_matching.md
│   │   ├── 04_gap_resolution.md
│   │   ├── 05_verification.md
│   │   └── 06_report_generation.md
│   │
│   ├── prompts/                           # LLM prompt engineering guidelines
│   │   └── PROMPT_ENGINEERING.md
│   │
│   └── tests/                             # Test strategy and metrics
│       └── TEST_STRATEGY.md
```

## Document Hierarchy and When to Read What

| Working on... | Read these docs |
|---------------|----------------|
| Understanding the project | README.md → PRD.md |
| Starting any coding task | AGENTS.md (auto-loaded) |
| Understanding how stages connect | ARCHITECTURE.md |
| Implementing a specific stage | docs/features/XX_{stage}.md |
| Planning what to build next | ROADMAP.md |
| Choosing or evaluating tech | TECH_STACK.md |
| Writing Python code | CODE_STANDARDS.md |
| Building frontend pages | FRONTEND.md + API_CONTRACT.md |
| Building API endpoints | API_CONTRACT.md |
| Writing or modifying LLM prompts | docs/prompts/PROMPT_ENGINEERING.md |
| Writing or running tests | docs/tests/TEST_STRATEGY.md |
| Understanding this doc system | DOCUMENTATION_GUIDE.md (this file) |

## How Each Document Type Serves the Agent

### AGENTS.md (Root)
**Loaded:** Automatically at every session start
**Purpose:** Orients the agent. What is this project? What's the tech stack? What are the conventions?
**Keep it:** Under 150 lines. Concise. Links to deeper docs.

### PRD.md
**Loaded:** When the agent needs to understand requirements, priorities, or success criteria
**Purpose:** The "source of truth" for what we're building and why

### ROADMAP.md
**Loaded:** When deciding what to build next or which sub-features belong in which version
**Purpose:** Version plan with feature × version matrix. Each version's scope is clear.

### TECH_STACK.md
**Loaded:** When evaluating technology choices or adding new dependencies
**Purpose:** Documents what we chose and why, so agents don't re-evaluate settled decisions

### CODE_STANDARDS.md
**Loaded:** When writing or reviewing Python code
**Purpose:** Anti-slop rules, naming conventions, patterns — prevents common AI-generated code problems

### FRONTEND.md
**Loaded:** When building or modifying any frontend page/component
**Purpose:** Design system, page specs, component map, SSE integration

### API_CONTRACT.md
**Loaded:** When building frontend API calls or backend endpoints
**Purpose:** The contract between frontend and backend — both sides reference this

### Feature Specs (docs/features/XX.md)
**Loaded:** When the agent is implementing that specific pipeline stage
**Purpose:** Everything needed to build and test one stage
**Template:** Purpose → Input → Output → Requirements → Edge Cases → Tests → Metrics → Implementation Notes

### ARCHITECTURE.md
**Loaded:** When understanding how stages connect
**Purpose:** Big picture — data flow, stage dependencies, SSE, folder structure

## Maintenance Rules

1. **Feature specs are the authority** — if code and spec disagree, fix the code (or update the spec with documented reasoning)
2. **Tests in feature specs are requirements** — they define acceptance criteria, not suggestions
3. **AGENTS.md stays lean** — resist the urge to add detail; link to deeper docs instead
4. **Every feature spec follows the same template** — consistency helps agents navigate
5. **Update docs in the same commit as code changes** — docs and code drift apart fast
6. **No orphan docs** — every document is linked from at least one other document
7. **ROADMAP.md is the plan of record** — if a feature isn't in the roadmap, it doesn't get built
