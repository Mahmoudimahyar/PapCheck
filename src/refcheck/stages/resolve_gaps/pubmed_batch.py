"""Batched, cached PubMed efetch -> abstract + retraction per PMID."""

import logging
import os

import httpx
from pydantic import BaseModel, Field

from refcheck.stages.resolve_gaps.http_retry import send_with_backoff
from refcheck.stages.resolve_gaps.markup import (
    extract_tag,
    parse_pubmed_abstract,
    parse_pubmed_year,
    split_pubmed_articles,
)
from refcheck.stages.resolve_gaps.record_cache import load_record, store_record
from refcheck.stages.resolve_gaps.retraction_parsing import (
    RetractionStatus,
    parse_pubmed_retraction,
)

logger = logging.getLogger(__name__)

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_BATCH_SIZE = 100
_CACHE_KIND = "pubmed_record_v1"
_TIMEOUT = 30.0


class PubMedRecord(BaseModel):
    """The parts of a PubMed article the pipeline needs."""

    pmid: str
    title: str = ""
    year: int | None = None
    doi: str = ""
    pmc_id: str = ""
    abstract: str = ""
    retraction: RetractionStatus = Field(default_factory=RetractionStatus)


def clean_pmid(pmid: str | None) -> str:
    """Digits-only PMID ("" if it is not a plausible PMID)."""
    digits = "".join(ch for ch in (pmid or "") if ch.isdigit())
    return digits if 1 <= len(digits) <= 9 else ""


async def fetch_pubmed_records(
    pmids: list[str], client: httpx.AsyncClient,
) -> dict[str, PubMedRecord]:
    """Fetch PubMed records for PMIDs (cache first, then efetch batches)."""
    records: dict[str, PubMedRecord] = {}
    missing: list[str] = []
    for pmid in dict.fromkeys(clean_pmid(p) for p in pmids):
        if not pmid:
            continue
        cached = load_record(_CACHE_KIND, pmid, PubMedRecord)
        if cached is not None:
            records[pmid] = cached
        else:
            missing.append(pmid)

    for start in range(0, len(missing), _BATCH_SIZE):
        batch = missing[start:start + _BATCH_SIZE]
        xml_text = await _efetch(batch, client)
        if xml_text is None:
            continue
        for pmid, article in split_pubmed_articles(xml_text).items():
            record = parse_pubmed_record(pmid, article)
            store_record(_CACHE_KIND, pmid, record)
            records[pmid] = record
    return records


def parse_pubmed_record(pmid: str, article_xml: str) -> PubMedRecord:
    """Build a PubMedRecord from one <PubmedArticle> element."""
    return PubMedRecord(
        pmid=pmid,
        title=extract_tag(article_xml, "ArticleTitle"),
        year=parse_pubmed_year(article_xml),
        doi=extract_tag(article_xml, "ArticleId", 'IdType="doi"'),
        pmc_id=extract_tag(article_xml, "ArticleId", 'IdType="pmc"'),
        abstract=parse_pubmed_abstract(article_xml),
        retraction=parse_pubmed_retraction(article_xml),
    )


async def _efetch(pmids: list[str], client: httpx.AsyncClient) -> str | None:
    """POST one efetch request; None on API failure (logged)."""
    data = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    api_key = os.environ.get("NCBI_API_KEY", "")
    if api_key:
        data["api_key"] = api_key
    try:
        resp = await send_with_backoff(
            lambda: client.post(EFETCH_URL, data=data, timeout=_TIMEOUT),
        )
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as exc:
        logger.warning("PubMed efetch failed for %d PMIDs: %s", len(pmids), exc)
        return None
