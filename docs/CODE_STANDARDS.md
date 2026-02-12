# RefCheck AI — Code Standards

**Purpose:** These rules prevent AI-generated slop and ensure every file in this codebase is modular, readable, and maintainable. AI agents MUST follow these rules. Human reviewers enforce them.

---

## Hard Rules (Zero Tolerance)

1. **No file exceeds 200 lines** (excluding tests and configs). Split it.
2. **No `print()` statements.** Use `import logging; logger = logging.getLogger(__name__)`.
3. **No `Any` type hints.** Figure out the actual type.
4. **No inline prompt strings.** All LLM prompts live in `src/refcheck/prompts/` as Jinja2 `.md` files.
5. **No wildcard imports** (`from module import *`).
6. **No mutable default arguments** (`def f(items=[]):`).
7. **No commented-out code.** Delete it. Git has history.
8. **No bare `except:`.** Always catch specific exceptions.
9. **No nested functions deeper than one level.**
10. **No classes that are just function wrappers.** Use plain functions unless holding state.
11. **No `# TODO` without context.** Write `# TODO(username): description` or remove it.
12. **No relative imports.** Always use `from refcheck.models.reference import Reference`.

---

## Naming Conventions

```python
# Files: snake_case, descriptive noun or verb_noun
doi_matcher.py              # YES
utils2.py                   # NO
helpers.py                  # NO (too vague)
misc.py                     # NO

# Functions: snake_case, verb_noun
def extract_references(docx_path: Path) -> list[Reference]:    # YES
def process(data):                                              # NO
def do_stuff():                                                 # NO

# Classes: PascalCase, noun (only when holding state)
class PipelineState:        # YES (holds state)
class ReferenceResolver:    # YES (holds API clients)
class Processor:            # NO (too vague)
class Utils:                # NO (never)

# Constants: UPPER_SNAKE_CASE
MAX_RETRY_ATTEMPTS = 3
DOI_PATTERN = re.compile(r"10\.\d{4,}/\S+")
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

# Type aliases: PascalCase
ReferenceId = int
Confidence = float
Verdict = Literal["supported", "partially_supported", "not_supported", "contradicted", "cannot_verify"]
```

---

## Function Design

Every public function follows this pattern:

```python
def match_by_doi(
    reference: Reference,
    uploaded_pdfs: list[UploadedPDF],
) -> MatchResult | None:
    """Try to match a reference to an uploaded PDF using DOI.

    Returns None if reference has no DOI or no PDF matches.
    """
    if not reference.doi:
        return None

    normalized = normalize_doi(reference.doi)
    for pdf in uploaded_pdfs:
        if pdf.doi and normalize_doi(pdf.doi) == normalized:
            return MatchResult(
                reference=reference,
                pdf=pdf,
                confidence=1.0,
                method="doi_exact",
            )
    return None
```

Rules:
- Type hints on ALL parameters and return type
- Docstring explains WHY, not WHAT (one line for simple functions)
- Maximum 30 lines of body
- Single responsibility — does one thing
- No side effects unless explicitly named (e.g., `save_`, `update_`, `delete_`)

---

## Import Order

```python
# 1. Standard library
import json
import logging
from pathlib import Path

# 2. Third-party
import httpx
from pydantic import BaseModel

# 3. Local (absolute imports only)
from refcheck.models.reference import Reference
from refcheck.llm.client import call_llm
```

Blank line between each group. Alphabetical within each group.

---

## Error Handling

```python
# Custom exceptions per domain — defined in each stage's __init__.py
class ReferenceNotFoundError(Exception):
    """Reference could not be found in any academic database."""

class LLMResponseInvalidError(Exception):
    """LLM returned unparseable or schema-invalid output."""

class PDFExtractionError(Exception):
    """PDF text could not be extracted."""

# Always catch specific, always distinguish failure modes
try:
    paper = await crossref_client.get_by_doi(doi)
except httpx.TimeoutException:
    logger.warning("CrossRef timeout for DOI %s", doi)
    return ResolutionResult(status="timeout", source="crossref")
except httpx.HTTPStatusError as e:
    if e.response.status_code == 404:
        return ResolutionResult(status="not_found", source="crossref")
    raise  # Re-raise unexpected HTTP errors
```

**Cardinal rule:** Never conflate "couldn't check" with "checked and failed."

---

## Pydantic Model Rules

```python
# Models live in src/refcheck/models/ — one file per domain concept
# Models are the contract between pipeline stages

class Reference(BaseModel):
    """A single bibliographic reference from the manuscript."""
    id: int
    raw_text: str
    title: str
    authors: list[str] = []
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    pmid: str | None = None           # PubMed ID — biomedical priority

    # Status fields (populated as pipeline progresses)
    source_status: Literal["pending", "found", "not_found", "api_error"] = "pending"
    pdf_path: Path | None = None
    pdf_source: Literal["user_upload", "open_access", "not_available"] | None = None
```

Rules:
- Use `|` union syntax, not `Optional[]`
- Provide defaults for fields populated later in the pipeline
- Use `Literal` for enums with few values, `enum.Enum` for larger sets
- Frozen models (`model_config = ConfigDict(frozen=True)`) for immutable data

---

## LLM Integration Pattern

```python
# NEVER do this:
response = client.messages.create(
    model="claude-sonnet-4-5-20250514",
    messages=[{"role": "user", "content": f"Verify: {claim}"}]
)

# ALWAYS do this:
from refcheck.llm.client import call_llm
from refcheck.models.verification import VerificationResult

result = await call_llm(
    template="grounded_verification",      # → loads prompts/grounded_verification.md
    variables={"claim": claim, "source_text": source_text},
    output_model=VerificationResult,       # Pydantic validation
    model="claude-sonnet-4-5-20250514",
)
```

The `call_llm` function handles: template rendering, API call, JSON parsing, Pydantic validation, retry on failure, logging.

---

## File Size & Splitting Guidelines

| If a file is... | Then... |
|-----------------|---------|
| Under 100 lines | Fine as-is |
| 100-200 lines | Consider splitting if it has 2+ responsibilities |
| Over 200 lines | Must split. Find the seam. |

**How to split:** Group by operation, not by type. Keep related code together.

```
# BAD: split by code type
models.py       (all models)
utils.py        (all helpers)
services.py     (all logic)

# GOOD: split by domain
stages/match_pdfs/
    doi_matcher.py       (DOI matching logic + its helpers)
    title_matcher.py     (fuzzy matching logic + its helpers)
    scorer.py            (confidence scoring)
```

---

## Comment Rules

```python
# Comments explain WHY, never WHAT
# BAD:
x = x + 1  # increment x

# GOOD:
x = x + 1  # CrossRef returns 0-indexed pages, our model uses 1-indexed

# Docstrings on public functions only (private functions use clear naming)
# BAD: docstring on a 3-line private helper
def _normalize(s: str) -> str:
    """Normalize a string by lowering case and stripping whitespace."""
    return s.lower().strip()

# GOOD: the name says it all
def _normalize_for_comparison(s: str) -> str:
    return s.lower().strip()
```

---

## Test Standards

```python
# Test file mirrors source file
# src/refcheck/stages/match_pdfs/doi_matcher.py
# → tests/unit/test_doi_matcher.py

# Test naming: test_{what}_{scenario}_{expected}
def test_doi_matcher_exact_match_returns_confidence_1():
    ...

def test_doi_matcher_no_doi_returns_none():
    ...

def test_doi_matcher_normalized_doi_matches():
    ...

# Every test has: Arrange → Act → Assert (no more)
def test_title_matcher_fuzzy_match_above_threshold():
    # Arrange
    reference = Reference(id=1, title="Effect of Drug X on Mortality", ...)
    pdf = UploadedPDF(extracted_title="Effects of Drug-X on Mortality Rates", ...)

    # Act
    result = match_by_title(reference, [pdf])

    # Assert
    assert result is not None
    assert result.confidence >= 0.85
    assert result.match_method == "title_fuzzy"
```
