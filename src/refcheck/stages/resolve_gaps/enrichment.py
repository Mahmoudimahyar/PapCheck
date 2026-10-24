"""Fill abstracts and retraction status for references with a PMID/DOI.

Abstract preference: PubMed (labelled parts joined) > Semantic Scholar >
Europe PMC (HTML stripped) > CrossRef (JATS stripped). A stub (abstract_quality:
under 300 characters, one sentence, or the title) counts as missing: the next
source is tried, and a stored stub is replaced by a full abstract of the
reference's own record. Retraction status comes from the same PubMed and
CrossRef records, so the retraction check costs no extra requests. The same
records repair garbled parsed titles (title_repair). All lookups are batched
where the API allows it and cached in the API cache.
"""

import logging

import httpx

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.abstract_quality import choose_abstract, judgeable_abstract
from refcheck.stages.resolve_gaps.doi_records import (
    CrossrefRecord,
    fetch_crossref_records,
    fetch_s2_abstracts,
)
from refcheck.stages.resolve_gaps.europepmc_client import (
    europepmc_key,
    fetch_europepmc_abstracts,
)
from refcheck.stages.resolve_gaps.pubmed_batch import (
    PubMedRecord,
    clean_pmid,
    fetch_pubmed_records,
)
from refcheck.stages.resolve_gaps.retraction_parsing import most_severe
from refcheck.stages.resolve_gaps.title_repair import title_repair_update
from refcheck.utils.doi import normalize_doi

logger = logging.getLogger(__name__)


async def enrich_references(
    refs: list[Reference], client: httpx.AsyncClient,
) -> list[Reference]:
    """Return references with abstracts / retraction status filled in."""
    pubmed = await fetch_pubmed_records(
        [r.pmid for r in refs if r.pmid], client,
    )
    crossref = await fetch_crossref_records(
        [r.doi for r in refs if r.doi], client,
    )

    def _pm(ref: Reference) -> PubMedRecord | None:
        return pubmed.get(clean_pmid(ref.pmid))

    def _cr(ref: Reference) -> CrossrefRecord | None:
        return crossref.get(normalize_doi(ref.doi)) if ref.doi else None

    def _lacks(ref: Reference, *found: str) -> bool:
        texts = (ref.abstract_text or "", *found)
        return not any(judgeable_abstract(t, ref.title) for t in texts)

    s2_needed = [r.doi for r in refs if r.doi and _lacks(r, _abstract_of(_pm(r)))]
    s2 = await fetch_s2_abstracts(s2_needed, client) if s2_needed else {}

    def _s2(ref: Reference) -> str:
        return s2.get(normalize_doi(ref.doi), "") if ref.doi else ""

    epmc_needed = [
        europepmc_key(r.doi, r.pmid) for r in refs
        if _lacks(r, _abstract_of(_pm(r)), _s2(r), _crossref_abstract(_cr(r)))
    ]
    epmc_keys = [k for k in epmc_needed if k]
    epmc = await fetch_europepmc_abstracts(epmc_keys, client) if epmc_keys else {}

    enriched: list[Reference] = []
    for ref in refs:
        epmc_text = epmc.get(europepmc_key(ref.doi, ref.pmid), "")
        enriched.append(apply_records(ref, _pm(ref), _cr(ref), _s2(ref), epmc_text))
    filled = sum(
        1 for old, new in zip(refs, enriched, strict=True)
        if new.abstract_text != old.abstract_text
    )
    logger.info("Enrichment: %d abstracts added or replaced for %d references",
                filled, len(refs))
    return enriched


def apply_records(
    ref: Reference,
    pm: PubMedRecord | None,
    cr: CrossrefRecord | None,
    s2_abstract: str,
    europepmc_abstract: str = "",
) -> Reference:
    """Merge fetched records into a reference (a full abstract is never
    overwritten, a stub only by a full one; replaces a garbled title with the
    record's, see title_repair)."""
    updates: dict[str, object] = {}
    choice = choose_abstract(ref.abstract_text, ref.title, [
        ("pubmed", _abstract_of(pm)),
        ("semantic_scholar", s2_abstract),
        ("europepmc", europepmc_abstract),
        ("crossref", _crossref_abstract(cr)),
    ])
    if choice is not None:
        updates["abstract_source"], updates["abstract_text"] = choice

    statuses = [rec.retraction for rec in (pm, cr) if rec is not None]
    if statuses:
        status = most_severe(statuses)
        updates["retraction_status"] = status.status
        updates["retraction_detail"] = status.detail

    if pm is not None:
        if pm.pmc_id and not ref.pmc_id:
            updates["pmc_id"] = pm.pmc_id
        if pm.doi and not ref.doi:
            updates["doi"] = pm.doi
    # cr was fetched by the reference's DOI and pm by its PMID: their titles are
    # authoritative and replace a garbled parsed title (raw_text is kept).
    updates.update(title_repair_update(
        ref,
        crossref_title=cr.title if cr else "",
        pubmed_title=pm.title if pm else "",
        pubmed_doi=pm.doi if pm else "",
    ))
    return ref.model_copy(update=updates) if updates else ref


def _abstract_of(record: PubMedRecord | None) -> str:
    return record.abstract if record is not None else ""


def _crossref_abstract(record: CrossrefRecord | None) -> str:
    return record.abstract if record is not None else ""
