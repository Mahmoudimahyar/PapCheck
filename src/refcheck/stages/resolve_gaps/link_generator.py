"""Generate external links for unresolved references."""

from urllib.parse import quote_plus


def generate_reference_links(
    doi: str | None,
    pmid: str | None,
    title: str | None,
    pmc_id: str | None = None,
    journal_url: str | None = None,
) -> dict[str, str | None]:
    """Generate external links for a reference.

    Returns dict with doi_url, pubmed_url, scholar_url, pmc_url,
    journal_url. Only populated when the corresponding identifier
    is available.
    """
    links: dict[str, str | None] = {
        "doi_url": None,
        "pubmed_url": None,
        "scholar_url": None,
        "pmc_url": None,
        "journal_url": None,
    }

    if doi:
        links["doi_url"] = f"https://doi.org/{doi}"
    if pmid:
        links["pubmed_url"] = (
            f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        )
    if title:
        encoded = quote_plus(title[:200])
        links["scholar_url"] = (
            f"https://scholar.google.com/scholar?q={encoded}"
        )
    if pmc_id:
        clean_id = pmc_id if pmc_id.startswith("PMC") else f"PMC{pmc_id}"
        links["pmc_url"] = (
            f"https://pmc.ncbi.nlm.nih.gov/articles/{clean_id}/"
        )
    if journal_url:
        links["journal_url"] = journal_url

    return links
