"""Parse retraction / correction signals from CrossRef and PubMed records."""

from typing import Literal

from pydantic import BaseModel


class RetractionStatus(BaseModel):
    """Retraction check result for a single reference."""

    status: Literal[
        "ok", "retracted", "corrected", "expression_of_concern", "unknown"
    ] = "unknown"
    detail: str = ""
    source: str = ""
    retraction_doi: str | None = None
    retraction_date: str | None = None


_SEVERITY = {
    "retracted": 4,
    "expression_of_concern": 3,
    "corrected": 2,
    "ok": 1,
    "unknown": 0,
}

_PM_RETRACTED = ('RefType="RetractionIn"', ">retracted publication<")
_PM_CONCERN = ('RefType="ExpressionOfConcernIn"',)
_PM_ERRATUM = ('RefType="ErratumIn"', ">published erratum<")


def most_severe(statuses: list[RetractionStatus]) -> RetractionStatus:
    """The most severe of several retraction statuses (unknown if none)."""
    if not statuses:
        return RetractionStatus(status="unknown")
    return max(statuses, key=lambda r: _SEVERITY.get(r.status, 0))


def parse_crossref_retraction(
    msg: dict[str, object], doi: str,
) -> RetractionStatus:
    """Parse CrossRef updated-by / update-to fields for retraction info.

    "updated-by" (Retraction Watch integration) sits on the original work;
    "update-to" sits on a notice, i.e. the cited DOI is itself a notice.
    """
    updates: list[object] = []
    for field in ("updated-by", "update-to"):
        value = msg.get(field)
        if isinstance(value, list):
            updates.extend(value)

    found: list[RetractionStatus] = [RetractionStatus(status="ok", source="crossref")]
    for update in updates:
        if isinstance(update, dict):
            status = _classify_crossref_update(update)
            if status is not None:
                found.append(status)
    return most_severe(found)


def _classify_crossref_update(update: dict[str, object]) -> RetractionStatus | None:
    """Map one CrossRef update entry to a status (None if irrelevant)."""
    update_type = str(update.get("type", "")).lower()
    kind: Literal["retracted", "corrected", "expression_of_concern"]
    if "retraction" in update_type or "withdrawal" in update_type:
        kind = "retracted"
    elif "concern" in update_type:
        kind = "expression_of_concern"
    elif "correction" in update_type or "erratum" in update_type:
        kind = "corrected"
    else:
        return None
    return RetractionStatus(
        status=kind,
        detail=str(update.get("label", "")),
        source="crossref",
        retraction_doi=str(update.get("DOI", "")),
        retraction_date=_extract_crossref_date(update),
    )


def _extract_crossref_date(update: dict[str, object]) -> str:
    """Extract date string from CrossRef update entry."""
    date_parts = update.get("updated", {})
    if isinstance(date_parts, dict):
        parts = date_parts.get("date-parts", [[]])
        if isinstance(parts, list) and parts and isinstance(parts[0], list):
            return "-".join(str(p) for p in parts[0])
    return ""


def parse_pubmed_retraction(xml_text: str) -> RetractionStatus:
    """Parse PubMed XML for retraction-related publication types.

    Uses structured markers (PublicationType, CommentsCorrections RefType)
    instead of free text, which fires on abstracts mentioning "erratum".
    """
    low = xml_text.lower()

    def _has(markers: tuple[str, ...]) -> bool:
        return any(m.lower() in low for m in markers)

    if _has(_PM_RETRACTED):
        return RetractionStatus(
            status="retracted", detail="Retracted Publication", source="pubmed",
        )
    if _has(_PM_CONCERN):
        return RetractionStatus(
            status="expression_of_concern",
            detail="Expression of Concern", source="pubmed",
        )
    if _has(_PM_ERRATUM):
        return RetractionStatus(
            status="corrected", detail="Published Erratum", source="pubmed",
        )
    return RetractionStatus(status="ok", source="pubmed")
