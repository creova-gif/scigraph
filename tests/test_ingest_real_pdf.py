import json
import zlib
from pathlib import Path

import pytest

from ingest import (
    OPEN_ACCESS_5_PDF_LAYOUTS,
    extract_paper_from_pdf_bytes,
    extract_text_from_pdf_bytes,
    load_papers_from_path,
)
from ingest.extractor import MAX_DECOMPRESSED_BYTES, MAX_PDF_BYTES


def _build_flate_pdf(content_stream: bytes) -> bytes:
    compressed = zlib.compress(content_stream)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Length "
        + str(len(compressed)).encode("ascii")
        + b" /Filter /FlateDecode >> stream\n"
        + compressed
        + b"\nendstream\nendobj\n%%EOF\n"
    )


def test_extract_text_flatedecode_and_tj_operators() -> None:
    stream = (
        b"BT /F1 12 Tf\n"
        b"(DOI: 10.1234/real.pdf.001) Tj\n"
        b"[(Treatment ) -10 (with) -250 (Compound X) 15 ( \\(v2\\))] TJ\n"
        b"ET\n"
    )
    pdf_bytes = _build_flate_pdf(stream)

    extracted = extract_text_from_pdf_bytes(pdf_bytes)
    assert "DOI: 10.1234/real.pdf.001" in extracted
    assert "Treatment with Compound X (v2)" in extracted


def test_extract_paper_from_flatedecode_layout_pdf() -> None:
    blocks = OPEN_ACCESS_5_PDF_LAYOUTS["arxiv-2401.10101"]
    lines: list[str] = []
    for b in blocks:
        escaped = b.text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(
            f"BT /F1 10 Tf {b.x0:.1f} {b.y0:.1f} {b.x1:.1f} {b.y1:.1f} "
            f"{b.page_number} Tm ({escaped}) Tj ET"
        )
    pdf_bytes = _build_flate_pdf("\n".join(lines).encode("utf-8"))

    paper = extract_paper_from_pdf_bytes("arxiv-2401.10101", pdf_bytes)
    assert paper.doi == "10.48550/arXiv.2401.10101"
    assert paper.paper_id == "arxiv-2401.10101"


def test_flatedecode_decompression_bomb_and_corrupt_zlib() -> None:
    bomb_payload = b"A" * (MAX_DECOMPRESSED_BYTES + 1024)
    bomb_pdf = _build_flate_pdf(bomb_payload)
    with pytest.raises(ValueError, match="MAX_DECOMPRESSED_BYTES"):
        extract_text_from_pdf_bytes(bomb_pdf)

    corrupt_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Filter /FlateDecode >> stream\n"
        b"not-valid-zlib-data\n"
        b"endstream\nendobj\n%%EOF\n"
    )
    with pytest.raises(ValueError, match="/FlateDecode"):
        extract_text_from_pdf_bytes(corrupt_pdf)


def test_flatedecode_cumulative_multistream_decompression_bomb() -> None:
    chunk_size = 26 * 1024 * 1024
    assert chunk_size < MAX_DECOMPRESSED_BYTES
    assert chunk_size * 2 > MAX_DECOMPRESSED_BYTES

    compressed_chunk = zlib.compress(b"A" * chunk_size)
    multistream_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Length "
        + str(len(compressed_chunk)).encode("ascii")
        + b" /Filter /FlateDecode >> stream\n"
        + compressed_chunk
        + b"\nendstream\nendobj\n"
        b"2 0 obj << /Length "
        + str(len(compressed_chunk)).encode("ascii")
        + b" /Filter /FlateDecode >> stream\n"
        + compressed_chunk
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    with pytest.raises(ValueError, match="MAX_DECOMPRESSED_BYTES"):
        extract_text_from_pdf_bytes(multistream_pdf)


def test_pdf_error_guards_header_size_encrypt_filter_empty() -> None:
    with pytest.raises(ValueError, match="Invalid PDF header"):
        extract_text_from_pdf_bytes(b"NOT-A-PDF")

    with pytest.raises(ValueError, match="MAX_PDF_BYTES"):
        extract_text_from_pdf_bytes(b"%PDF-1.4\n" + b"0" * MAX_PDF_BYTES)

    encrypted_pdf = b"%PDF-1.4\n1 0 obj << /Encrypt 2 0 R >> endobj\n"
    with pytest.raises(ValueError, match="/Encrypt"):
        extract_text_from_pdf_bytes(encrypted_pdf)

    unsupported_filter_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Filter /LZWDecode >> stream\nabc\nendstream\n"
    )
    with pytest.raises(ValueError, match="Unsupported PDF stream filter"):
        extract_text_from_pdf_bytes(unsupported_filter_pdf)

    empty_stream_pdf = b"%PDF-1.4\n1 0 obj << >> stream\nBT ET\nendstream\n"
    with pytest.raises(ValueError, match="No extractable text"):
        extract_text_from_pdf_bytes(empty_stream_pdf)


def test_load_papers_from_json_list_and_wrapper(tmp_path: Path) -> None:
    paper_dict = {
        "paper_id": "json-p1",
        "doi": "10.1000/json.1",
        "title": "JSON Corpus Paper",
        "authors": ["Alice Smith", "Bob Jones"],
        "publication_year": 2025,
        "venue": "Nature",
        "full_text": "Abstract: Treatment with Drug A increased survival.",
        "sections": [],
    }

    list_path = tmp_path / "list_corpus.json"
    list_path.write_text(json.dumps([paper_dict]), encoding="utf-8")
    loaded_list = load_papers_from_path(list_path)
    assert len(loaded_list) == 1
    assert loaded_list[0].paper_id == "json-p1"
    assert loaded_list[0].authors == ("Alice Smith", "Bob Jones")

    wrapper_path = tmp_path / "wrapper_corpus.json"
    wrapper_path.write_text(json.dumps({"papers": [paper_dict]}), encoding="utf-8")
    loaded_wrapper = load_papers_from_path(wrapper_path)
    assert len(loaded_wrapper) == 1
    assert loaded_wrapper[0].doi == "10.1000/json.1"

    bad_json_path = tmp_path / "bad.json"
    bad_json_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_papers_from_path(bad_json_path)

    bad_schema_path = tmp_path / "bad_schema.json"
    bad_schema_path.write_text(json.dumps([{"paper_id": "only-id"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Paper schema"):
        load_papers_from_path(bad_schema_path)


def test_load_papers_from_pdf_with_and_without_doi(tmp_path: Path) -> None:
    pdf_with_doi = tmp_path / "study_alpha.pdf"
    pdf_with_doi.write_bytes(
        _build_flate_pdf(
            b"BT /F1 12 Tf (Study Alpha Title) Tj (DOI: 10.5555/alpha.42) Tj ET"
        )
    )
    papers_with_doi = load_papers_from_path(pdf_with_doi)
    assert len(papers_with_doi) == 1
    assert papers_with_doi[0].paper_id == "study_alpha"
    assert papers_with_doi[0].doi == "10.5555/alpha.42"
    assert papers_with_doi[0].venue == "local-pdf"
    assert papers_with_doi[0].authors == ("Unknown",)

    pdf_no_doi = tmp_path / "study_beta.pdf"
    pdf_no_doi.write_bytes(
        _build_flate_pdf(b"BT /F1 12 Tf [(Study Beta) -200 (Results)] TJ ET")
    )
    papers_no_doi = load_papers_from_path(pdf_no_doi)
    assert len(papers_no_doi) == 1
    assert papers_no_doi[0].paper_id == "study_beta"
    assert papers_no_doi[0].doi == "10.0000/local.study_beta"
    assert "Study Beta Results" in papers_no_doi[0].full_text


def test_load_papers_from_directory_and_errors(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    (corpus_dir / "01_meta.json").write_text(
        json.dumps(
            [
                {
                    "paper_id": "dir-json-1",
                    "doi": "10.1000/dir.1",
                    "title": "Dir JSON",
                    "authors": ["Carol"],
                    "publication_year": 2024,
                    "venue": "PLOS",
                    "full_text": "Dir JSON full text.",
                }
            ]
        ),
        encoding="utf-8",
    )
    (corpus_dir / "02_local.pdf").write_bytes(
        _build_flate_pdf(b"BT /F1 12 Tf (Dir PDF text) Tj ET")
    )
    (corpus_dir / "ignore.txt").write_text("ignored", encoding="utf-8")

    papers = load_papers_from_path(corpus_dir)
    assert [p.paper_id for p in papers] == ["dir-json-1", "02_local"]

    with pytest.raises(ValueError, match="does not exist"):
        load_papers_from_path(tmp_path / "missing")

    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    (empty_dir / "notes.txt").write_text("no papers", encoding="utf-8")
    with pytest.raises(ValueError, match="No supported"):
        load_papers_from_path(empty_dir)
