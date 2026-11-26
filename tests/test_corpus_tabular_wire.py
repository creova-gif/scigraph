import json
from pathlib import Path

import pytest

from ingest.corpus_loader import load_papers_from_path


def _sample_pubmed_xml(*, pmid: str, doi: str, title: str, abstract: str) -> bytes:
    xml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>{pmid}</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2025</Year></PubDate>
          </JournalIssue>
          <Title>Journal of Testing</Title>
        </Journal>
        <ArticleTitle>{title}</ArticleTitle>
        <Abstract>
          <AbstractText>{abstract}</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Doe</LastName>
            <ForeName>Jane</ForeName>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">{doi}</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""
    return xml_str.encode("utf-8")


def test_load_papers_from_path_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "papers.csv"
    csv_path.write_text(
        "paper_id,title,abstract,doi,authors,publication_year,venue\n"
        "csv-1,CSV Study Alpha,Abstract for CSV alpha.,10.1000/csv.1,"
        "Alice Smith;Bob Jones,2024,CSV Journal\n",
        encoding="utf-8",
    )

    papers = load_papers_from_path(csv_path)
    assert len(papers) == 1
    assert papers[0].paper_id == "csv-1"
    assert papers[0].doi == "10.1000/csv.1"
    assert papers[0].title == "CSV Study Alpha"
    assert papers[0].authors == ("Alice Smith", "Bob Jones")
    assert papers[0].publication_year == 2024
    assert papers[0].venue == "CSV Journal"
    assert "Abstract for CSV alpha." in papers[0].full_text


def test_load_papers_from_path_tsv(tmp_path: Path) -> None:
    tsv_path = tmp_path / "papers.tsv"
    tsv_path.write_text(
        "paper_id\ttitle\tabstract\tauthors\tpublication_year\n"
        "tsv-1\tTSV Study Beta\tAbstract for TSV beta.\tCarol White\t2023\n",
        encoding="utf-8",
    )

    papers = load_papers_from_path(tsv_path)
    assert len(papers) == 1
    assert papers[0].paper_id == "tsv-1"
    assert papers[0].doi == "10.0000/tabular.tsv-1"
    assert papers[0].title == "TSV Study Beta"
    assert papers[0].authors == ("Carol White",)
    assert papers[0].publication_year == 2023
    assert "Abstract for TSV beta." in papers[0].full_text


def test_load_papers_from_path_pubmed_xml(tmp_path: Path) -> None:
    xml_path = tmp_path / "pubmed.xml"
    xml_path.write_bytes(
        _sample_pubmed_xml(
            pmid="12345678",
            doi="10.1000/pubmed.12345678",
            title="PubMed XML Study",
            abstract="Abstract from PubMed EFetch XML.",
        )
    )

    papers = load_papers_from_path(xml_path)
    assert len(papers) == 1
    assert papers[0].paper_id == "pubmed-12345678"
    assert papers[0].doi == "10.1000/pubmed.12345678"
    assert papers[0].title == "PubMed XML Study"
    assert papers[0].authors == ("Doe Jane",)
    assert papers[0].publication_year == 2025
    assert papers[0].venue == "Journal of Testing"
    assert "Abstract from PubMed EFetch XML." in papers[0].full_text


def test_load_papers_from_path_mixed_directory(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "mixed_corpus"
    corpus_dir.mkdir()

    (corpus_dir / "01_data.json").write_text(
        json.dumps(
            [
                {
                    "paper_id": "json-1",
                    "doi": "10.1000/json.1",
                    "title": "JSON Paper",
                    "authors": ["Dan Lee"],
                    "publication_year": 2022,
                    "venue": "JSON Conf",
                    "full_text": "JSON paper full text.",
                }
            ]
        ),
        encoding="utf-8",
    )
    (corpus_dir / "02_data.csv").write_text(
        "paper_id,title,abstract\ncsv-2,CSV Paper,CSV abstract text.\n",
        encoding="utf-8",
    )
    (corpus_dir / "03_data.tsv").write_text(
        "paper_id\ttitle\tabstract\ntsv-2\tTSV Paper\tTSV abstract text.\n",
        encoding="utf-8",
    )
    (corpus_dir / "04_data.xml").write_bytes(
        _sample_pubmed_xml(
            pmid="99999",
            doi="10.1000/xml.99999",
            title="XML Paper",
            abstract="XML abstract text.",
        )
    )
    (corpus_dir / "99_readme.txt").write_text("ignored file", encoding="utf-8")

    papers = load_papers_from_path(corpus_dir)
    assert [p.paper_id for p in papers] == ["json-1", "csv-2", "tsv-2", "pubmed-99999"]

    bad_file = tmp_path / "unsupported.txt"
    bad_file.write_text("not a corpus", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported corpus file extension"):
        load_papers_from_path(bad_file)
