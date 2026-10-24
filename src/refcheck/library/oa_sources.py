"""Where an open-access PDF of a reference may be downloaded (Unpaywall, Europe PMC, PMC).

Unpaywall is asked by DOI with the contact e-mail (oa_settings); Europe PMC by DOI,
else PMID / PMCID, keeping only its open-access ("OA") or free ("F") PDF links and,
for an open-access article with a PMCID, the Europe PMC and PMC PDF renderings. A
Europe PMC record with another DOI is ignored. Only http(s) links are returned.
Every failure (network, HTTP status, JSON) yields no links, never an exception.
"""

import logging
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from refcheck.models.reference import Reference
from refcheck.utils.doi import normalize_doi

logger = logging.getLogger(__name__)

UNPAYWALL_API = "https://api.unpaywall.org/v2/"
EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_FREE_CODES = frozenset({"OA", "F"})

OaSource = Literal["unpaywall", "europepmc", "pmc"]


class OaLink(BaseModel):
    """One candidate PDF URL and the service that named it."""

    url: str
    source: OaSource


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _UnpaywallLocation(_Lenient):
    url_for_pdf: str | None = None


class _UnpaywallRecord(_Lenient):
    best_oa_location: _UnpaywallLocation | None = None
    oa_locations: list[_UnpaywallLocation] = Field(default_factory=list)


class _EpmcUrl(_Lenient):
    url: str = ""
    style: str = Field(default="", alias="documentStyle")
    code: str = Field(default="", alias="availabilityCode")


class _EpmcUrls(_Lenient):
    urls: list[_EpmcUrl] = Field(default_factory=list, alias="fullTextUrl")


class _EpmcResult(_Lenient):
    doi: str | None = None
    pmcid: str | None = None
    open_access: str = Field(default="N", alias="isOpenAccess")
    url_list: _EpmcUrls | None = Field(default=None, alias="fullTextUrlList")


class _EpmcResults(_Lenient):
    result: list[_EpmcResult] = Field(default_factory=list)


class _EpmcResponse(_Lenient):
    result_list: _EpmcResults = Field(default_factory=_EpmcResults, alias="resultList")


def oa_links(client: httpx.Client, ref: Reference, contact_email: str) -> list[OaLink]:
    """Candidate open-access PDF URLs for `ref`, best first, without duplicates."""
    doi = normalize_doi(ref.doi or "")
    links: list[OaLink] = []
    if doi and contact_email:
        links += _unpaywall(client, doi, contact_email)
    links += _europe_pmc(client, doi, ref.pmid, ref.pmc_id)
    seen: set[str] = set()
    unique: list[OaLink] = []
    for link in links:
        if link.url not in seen and link.url.lower().startswith(("https://", "http://")):
            seen.add(link.url)
            unique.append(link)
    return unique


def _unpaywall(client: httpx.Client, doi: str, email: str) -> list[OaLink]:
    record = _get_json(client, UNPAYWALL_API + quote(doi, safe="/"), {"email": email},
                       _UnpaywallRecord)
    if not isinstance(record, _UnpaywallRecord):
        return []
    locations = [record.best_oa_location, *record.oa_locations]
    return [OaLink(url=loc.url_for_pdf, source="unpaywall")
            for loc in locations if loc is not None and loc.url_for_pdf]


def _europe_pmc(
    client: httpx.Client, doi: str, pmid: str | None, pmc_id: str | None,
) -> list[OaLink]:
    query = f'DOI:"{doi}"' if doi else (f"EXT_ID:{pmid} AND SRC:MED" if pmid else
                                       (f"PMCID:{pmc_id}" if pmc_id else ""))
    if not query:
        return []
    params = {"query": query, "resultType": "core", "format": "json", "pageSize": "1"}
    response = _get_json(client, EUROPE_PMC_SEARCH, params, _EpmcResponse)
    if not isinstance(response, _EpmcResponse) or not response.result_list.result:
        return _pmc_links(pmc_id)
    hit = response.result_list.result[0]
    if doi and hit.doi and normalize_doi(hit.doi) != doi:
        return _pmc_links(pmc_id)  # another article: its links say nothing about this one
    urls = hit.url_list.urls if hit.url_list else []
    links = [OaLink(url=u.url, source="europepmc") for u in urls
             if u.style.lower() == "pdf" and u.code.upper() in _FREE_CODES and u.url]
    if hit.open_access.upper() == "Y" and hit.pmcid:
        links += _pmc_links(hit.pmcid)
    return links + _pmc_links(pmc_id)


def _pmc_links(pmc_id: str | None) -> list[OaLink]:
    """Europe PMC and PMC renderings of a PMC article's PDF."""
    if not pmc_id:
        return []
    pmc = pmc_id if pmc_id.upper().startswith("PMC") else f"PMC{pmc_id}"
    return [OaLink(url=f"https://europepmc.org/articles/{pmc}?pdf=render", source="europepmc"),
            OaLink(url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc}/pdf/", source="pmc")]


def _get_json(
    client: httpx.Client, url: str, params: dict[str, str],
    model: type[_UnpaywallRecord] | type[_EpmcResponse],
) -> _UnpaywallRecord | _EpmcResponse | None:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return model.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        # ValueError: a body that is not JSON (ValidationError is one too)
        logger.info("OA lookup failed (%s): %s", url.split("?")[0], type(exc).__name__)
        return None
