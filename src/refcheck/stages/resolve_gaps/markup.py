"""Parse titles, years and abstracts out of PubMed XML and CrossRef JATS."""

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
# Inline formatting tags vanish without a space ("(<i>p</i> < 0.05)").
_INLINE_TAG_RE = re.compile(
    r"</?(?:jats:)?(?:i|b|u|em|strong|sup|sub|italic|bold|sc|underline)\b[^>]*>",
)
_SPACE_RE = re.compile(r"\s+")
_JATS_TITLE_RE = re.compile(r"<jats:title[^>]*>(.*?)</jats:title>", re.DOTALL)
_ABSTRACT_BLOCK_RE = re.compile(r"<Abstract\b[^>]*>(.*?)</Abstract>", re.DOTALL)
_ABSTRACT_TEXT_RE = re.compile(
    r"<AbstractText\b([^>]*)>(.*?)</AbstractText>", re.DOTALL,
)
_LABEL_RE = re.compile(r'\bLabel="([^"]*)"')
_ARTICLE_RE = re.compile(r"<PubmedArticle\b.*?</PubmedArticle>", re.DOTALL)
_PMID_RE = re.compile(r"<PMID\b[^>]*>(\d+)</PMID>")
_PUBDATE_RE = re.compile(r"<PubDate>(.*?)</PubDate>", re.DOTALL)
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def strip_markup(text: str) -> str:
    """Remove XML/HTML tags and entities, collapse whitespace."""
    cleaned = _TAG_RE.sub(" ", _INLINE_TAG_RE.sub("", text or ""))
    cleaned = html.unescape(cleaned)
    return _SPACE_RE.sub(" ", cleaned).strip()


def strip_jats(text: str) -> str:
    """Plain text from a CrossRef JATS abstract.

    Section titles become "Title: " prefixes; a bare "Abstract" title is
    dropped because it carries no content.
    """

    def _title(match: re.Match[str]) -> str:
        title = strip_markup(match.group(1))
        if not title or title.lower().rstrip(":") == "abstract":
            return " "
        return f" {title}: "

    return strip_markup(_JATS_TITLE_RE.sub(_title, text or ""))


def extract_tag(xml: str, tag: str, attrs: str = "") -> str:
    """Inner text of the first <tag ...attrs...> element ("" if absent)."""
    pattern = rf"<{tag}\b[^>]*{re.escape(attrs)}[^>]*>(.*?)</{tag}>"
    match = re.search(pattern, xml or "", re.DOTALL)
    return strip_markup(match.group(1)) if match else ""


def parse_pubmed_abstract(article_xml: str) -> str:
    """Join all (labelled) AbstractText parts of a PubMed article."""
    block = _ABSTRACT_BLOCK_RE.search(article_xml or "")
    if not block:
        return ""
    parts: list[str] = []
    for attrs, body in _ABSTRACT_TEXT_RE.findall(block.group(1)):
        text = strip_markup(body)
        if not text:
            continue
        label = _LABEL_RE.search(attrs)
        parts.append(f"{label.group(1)}: {text}" if label else text)
    return "\n".join(parts)


def parse_pubmed_year(article_xml: str) -> int | None:
    """Publication year from <PubDate> (Year or MedlineDate)."""
    block = _PUBDATE_RE.search(article_xml or "")
    if not block:
        return None
    year = _YEAR_RE.search(strip_markup(block.group(1)))
    return int(year.group(1)) if year else None


def split_pubmed_articles(xml_text: str) -> dict[str, str]:
    """Map PMID -> <PubmedArticle> XML from an efetch response."""
    articles: dict[str, str] = {}
    for article in _ARTICLE_RE.findall(xml_text or ""):
        pmid = _PMID_RE.search(article)
        if pmid:
            articles[pmid.group(1)] = article
    return articles
