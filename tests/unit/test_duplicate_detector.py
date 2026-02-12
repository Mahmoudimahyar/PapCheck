"""Tests for duplicate reference detection (V2)."""

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.duplicate_detector import detect_duplicates


class TestDuplicateDetector:
    def test_same_doi_detected(self) -> None:
        """Same DOI -> duplicate detected."""
        refs = [
            Reference(id=1, title="Paper A", doi="10.1234/test"),
            Reference(id=2, title="Paper A variant", doi="10.1234/test"),
        ]
        updated, warnings = detect_duplicates(refs)
        assert updated[1].duplicate_of == 1
        assert len(warnings) == 1

    def test_similar_titles_detected(self) -> None:
        """Very similar titles -> duplicate detected."""
        refs = [
            Reference(
                id=1,
                title="Effect of Drug X on Mortality in Elderly Patients",
            ),
            Reference(
                id=2,
                title="Effects of Drug X on Mortality in Elderly Patients",
            ),
        ]
        updated, warnings = detect_duplicates(refs)
        assert updated[1].duplicate_of == 1

    def test_different_refs_no_false_duplicate(self) -> None:
        """Different references -> no false positive."""
        refs = [
            Reference(
                id=1,
                title="Drug X for Cancer Treatment",
                doi="10.1234/a",
            ),
            Reference(
                id=2,
                title="Gene Therapy for Heart Disease",
                doi="10.5678/b",
            ),
        ]
        updated, warnings = detect_duplicates(refs)
        assert all(r.duplicate_of is None for r in updated)
        assert len(warnings) == 0

    def test_same_author_year_similar_title(self) -> None:
        """Same first author + year + similar title -> duplicate."""
        refs = [
            Reference(
                id=1,
                title="Novel Approach to Drug Delivery",
                authors=["Smith J"],
                year=2020,
            ),
            Reference(
                id=2,
                title="A Novel Approach to Drug Delivery Systems",
                authors=["Smith J"],
                year=2020,
            ),
        ]
        updated, warnings = detect_duplicates(refs)
        assert updated[1].duplicate_of == 1
