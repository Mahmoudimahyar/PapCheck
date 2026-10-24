"""Tests that Pydantic models are NEVER mutated via direct attribute assignment.

Root cause analysis:
    Pydantic V2 raises ValueError("X object has no field Y") when you do
    obj.field = value if the field doesn't exist on the model (e.g. stale
    bytecode loaded a version without the field). Using model_copy(update=...)
    is Pydantic-safe and side-effect-free. This suite validates that all
    model-producing code paths use model_copy instead of setattr.

These tests prevent the recurring bug:
    "CitationInstance" object has no field "paragraph_text"
"""

import ast
import pathlib
from collections.abc import Iterator

from refcheck.models.citation import CitationInstance, MissingCitation, VerificationUnit

# --------------------------------------------------------------------------- #
# Static analysis: scan source for direct setattr on Pydantic models          #
# --------------------------------------------------------------------------- #

_SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "refcheck"

# Files that are ALLOWED to use setattr (tests, debug endpoints)
_ALLOWED_FILES = frozenset({
    "tests",
    "conftest",
})


def _python_files() -> Iterator[pathlib.Path]:
    """Yield all .py files under src/refcheck/."""
    for p in _SRC_ROOT.rglob("*.py"):
        if any(skip in str(p) for skip in _ALLOWED_FILES):
            continue
        yield p


def _find_setattr_on_pydantic(filepath: pathlib.Path) -> list[tuple[int, str]]:
    """Find lines where a Pydantic model field is directly assigned.

    Looks for `obj.field = value` patterns on known Pydantic model types.
    Returns list of (line_number, line_text) tuples.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []
    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Attribute):
                continue
            # Skip class-level attributes (inside class body definitions)
            # We only care about instance mutations
            line_text = lines[node.lineno - 1].strip()
            # Skip type annotations, class definitions, self assignments
            if "self." in line_text:
                continue
            if line_text.startswith("#"):
                continue
            # Look for patterns like obj.paragraph_text = or obj.title =
            # that might be Pydantic mutations
            attr_name = target.attr
            if attr_name in _PYDANTIC_FIELDS_TO_WATCH:
                violations.append((node.lineno, line_text))

    return violations


# Fields that have caused bugs or are known Pydantic model fields
_PYDANTIC_FIELDS_TO_WATCH = frozenset({
    "paragraph_text", "sentence_text", "sentence_start", "sentence_end",
    "reference_id", "reference_title", "mapping_confidence", "mapping_method",
    "confidence", "category", "reason", "suggestion",
    "final_tier", "escalation_path",
    "repair_applied",
})


class TestNoDirectSetattr:
    """Scan source code to ensure no Pydantic models are mutated via setattr."""

    def test_no_setattr_in_detect_citations(self) -> None:
        """detect_citations module must not use direct setattr."""
        module_dir = _SRC_ROOT / "stages" / "detect_citations"
        violations: list[str] = []
        for fp in module_dir.glob("*.py"):
            if fp.name.startswith("test_"):
                continue
            hits = _find_setattr_on_pydantic(fp)
            for lineno, text in hits:
                violations.append(f"{fp.name}:{lineno}: {text}")
        assert not violations, (
            "Direct setattr on Pydantic fields found:\n"
            + "\n".join(violations)
        )

    def test_no_setattr_in_services(self) -> None:
        """Service layer must not use direct setattr on Pydantic models."""
        module_dir = _SRC_ROOT / "services"
        violations: list[str] = []
        for fp in module_dir.glob("*.py"):
            hits = _find_setattr_on_pydantic(fp)
            for lineno, text in hits:
                violations.append(f"{fp.name}:{lineno}: {text}")
        assert not violations, (
            "Direct setattr on Pydantic fields found:\n"
            + "\n".join(violations)
        )

    def test_no_setattr_in_llm(self) -> None:
        """LLM module must not use direct setattr on Pydantic models."""
        module_dir = _SRC_ROOT / "llm"
        violations: list[str] = []
        for fp in module_dir.glob("*.py"):
            hits = _find_setattr_on_pydantic(fp)
            for lineno, text in hits:
                violations.append(f"{fp.name}:{lineno}: {text}")
        assert not violations, (
            "Direct setattr on Pydantic fields found:\n"
            + "\n".join(violations)
        )


# --------------------------------------------------------------------------- #
# Runtime: verify model_copy works for all critical fields                     #
# --------------------------------------------------------------------------- #


class TestCitationInstanceModelCopy:
    """Verify model_copy works for all CitationInstance fields."""

    def test_model_copy_paragraph_text(self) -> None:
        cit = _make_citation()
        updated = cit.model_copy(update={"paragraph_text": "new para"})
        assert updated.paragraph_text == "new para"
        assert cit.paragraph_text == ""  # original unchanged

    def test_model_copy_sentence_text(self) -> None:
        cit = _make_citation()
        updated = cit.model_copy(update={"sentence_text": "new sent"})
        assert updated.sentence_text == "new sent"

    def test_model_copy_sentence_boundaries(self) -> None:
        cit = _make_citation()
        updated = cit.model_copy(update={
            "sentence_start": 10,
            "sentence_end": 50,
        })
        assert updated.sentence_start == 10
        assert updated.sentence_end == 50

    def test_model_copy_reference_mapping(self) -> None:
        cit = _make_citation()
        updated = cit.model_copy(update={
            "reference_id": 42,
            "reference_title": "A Great Paper",
            "mapping_confidence": 0.95,
            "mapping_method": "exact_author_year",
        })
        assert updated.reference_id == 42
        assert updated.reference_title == "A Great Paper"
        assert updated.mapping_confidence == 0.95
        assert updated.mapping_method == "exact_author_year"

    def test_model_copy_id(self) -> None:
        cit = _make_citation()
        updated = cit.model_copy(update={"id": 99})
        assert updated.id == 99

    def test_model_copy_preserves_other_fields(self) -> None:
        cit = CitationInstance(
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=5,
            char_start=10,
            char_end=13,
            section_heading="Methods",
            number=1,
        )
        updated = cit.model_copy(update={"paragraph_text": "test"})
        assert updated.paragraph_index == 5
        assert updated.section_heading == "Methods"
        assert updated.number == 1
        assert updated.raw_marker == "[1]"

    def test_model_copy_chain(self) -> None:
        """Multiple sequential model_copy calls all work."""
        cit = _make_citation()
        step1 = cit.model_copy(update={"paragraph_text": "para"})
        step2 = step1.model_copy(update={"sentence_text": "sent"})
        step3 = step2.model_copy(update={"reference_id": 7})
        assert step3.paragraph_text == "para"
        assert step3.sentence_text == "sent"
        assert step3.reference_id == 7


class TestVerificationUnitModelCopy:
    """Verify model_copy works for VerificationUnit."""

    def test_model_copy_id(self) -> None:
        unit = _make_unit()
        updated = unit.model_copy(update={"id": 42})
        assert updated.id == 42

    def test_model_copy_preserves_paragraph_text(self) -> None:
        unit = _make_unit()
        updated = unit.model_copy(update={"id": 1})
        assert updated.paragraph_text == "test paragraph"


class TestMissingCitationModelCopy:
    """Verify model_copy works for MissingCitation."""

    def test_model_copy_all_flagging_fields(self) -> None:
        mc = MissingCitation(
            sentence_text="Studies have shown X.",
            paragraph_index=0,
        )
        updated = mc.model_copy(update={
            "id": 1,
            "confidence": 0.8,
            "category": "attribution",
            "reason": "References other studies",
            "suggestion": "Add citation",
        })
        assert updated.id == 1
        assert updated.confidence == 0.8
        assert updated.category == "attribution"


# --------------------------------------------------------------------------- #
# Runtime: verify _verify_citation_model guard works                          #
# --------------------------------------------------------------------------- #


class TestVerifyCitationModelGuard:
    """Test the runtime guard that catches stale models."""

    def test_guard_passes_with_current_model(self) -> None:
        from refcheck.stages.detect_citations.detector import (
            _verify_citation_model,
        )
        _verify_citation_model()  # Should not raise

    def test_guard_checks_required_fields(self) -> None:
        from refcheck.stages.detect_citations.detector import _REQUIRED_FIELDS

        for field in _REQUIRED_FIELDS:
            assert field in CitationInstance.model_fields, (
                f"Required field '{field}' missing from CitationInstance"
            )


# --------------------------------------------------------------------------- #
# Runtime: reference_mapper uses model_copy (no in-place mutation)            #
# --------------------------------------------------------------------------- #


class TestReferenceMapperModelCopy:
    """reference_mapper must return NEW objects, not mutate in-place."""

    def test_map_returns_new_list(self) -> None:
        from refcheck.models.reference import Reference
        from refcheck.stages.detect_citations.reference_mapper import (
            map_citations_to_references,
        )

        cit = CitationInstance(
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=0,
            char_end=3,
            number=1,
        )
        ref = Reference(id=1, raw_text="Author. Title. 2020.", title="Title")
        original_id = id(cit)

        result = map_citations_to_references([cit], [ref])
        assert len(result) == 1
        assert result[0].reference_id == 1
        assert result[0].reference_title == "Title"
        # Must be a NEW object (model_copy), not the same object mutated
        assert id(result[0]) != original_id

    def test_map_unresolved_returns_new_object(self) -> None:
        from refcheck.stages.detect_citations.reference_mapper import (
            map_citations_to_references,
        )

        cit = CitationInstance(
            raw_marker="(Unknown, 2099)",
            style="author_year_parenthetical",
            paragraph_index=0,
            char_start=0,
            char_end=20,
            authors=["Unknown"],
            year="2099",
        )
        original_id = id(cit)
        result = map_citations_to_references([cit], [])
        assert len(result) == 1
        assert result[0].mapping_method == "unresolved"
        assert id(result[0]) != original_id


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_citation() -> CitationInstance:
    return CitationInstance(
        raw_marker="[1]",
        style="numbered_bracket",
        paragraph_index=0,
        char_start=0,
        char_end=3,
    )


def _make_unit() -> VerificationUnit:
    return VerificationUnit(
        manuscript_text="test sentence",
        paragraph_text="test paragraph",
        scope_text="test scope",
        citation_marker="[1]",
        reference_id=1,
    )
