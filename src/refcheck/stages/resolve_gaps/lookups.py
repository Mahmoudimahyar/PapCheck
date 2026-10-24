"""Per-reference metadata lookups (PubMed, CrossRef, Semantic Scholar).

Identifier lookups (PMID, DOI) are trusted; title-search hits must pass
the title-similarity guard, otherwise they are treated as not found.
Each lookup returns a dict of Reference field updates, or None.
"""

import httpx

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.crossref_client import (
    search_by_doi as crossref_by_doi,
)
from refcheck.stages.resolve_gaps.crossref_client import (
    search_by_title as crossref_by_title,
)
from refcheck.stages.resolve_gaps.pubmed_client import (
    search_by_pmid as pubmed_by_pmid,
)
from refcheck.stages.resolve_gaps.pubmed_client import (
    search_by_title as pubmed_by_title,
)
from refcheck.stages.resolve_gaps.semantic_scholar_client import (
    search_by_title as s2_by_title,
)
from refcheck.stages.resolve_gaps.title_guard import accept_search_hit

Updates = dict[str, object]


def _abstract_update(ref: Reference, abstract: str, source: str) -> Updates:
    """Abstract fields, only when the reference has none yet."""
    if abstract and not ref.abstract_text:
        return {"abstract_text": abstract, "abstract_source": source}
    return {}


async def try_pubmed(ref: Reference, client: httpx.AsyncClient) -> Updates | None:
    """PubMed lookup by PMID, else by (guarded) title search."""
    if ref.pmid:
        result = await pubmed_by_pmid(ref.pmid, client)
    elif ref.title:
        result = await pubmed_by_title(ref.title, client)
        if result.found and not accept_search_hit(
            ref.title, ref.doi, result.title, result.doi, "PubMed",
        ):
            return None
    else:
        return None

    if result.found:
        updates: Updates = {"source_status": "found", "pmid": result.pmid or ref.pmid}
        if result.pmc_id:
            updates["pmc_id"] = result.pmc_id
        if result.doi and not ref.doi:
            updates["doi"] = result.doi
        updates.update(_abstract_update(ref, result.abstract, "pubmed"))
        return updates
    if result.status == "api_error":
        return {"source_status": "api_error"}
    return None


async def try_crossref(ref: Reference, client: httpx.AsyncClient) -> Updates | None:
    """CrossRef lookup by DOI, else by (guarded) title search."""
    if ref.doi:
        result = await crossref_by_doi(ref.doi, client)
    elif ref.title:
        result = await crossref_by_title(ref.title, ref.authors, client)
        if result.found and not accept_search_hit(
            ref.title, ref.doi, result.title, result.doi, "CrossRef",
        ):
            return None
    else:
        return None

    if result.found:
        updates: Updates = {
            "source_status": "found",
            "doi": result.doi or ref.doi,
            "journal_url": result.url,
        }
        updates.update(_abstract_update(ref, result.abstract, "crossref"))
        return updates
    if result.status == "api_error":
        return {"source_status": "api_error"}
    return None


async def try_semantic_scholar(
    ref: Reference, client: httpx.AsyncClient,
) -> Updates | None:
    """Semantic Scholar (guarded) title search."""
    if not ref.title:
        return None
    result = await s2_by_title(ref.title, client)
    if result.found:
        if not accept_search_hit(
            ref.title, ref.doi, result.title, result.doi, "Semantic Scholar",
        ):
            return None
        updates: Updates = {"source_status": "found", "doi": result.doi or ref.doi}
        if result.pmid and not ref.pmid:
            updates["pmid"] = result.pmid
        updates.update(_abstract_update(ref, result.abstract, "semantic_scholar"))
        return updates
    if result.status == "api_error":
        return {"source_status": "api_error"}
    return None
