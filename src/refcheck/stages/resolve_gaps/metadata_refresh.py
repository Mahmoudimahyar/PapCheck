"""Re-run the abstract and free-full-text lookups for one reference.

Used by POST .../references/{n}/refresh-metadata: the same enrichment as the
resolve stage (a stub abstract is replaced by a full one from PubMed, Semantic
Scholar, Europe PMC or CrossRef) plus the OpenAlex hint, looked up whether or
not the reference has a PDF (the user asked). Only the abstract, the PMC id
and the hint are reported as changes; lookups are cached like the stage's
(misses for a day, API failures not at all).
"""

import logging

import httpx
from pydantic import BaseModel, Field

from refcheck.models.open_access import (
    OA_FIELDS,
    OpenAccessHint,
    ReferenceWithAccess,
    access_hint_of,
    with_access_hint,
)
from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.enrichment import enrich_references
from refcheck.stages.resolve_gaps.oa_hints import fetch_oa_hint

logger = logging.getLogger(__name__)

REFRESHED_FIELDS: tuple[str, ...] = ("abstract_text", "abstract_source", "pmc_id", *OA_FIELDS)
_TIMEOUT = 15.0


class MetadataRefresh(BaseModel):
    """Outcome of refreshing one reference's metadata."""

    reference: ReferenceWithAccess
    changed_fields: list[str] = Field(default_factory=list)
    abstract_changed: bool = False
    previous_abstract_chars: int = 0
    open_access: OpenAccessHint = Field(default_factory=OpenAccessHint)

    def updates(self) -> dict[str, object]:
        """Changed fields and their new values (for the database / re-verification)."""
        return {name: getattr(self.reference, name) for name in self.changed_fields}


def new_client() -> httpx.AsyncClient:
    """HTTP client of a refresh (one reference: a handful of requests)."""
    return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)


async def refresh_metadata(
    ref: Reference, client: httpx.AsyncClient | None = None,
) -> MetadataRefresh:
    """Abstract + open-access lookups for `ref` (failures leave fields unchanged)."""
    if client is None:
        async with new_client() as own:
            return await refresh_metadata(ref, own)
    before = with_access_hint(ref, access_hint_of(ref))
    try:
        enriched = (await enrich_references([before], client))[0]
    except Exception as exc:  # enrichment is best-effort, as in the resolve stage
        logger.warning("Abstract refresh failed for ref %d: %s", ref.id, exc)
        enriched = before
    hint = await fetch_oa_hint(ref.doi, client) if ref.doi else None
    after = with_access_hint(enriched, hint) if hint is not None else \
        with_access_hint(enriched, access_hint_of(before))
    # Only the refreshed fields change (enrichment may also touch title / retraction).
    after = before.model_copy(update={n: getattr(after, n) for n in REFRESHED_FIELDS})
    changed = [n for n in REFRESHED_FIELDS if getattr(after, n) != getattr(before, n)]
    return MetadataRefresh(
        reference=after,
        changed_fields=changed,
        abstract_changed="abstract_text" in changed,
        previous_abstract_chars=len(before.abstract_text or ""),
        open_access=access_hint_of(after),
    )
