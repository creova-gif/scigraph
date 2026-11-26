import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable

from scigraph.models import DOI_PATTERN, Paper, PaperSection, SectionKind
from scigraph.net_guard import (
    NoRedirectHandler,
    assert_public_dns_resolution,
    validate_public_https_url,
)

MAX_RESPONSE_BYTES = 10 * 1024 * 1024

Fetcher = Callable[[str], bytes]

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_FALLBACK_ID_SANITIZE = re.compile(r"[^-._;()/:A-Za-z0-9]")
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")
_DEFAULT_PUB_YEAR = 2024

_NoRedirectHandler = NoRedirectHandler
_assert_public_dns_resolution = assert_public_dns_resolution
_validate_https_url = validate_public_https_url


def default_https_fetcher(url: str, timeout: float = 15.0) -> bytes:
    """Fetch HTTPS response bytes with SSRF validation and bounded size."""
    validated_url = validate_public_https_url(url)
    hostname = urllib.parse.urlsplit(validated_url).hostname
    if not hostname:
        raise ValueError("URL must include a non-empty hostname")
    assert_public_dns_resolution(hostname)

    opener = urllib.request.build_opener(NoRedirectHandler)
    with opener.open(validated_url, timeout=timeout) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if not isinstance(data, bytes):
        raise ValueError("Expected bytes response from HTTPS fetcher")
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Response exceeded maximum size of {MAX_RESPONSE_BYTES} bytes")
    return data


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _parse_year(raw: object, default: int = _DEFAULT_PUB_YEAR) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool):
        year = raw
    elif isinstance(raw, str):
        stripped = raw.strip()
        if len(stripped) >= 4 and stripped[:4].isdigit():
            year = int(stripped[:4])
        else:
            return default
    else:
        return default
    return year if 1900 <= year <= 2100 else default


def _sanitize_doi_suffix(raw: str) -> str:
    cleaned = _FALLBACK_ID_SANITIZE.sub("_", raw.strip())
    return cleaned or "unknown"


def _build_abstract_paper(
    *,
    paper_id: str,
    doi: str,
    title: str,
    authors: tuple[str, ...],
    publication_year: int,
    venue: str,
    abstract: str,
) -> Paper:
    section = PaperSection(
        kind=SectionKind.ABSTRACT,
        heading="Abstract",
        text=abstract,
        start_char=0,
        end_char=len(abstract),
    )
    full_text = f"{abstract}\n\nTitle: {title}\nDOI: {doi}"
    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=authors,
        publication_year=publication_year,
        venue=venue,
        full_text=full_text,
        sections=(section,),
    )


def parse_arxiv_atom_xml(xml_bytes: bytes) -> list[Paper]:
    """Parse an arXiv Atom XML feed payload into Paper models."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid arXiv Atom XML: {exc}") from exc

    papers: list[Paper] = []
    for idx, entry in enumerate(root.findall(f"{{{_ATOM_NS}}}entry")):
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        summary_el = entry.find(f"{{{_ATOM_NS}}}summary")
        if title_el is None or summary_el is None:
            continue

        title = _normalize_whitespace(title_el.text or "")
        summary = _normalize_whitespace(summary_el.text or "")
        if not title or not summary:
            continue

        id_el = entry.find(f"{{{_ATOM_NS}}}id")
        raw_id = (id_el.text or "").strip() if id_el is not None else ""
        arxiv_id = raw_id.rsplit("/", 1)[-1].strip() if raw_id else f"arxiv-{idx}"
        base_id = _VERSION_SUFFIX_RE.sub("", arxiv_id) or arxiv_id

        doi_el = entry.find(f"{{{_ARXIV_NS}}}doi")
        raw_doi = (doi_el.text or "").strip() if doi_el is not None else ""
        if raw_doi and DOI_PATTERN.match(raw_doi):
            doi = raw_doi
        else:
            doi = f"10.48550/arXiv.{_sanitize_doi_suffix(base_id)}"

        author_names: list[str] = []
        for author_el in entry.findall(f"{{{_ATOM_NS}}}author"):
            name_el = author_el.find(f"{{{_ATOM_NS}}}name")
            if name_el is not None and name_el.text:
                cleaned_name = _normalize_whitespace(name_el.text)
                if cleaned_name:
                    author_names.append(cleaned_name)
        authors = tuple(author_names) if author_names else ("Unknown",)

        published_el = entry.find(f"{{{_ATOM_NS}}}published")
        pub_year = _parse_year(published_el.text if published_el is not None else None)

        journal_el = entry.find(f"{{{_ARXIV_NS}}}journal_ref")
        venue = (
            _normalize_whitespace(journal_el.text)
            if journal_el is not None and journal_el.text
            else ""
        ) or "arXiv"

        papers.append(
            _build_abstract_paper(
                paper_id=f"arxiv:{arxiv_id}",
                doi=doi,
                title=title,
                authors=authors,
                publication_year=pub_year,
                venue=venue,
                abstract=summary,
            )
        )
    return papers


def parse_europepmc_json(payload_bytes: bytes) -> list[Paper]:
    """Parse a EuropePMC REST search JSON payload into Paper models."""
    try:
        payload: object = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid EuropePMC JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("EuropePMC payload must be a JSON object")

    result_list = payload.get("resultList")
    if result_list is None:
        return []
    if not isinstance(result_list, dict):
        raise ValueError("EuropePMC 'resultList' must be a JSON object")

    entries = result_list.get("result", [])
    if not isinstance(entries, list):
        raise ValueError("EuropePMC 'resultList.result' must be a JSON list")

    papers: list[Paper] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

        raw_title = entry.get("title")
        raw_abstract = entry.get("abstractText")
        if not isinstance(raw_title, str) or not isinstance(raw_abstract, str):
            continue

        title = _normalize_whitespace(raw_title)
        abstract = _normalize_whitespace(raw_abstract)
        if not title or not abstract:
            continue

        raw_id = entry.get("pmcid") or entry.get("id") or entry.get("pmid")
        paper_id = str(raw_id).strip() if raw_id else f"epmc-{idx}"
        if not paper_id:
            paper_id = f"epmc-{idx}"

        raw_doi = entry.get("doi")
        if isinstance(raw_doi, str) and DOI_PATTERN.match(raw_doi.strip()):
            doi = raw_doi.strip()
        else:
            doi = f"10.0000/epmc.{_sanitize_doi_suffix(paper_id)}"

        raw_authors = entry.get("authorString")
        if isinstance(raw_authors, str) and raw_authors.strip():
            parsed_authors = tuple(
                _normalize_whitespace(part)
                for part in raw_authors.split(",")
                if _normalize_whitespace(part)
            )
            authors = parsed_authors if parsed_authors else ("Unknown",)
        else:
            authors = ("Unknown",)

        raw_journal = entry.get("journalTitle")
        venue = (
            _normalize_whitespace(raw_journal)
            if isinstance(raw_journal, str) and raw_journal.strip()
            else "EuropePMC"
        )

        pub_year = _parse_year(entry.get("pubYear"))

        papers.append(
            _build_abstract_paper(
                paper_id=paper_id,
                doi=doi,
                title=title,
                authors=authors,
                publication_year=pub_year,
                venue=venue,
                abstract=abstract,
            )
        )
    return papers


def _validate_query_and_limit(query: str, max_results: int) -> tuple[str, int]:
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("query must be a non-empty string")
    if isinstance(max_results, bool) or not (1 <= max_results <= 100):
        raise ValueError(f"max_results must be between 1 and 100, got {max_results!r}")
    return cleaned_query, max_results


def fetch_arxiv_papers(
    query: str,
    max_results: int = 10,
    fetcher: Fetcher | None = None,
) -> list[Paper]:
    """Query the arXiv Atom API and parse results into Paper models."""
    cleaned_query, limit = _validate_query_and_limit(query, max_results)
    encoded_query = urllib.parse.quote_plus(cleaned_query)
    url = (
        "https://export.arxiv.org/api/query"
        f"?search_query=all:{encoded_query}&start=0&max_results={limit}"
    )
    active_fetcher = fetcher if fetcher is not None else default_https_fetcher
    return parse_arxiv_atom_xml(active_fetcher(url))


def fetch_europepmc_papers(
    query: str,
    max_results: int = 10,
    fetcher: Fetcher | None = None,
) -> list[Paper]:
    """Query the EuropePMC REST JSON API and parse results into Paper models."""
    cleaned_query, limit = _validate_query_and_limit(query, max_results)
    encoded_query = urllib.parse.quote_plus(cleaned_query)
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={encoded_query}&resultType=core&format=json&pageSize={limit}"
    )
    active_fetcher = fetcher if fetcher is not None else default_https_fetcher
    return parse_europepmc_json(active_fetcher(url))
