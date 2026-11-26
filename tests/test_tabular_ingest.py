from pathlib import Path

import pytest

from ingest import load_papers_from_csv, parse_pubmed_efetch_xml
from scigraph.models import SectionKind


def test_load_papers_from_csv_with_optional_fields_and_fallbacks(tmp_path: Path) -> None:
    csv_path = tmp_path / "corpus.csv"
    csv_path.write_text(
        "\n".join(
            [
                "paper_id,title,abstract,doi,authors,venue,publication_year",
                (
                    'p1,"Metformin Trial","Metformin reduced HbA1c by 1.2% (n=120, p=0.004).",'
                    '10.1234/metformin.2025,"Doe Jane; Smith John","JAMA",2025'
                ),
                (
                    'p2,"Placebo Baseline","No significant change in LDL (n=80, p=0.42).",'
                    ",,, "
                ),
            ]
        ),
        encoding="utf-8",
    )

    papers = load_papers_from_csv(csv_path)
    assert len(papers) == 2

    p1 = papers[0]
    assert p1.paper_id == "p1"
    assert p1.doi == "10.1234/metformin.2025"
    assert p1.title == "Metformin Trial"
    assert p1.authors == ("Doe Jane", "Smith John")
    assert p1.venue == "JAMA"
    assert p1.publication_year == 2025
    assert len(p1.sections) == 1
    assert p1.sections[0].kind == SectionKind.ABSTRACT
    assert p1.sections[0].heading == "Abstract"
    assert p1.sections[0].start_char == 0
    assert p1.sections[0].end_char == len(p1.sections[0].text)
    assert p1.full_text.startswith(p1.sections[0].text)

    p2 = papers[1]
    assert p2.paper_id == "p2"
    assert p2.doi == "10.0000/tabular.p2"
    assert p2.authors == ("Unknown",)
    assert p2.venue == "tabular-import"
    assert p2.publication_year == 2026


def test_load_papers_from_tsv_auto_detects_tab_delimiter(tmp_path: Path) -> None:
    tsv_path = tmp_path / "corpus.tsv"
    tsv_path.write_text(
        "paper_id\ttitle\tabstract\n"
        "t1\tTSV Study\tIntervention lowered systolic BP (n=64, p=0.01).\n",
        encoding="utf-8",
    )

    papers = load_papers_from_csv(tsv_path)
    assert len(papers) == 1
    assert papers[0].paper_id == "t1"
    assert papers[0].doi == "10.0000/tabular.t1"
    assert papers[0].sections[0].text == "Intervention lowered systolic BP (n=64, p=0.01)."


def test_load_papers_from_csv_missing_required_columns_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_cols.csv"
    csv_path.write_text("paper_id,title\np1,Only Title\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required columns"):
        load_papers_from_csv(csv_path)


def test_load_papers_from_csv_empty_rows_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty_rows.csv"
    csv_path.write_text("paper_id,title,abstract\n", encoding="utf-8")

    with pytest.raises(ValueError, match="0 data rows"):
        load_papers_from_csv(csv_path)


def test_load_papers_from_csv_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        load_papers_from_csv(tmp_path / "missing.csv")


def test_parse_pubmed_efetch_xml_valid_and_fallback_doi_and_skips() -> None:
    xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>39001234</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2024</Year></PubDate>
          </JournalIssue>
          <Title>Nature Medicine</Title>
        </Journal>
        <ArticleTitle>GLP-1 agonist improves glycemic control.</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Patients were randomized (n=200).</AbstractText>
          <AbstractText Label="RESULTS">HbA1c decreased significantly (p=0.001).</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Reyes</LastName>
            <ForeName>Elena</ForeName>
          </Author>
          <Author>
            <LastName>Patel</LastName>
            <ForeName>Vikram</ForeName>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">39001234</ArticleId>
        <ArticleId IdType="doi">10.1038/s41591-024-00001-x</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>39005678</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2023</Year></PubDate>
          </JournalIssue>
          <Title>Lancet</Title>
        </Journal>
        <ArticleTitle>Observational cohort without DOI.</ArticleTitle>
        <Abstract>
          <AbstractText>No effect observed (n=50, p=0.65).</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>39009999</PMID>
      <Article>
        <ArticleTitle>Article missing abstract should be skipped.</ArticleTitle>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>39008888</PMID>
      <Article>
        <Abstract>
          <AbstractText>Article missing title should be skipped.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""
    papers = parse_pubmed_efetch_xml(xml_bytes)
    assert len(papers) == 2

    first = papers[0]
    assert first.paper_id == "pubmed-39001234"
    assert first.doi == "10.1038/s41591-024-00001-x"
    assert first.title == "GLP-1 agonist improves glycemic control."
    assert first.authors == ("Reyes Elena", "Patel Vikram")
    assert first.venue == "Nature Medicine"
    assert first.publication_year == 2024
    assert len(first.sections) == 1
    assert first.sections[0].kind == SectionKind.ABSTRACT
    assert first.sections[0].text == (
        "Patients were randomized (n=200). HbA1c decreased significantly (p=0.001)."
    )
    assert first.sections[0].start_char == 0
    assert first.sections[0].end_char == len(first.sections[0].text)

    second = papers[1]
    assert second.paper_id == "pubmed-39005678"
    assert second.doi == "10.0000/pubmed.39005678"
    assert second.authors == ("Unknown",)
    assert second.venue == "Lancet"
    assert second.publication_year == 2023


def test_parse_pubmed_efetch_xml_malformed_raises() -> None:
    with pytest.raises(ValueError, match="Malformed PubMed EFetch XML"):
        parse_pubmed_efetch_xml(b"<PubmedArticleSet><unclosed></PubmedArticleSet>")
