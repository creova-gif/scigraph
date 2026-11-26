import json
from types import TracebackType
from typing import Self

import pytest

from ingest import (
    fetch_arxiv_papers,
    fetch_europepmc_papers,
    parse_arxiv_atom_xml,
    parse_europepmc_json,
)
from ingest.connectors import (
    MAX_RESPONSE_BYTES,
    _validate_https_url,
    default_https_fetcher,
)
from scigraph.models import SectionKind

_SAMPLE_ARXIV_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <published>2024-01-15T12:00:00Z</published>
    <title>  Metformin   Reduces  Inflammation </title>
    <summary>  Metformin lowered IL-6 levels in adults (p = 0.002, n = 120). </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:doi>10.1016/j.cell.2024.01.001</arxiv:doi>
    <arxiv:journal_ref>Cell 2024</arxiv:journal_ref>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.99999v1</id>
    <published>2023-11-01T00:00:00Z</published>
    <title>Fallback DOI Paper</title>
    <summary>No explicit DOI tag provided in this arXiv entry.</summary>
    <author><name>Grace Hopper</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00000v1</id>
    <published>2024-02-01T00:00:00Z</published>
    <title>Missing Summary Entry</title>
  </entry>
</feed>
"""

_SAMPLE_EUROPEPMC_JSON = json.dumps(
    {
        "resultList": {
            "result": [
                {
                    "id": "38123456",
                    "pmcid": "PMC10987654",
                    "pmid": "38123456",
                    "doi": "10.1038/s41586-024-00001-1",
                    "title": "Sleep Deprivation Impairs Consolidation",
                    "authorString": "Rosalind Franklin, Maurice Wilkins",
                    "journalTitle": "Nature",
                    "pubYear": "2024",
                    "abstractText": "Acute sleep loss reduced recall accuracy (p < 0.01, n = 64).",
                },
                {
                    "id": "38123457",
                    "title": "Entry Without Abstract Should Be Skipped",
                    "authorString": "Jane Doe",
                    "pubYear": "2024",
                },
                {
                    "id": "38123458",
                    "title": "Fallback DOI EuropePMC Entry",
                    "abstractText": "Valid abstract without an explicit DOI field.",
                    "pubYear": "2022",
                },
            ]
        }
    }
).encode("utf-8")


class _FakeHttpResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amt: int | None = None) -> bytes:
        if amt is None:
            return self._payload
        return self._payload[:amt]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


def test_parse_arxiv_atom_xml_extracts_papers_and_fallback_doi() -> None:
    papers = parse_arxiv_atom_xml(_SAMPLE_ARXIV_XML)
    assert len(papers) == 2

    first = papers[0]
    assert first.paper_id == "arxiv:2401.12345v2"
    assert first.doi == "10.1016/j.cell.2024.01.001"
    assert first.title == "Metformin Reduces Inflammation"
    assert first.authors == ("Ada Lovelace", "Alan Turing")
    assert first.publication_year == 2024
    assert first.venue == "Cell 2024"
    assert len(first.sections) == 1
    sec = first.sections[0]
    assert sec.kind == SectionKind.ABSTRACT
    assert sec.heading == "Abstract"
    assert sec.start_char == 0
    assert sec.end_char == len(sec.text)
    assert first.full_text[sec.start_char : sec.end_char] == sec.text
    assert first.doi in first.full_text

    second = papers[1]
    assert second.doi == "10.48550/arXiv.2402.99999"
    assert second.publication_year == 2023
    assert second.venue == "arXiv"
    assert second.authors == ("Grace Hopper",)


def test_parse_arxiv_atom_xml_rejects_malformed_xml() -> None:
    with pytest.raises(ValueError, match="Invalid arXiv Atom XML"):
        parse_arxiv_atom_xml(b"<feed><unclosed></feed>")


def test_parse_europepmc_json_extracts_and_skips_incomplete() -> None:
    papers = parse_europepmc_json(_SAMPLE_EUROPEPMC_JSON)
    assert len(papers) == 2

    first = papers[0]
    assert first.paper_id == "PMC10987654"
    assert first.doi == "10.1038/s41586-024-00001-1"
    assert first.title == "Sleep Deprivation Impairs Consolidation"
    assert first.authors == ("Rosalind Franklin", "Maurice Wilkins")
    assert first.venue == "Nature"
    assert first.publication_year == 2024
    assert len(first.sections) == 1
    sec = first.sections[0]
    assert sec.kind == SectionKind.ABSTRACT
    assert first.full_text[sec.start_char : sec.end_char] == sec.text
    assert first.doi in first.full_text

    second = papers[1]
    assert second.paper_id == "38123458"
    assert second.doi == "10.0000/epmc.38123458"
    assert second.publication_year == 2022
    assert second.authors == ("Unknown",)
    assert second.venue == "EuropePMC"


def test_parse_europepmc_json_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="Invalid EuropePMC JSON"):
        parse_europepmc_json(b"{not-valid-json")


def test_fetch_arxiv_papers_uses_mock_fetcher_and_encodes_query() -> None:
    seen_urls: list[str] = []

    def mock_fetcher(url: str) -> bytes:
        seen_urls.append(url)
        return _SAMPLE_ARXIV_XML

    papers = fetch_arxiv_papers("metformin & IL-6", max_results=5, fetcher=mock_fetcher)
    assert len(papers) == 2
    assert len(seen_urls) == 1
    assert seen_urls[0] == (
        "https://export.arxiv.org/api/query"
        "?search_query=all:metformin+%26+IL-6&start=0&max_results=5"
    )


def test_fetch_europepmc_papers_uses_mock_fetcher_and_encodes_query() -> None:
    seen_urls: list[str] = []

    def mock_fetcher(url: str) -> bytes:
        seen_urls.append(url)
        return _SAMPLE_EUROPEPMC_JSON

    papers = fetch_europepmc_papers("sleep deprivation", max_results=12, fetcher=mock_fetcher)
    assert len(papers) == 2
    assert len(seen_urls) == 1
    assert seen_urls[0] == (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        "?query=sleep+deprivation&resultType=core&format=json&pageSize=12"
    )


@pytest.mark.parametrize("bad_max", [0, -5, 101, True])
def test_fetch_rejects_out_of_bounds_max_results(bad_max: int) -> None:
    def unused_fetcher(url: str) -> bytes:
        raise AssertionError(f"Fetcher should not be called: {url}")

    with pytest.raises(ValueError, match="max_results"):
        fetch_arxiv_papers("metformin", max_results=bad_max, fetcher=unused_fetcher)
    with pytest.raises(ValueError, match="max_results"):
        fetch_europepmc_papers("metformin", max_results=bad_max, fetcher=unused_fetcher)


def test_fetch_rejects_empty_query() -> None:
    def unused_fetcher(url: str) -> bytes:
        raise AssertionError(f"Fetcher should not be called: {url}")

    with pytest.raises(ValueError, match="query"):
        fetch_arxiv_papers("   ", fetcher=unused_fetcher)
    with pytest.raises(ValueError, match="query"):
        fetch_europepmc_papers("", fetcher=unused_fetcher)


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://export.arxiv.org/api/query",
        "file:///etc/passwd",
        "https://localhost/api",
        "https://127.0.0.1/api",
        "https://[::1]/api",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.1/internal",
        "https:///missing-host",
    ],
)
def test_validate_https_url_rejects_ssrf_targets(unsafe_url: str) -> None:
    with pytest.raises(ValueError):
        _validate_https_url(unsafe_url)


def test_validate_https_url_accepts_public_https() -> None:
    url = "https://export.arxiv.org/api/query?search_query=all:test"
    assert _validate_https_url(url) == url


def test_default_https_fetcher_enforces_max_response_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"x" * (MAX_RESPONSE_BYTES + 1)

    def fake_urlopen(url: str, timeout: float = 15.0) -> _FakeHttpResponse:
        return _FakeHttpResponse(oversized)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="exceeded maximum size"):
        default_https_fetcher("https://export.arxiv.org/api/query")


def test_default_https_fetcher_returns_bounded_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = b"<feed/>"

    def fake_urlopen(url: str, timeout: float = 15.0) -> _FakeHttpResponse:
        return _FakeHttpResponse(expected)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert default_https_fetcher("https://export.arxiv.org/api/query") == expected
