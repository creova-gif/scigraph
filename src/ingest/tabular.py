import csv
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from scigraph.models import DOI_PATTERN, Paper, PaperSection, SectionKind

_FALLBACK_ID_SANITIZE = re.compile(r"[^-._;()/:A-Za-z0-9]")
_REQUIRED_CSV_COLUMNS = frozenset({"paper_id", "title", "abstract"})
_DEFAULT_PUB_YEAR = 2026


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _sanitize_doi_suffix(raw: str) -> str:
    cleaned = _FALLBACK_ID_SANITIZE.sub("_", raw.strip())
    return cleaned or "unknown"


def _parse_year(raw: str | None, default: int = _DEFAULT_PUB_YEAR) -> int:
    if raw is None:
        return default
    stripped = raw.strip()
    if len(stripped) >= 4 and stripped[:4].isdigit():
        year = int(stripped[:4])
        if 1900 <= year <= 2100:
            return year
    return default


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


def load_papers_from_csv(path: Path, *, delimiter: str | None = None) -> list[Paper]:
    """Load Paper records from a CSV or TSV file.

    Auto-detects ``"\\t"`` for ``.tsv`` and ``","`` for ``.csv`` when
    ``delimiter`` is ``None``. Requires ``paper_id``, ``title``, and
    ``abstract`` columns and at least one data row.
    """
    if not path.exists() or not path.is_file():
        raise ValueError(f"Tabular corpus file does not exist: {path}")

    resolved_delimiter = (
        delimiter
        if delimiter is not None
        else ("\t" if path.suffix.lower() == ".tsv" else ",")
    )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"Unable to read tabular corpus file {path}: {exc}") from exc

    reader = csv.DictReader(raw_text.splitlines(), delimiter=resolved_delimiter)
    if reader.fieldnames is None:
        raise ValueError(f"Tabular corpus file {path} is empty or missing a header row")

    normalized_fields = {name.strip() for name in reader.fieldnames if name}
    missing = sorted(_REQUIRED_CSV_COLUMNS - normalized_fields)
    if missing:
        raise ValueError(
            f"Missing required columns in {path}: {', '.join(missing)}"
        )

    papers: list[Paper] = []
    for row_index, raw_row in enumerate(reader, start=1):
        row = {
            k.strip(): (v.strip() if v is not None else "")
            for k, v in raw_row.items()
            if k is not None
        }
        paper_id = row.get("paper_id", "")
        title = _normalize_whitespace(row.get("title", ""))
        abstract = _normalize_whitespace(row.get("abstract", ""))
        if not paper_id or not title or not abstract:
            raise ValueError(
                f"Row {row_index} in {path} has empty required field(s)"
            )

        raw_doi = row.get("doi", "")
        if raw_doi and DOI_PATTERN.match(raw_doi):
            doi = raw_doi
        else:
            doi = f"10.0000/tabular.{_sanitize_doi_suffix(paper_id)}"

        raw_authors = row.get("authors", "")
        parsed_authors = tuple(
            _normalize_whitespace(part)
            for part in raw_authors.split(";")
            if part.strip()
        )
        authors = parsed_authors if parsed_authors else ("Unknown",)

        venue = _normalize_whitespace(row.get("venue", "")) or "tabular-import"
        publication_year = _parse_year(row.get("publication_year"))

        papers.append(
            _build_abstract_paper(
                paper_id=paper_id,
                doi=doi,
                title=title,
                authors=authors,
                publication_year=publication_year,
                venue=venue,
                abstract=abstract,
            )
        )

    if not papers:
        raise ValueError(f"Tabular corpus file {path} contains 0 data rows")

    return papers


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return _normalize_whitespace("".join(element.itertext()))


def _extract_pubmed_doi(article: ET.Element) -> str:
    """Extract the article's own DOI without matching cited ReferenceList DOIs."""
    for xpath in (
        "./PubmedData/ArticleIdList/ArticleId[@IdType='doi']",
        "./MedlineCitation/Article/ELocationID[@EIdType='doi'][@ValidYN='Y']",
    ):
        for id_node in article.findall(xpath):
            candidate = _element_text(id_node)
            if candidate and DOI_PATTERN.match(candidate):
                return candidate
    return ""


def parse_pubmed_efetch_xml(xml_bytes: bytes) -> list[Paper]:
    """Parse PubMed EFetch ``<PubmedArticleSet>`` XML bytes into Paper models."""
    try:
        root = ET.fromstring(xml_bytes)
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed PubMed EFetch XML: {exc}") from exc

    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _element_text(article.find(".//MedlineCitation/PMID"))
        if not pmid:
            pmid = _element_text(article.find(".//PMID"))
        title = _element_text(article.find(".//Article/ArticleTitle"))
        abstract_parts = [
            _element_text(node)
            for node in article.findall(".//Article/Abstract/AbstractText")
        ]
        abstract = " ".join(part for part in abstract_parts if part)

        if not pmid or not title or not abstract:
            continue

        doi = _extract_pubmed_doi(article)
        if not doi:
            doi = f"10.0000/pubmed.{_sanitize_doi_suffix(pmid)}"

        authors_list: list[str] = []
        for author_node in article.findall(".//Article/AuthorList/Author"):
            last_name = _element_text(author_node.find("LastName"))
            fore_name = _element_text(author_node.find("ForeName"))
            if last_name and fore_name:
                authors_list.append(f"{last_name} {fore_name}")
            elif last_name or fore_name:
                authors_list.append(last_name or fore_name)
            else:
                collective = _element_text(author_node.find("CollectiveName"))
                if collective:
                    authors_list.append(collective)
        authors = tuple(authors_list) if authors_list else ("Unknown",)

        venue = _element_text(article.find(".//Article/Journal/Title")) or "PubMed"
        year_text = _element_text(
            article.find(".//Article/Journal/JournalIssue/PubDate/Year")
        )
        if not year_text:
            year_text = _element_text(article.find(".//PubDate/Year"))
        publication_year = _parse_year(year_text)

        papers.append(
            _build_abstract_paper(
                paper_id=f"pubmed-{pmid}",
                doi=doi,
                title=title,
                authors=authors,
                publication_year=publication_year,
                venue=venue,
                abstract=abstract,
            )
        )

    return papers
