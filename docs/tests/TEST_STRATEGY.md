# Test Strategy & Quality Metrics

## Testing Philosophy

Every pipeline stage must be independently testable with fixture data. Tests serve two purposes:
1. Traditional quality assurance — catch bugs
2. **Agent loop gates** — the AI agent implementing a feature must run tests and iterate until all pass

## Agent Loop Protocol

When an AI coding agent implements any feature:

1. **Read** the feature spec in `docs/features/XX_feature.md`
2. **Implement** the feature in the specified module under `src/refcheck/stages/`
3. **Run tests** for that module: `pytest tests/unit/test_{module}.py -v`
4. **If tests fail:** read the failure output, fix the code, re-run tests
5. **Repeat steps 3-4** until ALL tests for that module pass
6. **Run linting:** `ruff check src/`
7. **Run type checking:** `mypy src/`
8. **Run the full test suite:** `pytest tests/ -v` — ensure no regressions
9. **Only then** report the feature as complete

The agent must NOT move to the next feature until the current feature's tests all pass.

## Test Types

### Unit Tests (per module)
- Located in `tests/unit/test_{module_name}.py`
- Test individual functions with mock data
- Must run without network access (mock all API calls)
- Must run without LLM access (mock LLM responses for non-LLM modules)
- Target: each module has ≥10 unit tests covering happy path + edge cases

### Integration Tests (per stage)
- Located in `tests/integration/test_stage_{N}.py`
- Test the full stage with realistic fixture data
- API calls mocked with recorded responses
- LLM calls use recorded responses for deterministic testing

### End-to-End Tests
- Located in `tests/e2e/test_pipeline.py`
- Run the full pipeline on a sample biomedical manuscript with known expected results
- May use live APIs (marked with `@pytest.mark.live`)
- Run manually before releases, not in CI

### Canary Tests (LLM-specific)
- Located in `tests/canary/test_llm_grounding.py`
- Verify LLMs read provided text rather than relying on memory
- Feed modified versions of known biomedical papers, verify LLM catches changes
- Must pass 100% — any failure indicates a grounding problem

### API Tests
- Located in `tests/unit/test_api_routes.py`
- Test FastAPI endpoints using `httpx.AsyncClient`
- Verify request/response contracts match `docs/API_CONTRACT.md`
- Test SSE event streaming

## Fixture Data Requirements

### `tests/fixtures/manuscripts/`
- `simple_10refs.docx` — Clean biomedical manuscript, 10 numbered references (Vancouver style)
- `complex_60refs.docx` — Real-world biomedical manuscript, 60 references
- `large_150refs.docx` — Biomedical manuscript, 150+ references (performance testing)
- `author_year.docx` — Author-year citation style
- `messy_format.docx` — Inconsistent formatting, some broken references
- `no_refs.docx` — Manuscript with no reference section
- `with_zotero.docx` — Contains Zotero field codes

### `tests/fixtures/pdfs/`
- 10-15 real open-access biomedical PDFs corresponding to references in fixture manuscripts
- 2-3 PDFs that DON'T match any reference (test false-match rejection)
- 1 scanned PDF (image-based, no extractable text)
- 1 preprint version of a paper whose journal version is in the reference list

### `tests/fixtures/api_responses/`
- Recorded PubMed, CrossRef, Semantic Scholar, Unpaywall responses
- Include both successful and error responses
- Include "not found" responses for fabricated references

### `tests/fixtures/llm_responses/`
- Recorded LLM outputs for claim extraction and verification
- Include both clean JSON and malformed responses (for error handling tests)

## Quality Metrics Dashboard

### Pipeline-Level Metrics

| Metric | Target | Priority |
|--------|--------|----------|
| Full pipeline success rate (no crashes) | 100% | Critical |
| End-to-end processing time (100 refs) | < 15 minutes | Medium |
| Total API cost per manuscript (100 refs) | ~$3-5 | Track |

### Stage-Level Metrics

| Stage | Key Metric | Target |
|-------|-----------|--------|
| 1. Parsing | Reference extraction F1 | ≥0.95 |
| 2. Claims | Claim-citation mapping accuracy | ≥0.85 |
| 3. Matching | Match precision at auto-accept | ≥0.98 |
| 4. Resolution | False "not found" rate | ≤5% |
| 5. Verification | Agreement with human experts | ≥80% |
| 6. Report | Summary statistics accuracy | 100% |

### LLM-Specific Metrics

| Metric | Target |
|--------|--------|
| Structured output parse success rate | ≥98% |
| Evidence quote validation rate | ≥95% |
| Canary test pass rate | 100% |
| Tier 2 escalation rate | 10-20% |
| Tier 3 escalation rate | 3-8% |

## Test Naming Convention

```
test_{module}_{scenario}_{expected_outcome}

Examples:
test_parse_docx_numbered_refs_extracts_all_10()
test_match_pdfs_no_doi_falls_back_to_title()
test_verify_claims_contradicted_claim_returns_contradicted()
test_resolve_gaps_api_timeout_returns_api_error_not_not_found()
```

## Continuous Quality Checks

```bash
# Quick check (< 30 seconds)
pytest tests/unit/ -v
ruff check src/
mypy src/

# Full check (before release)
pytest tests/ -v --ignore=tests/e2e

# E2E (manual, may use live APIs)
pytest tests/e2e/ -v -m live
```
