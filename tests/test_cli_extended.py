import json
import zlib
from pathlib import Path

import pytest

from evals.benchmark import BENCHMARK_30_PAPERS
from ingest import OPEN_ACCESS_5_PDF_LAYOUTS, extract_paper_from_layout
from scigraph.cli import main


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


def _write_json_corpus(tmp_path: Path, count: int = 2) -> Path:
    papers = [
        extract_paper_from_layout(spec.paper_id, spec.blocks).model_dump(mode="json")
        for spec in BENCHMARK_30_PAPERS[:count]
    ]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"papers": papers}), encoding="utf-8")
    return corpus_path


def _write_flate_pdf_corpus(tmp_path: Path) -> Path:
    blocks = OPEN_ACCESS_5_PDF_LAYOUTS["arxiv-2401.10101"]
    lines = [
        f"BT /F1 10 Tf {b.x0:.1f} {b.y0:.1f} {b.x1:.1f} {b.y1:.1f} "
        f"{b.page_number} Tm "
        f"({b.text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')}) Tj ET"
        for b in blocks
    ]
    pdf_path = tmp_path / "arxiv-2401.10101.pdf"
    pdf_path.write_bytes(_build_flate_pdf("\n".join(lines).encode("utf-8")))
    return pdf_path


def test_verify_input_json_and_flatedecode_pdf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_corpus = _write_json_corpus(tmp_path, count=2)
    rc_json = main(["verify", "--input", str(json_corpus)])
    captured_json = capsys.readouterr()
    assert rc_json == 0
    assert "doi_verified=True" in captured_json.out

    pdf_corpus = _write_flate_pdf_corpus(tmp_path)
    rc_pdf = main(["verify", "--input", str(pdf_corpus)])
    captured_pdf = capsys.readouterr()
    assert rc_pdf == 0
    assert "arxiv-2401.10101: doi_verified=True" in captured_pdf.out


def test_verify_input_mutually_exclusive_and_bad_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_corpus = _write_json_corpus(tmp_path, count=1)
    rc_mutex = main(["verify", "--paper-id", "paper-01", "--input", str(json_corpus)])
    assert rc_mutex == 2

    missing = tmp_path / "does-not-exist.json"
    rc_missing = main(["verify", "--input", str(missing)])
    captured = capsys.readouterr()
    assert rc_missing == 2
    assert "Failed to load corpus" in captured.err


def test_report_input_json_and_bad_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_corpus = _write_json_corpus(tmp_path, count=4)
    rc = main(["report", "--input", str(json_corpus), "--format", "json"])
    captured = capsys.readouterr()
    assert rc == 0
    bundle = json.loads(captured.out)
    assert bundle["metrics"] is None
    assert len(bundle["papers"]) == 4
    assert len(bundle["claims"]) > 0

    rc_bad = main(["report", "--input", str(tmp_path / "missing.json"), "--format", "json"])
    captured_bad = capsys.readouterr()
    assert rc_bad == 2
    assert "Failed to load corpus" in captured_bad.err


@pytest.mark.parametrize("store_name", ["graph.db", "graph.json"])
def test_ingest_and_query_roundtrip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    store_name: str,
) -> None:
    json_corpus = _write_json_corpus(tmp_path, count=4)
    store_path = tmp_path / store_name

    rc_ingest = main(["ingest", str(json_corpus), "--store", str(store_path), "--json"])
    ingest_out = capsys.readouterr()
    assert rc_ingest == 0
    summary = json.loads(ingest_out.out)
    assert summary["papers"] == 4
    assert summary["verified_claims"] > 0
    assert summary["store"] == str(store_path)
    assert store_path.exists()

    rc_all = main(["query", "--store", str(store_path), "--json"])
    all_out = capsys.readouterr()
    assert rc_all == 0
    all_claims = json.loads(all_out.out)
    assert len(all_claims) == summary["verified_claims"]

    sample_claim = all_claims[0]
    sample_tuple = sample_claim["claim_tuple"]

    rc_filtered = main(
        [
            "query",
            "--store",
            str(store_path),
            "--intervention",
            sample_tuple["intervention"],
            "--condition",
            sample_tuple["condition"],
            "--outcome",
            sample_tuple["outcome"],
            "--direction",
            sample_tuple["direction"],
            "--paper-id",
            sample_claim["paper_id"],
            "--json",
        ]
    )
    filtered_out = capsys.readouterr()
    assert rc_filtered == 0
    filtered_claims = json.loads(filtered_out.out)
    assert len(filtered_claims) >= 1
    assert all(c["paper_id"] == sample_claim["paper_id"] for c in filtered_claims)

    rc_text = main(
        [
            "query",
            "--store",
            str(store_path),
            "--paper-id",
            sample_claim["paper_id"],
        ]
    )
    text_out = capsys.readouterr()
    assert rc_text == 0
    assert sample_claim["paper_id"] in text_out.out


def test_ingest_and_query_error_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_corpus = _write_json_corpus(tmp_path, count=1)

    rc_bad_ext = main(["ingest", str(json_corpus), "--store", str(tmp_path / "graph.txt")])
    err_ext = capsys.readouterr()
    assert rc_bad_ext == 2
    assert "Unsupported store extension" in err_ext.err

    rc_bad_input = main(
        ["ingest", str(tmp_path / "missing.json"), "--store", str(tmp_path / "ok.db")]
    )
    err_input = capsys.readouterr()
    assert rc_bad_input == 2
    assert "Failed to ingest" in err_input.err

    rc_missing_store = main(["query", "--store", str(tmp_path / "missing.db")])
    err_store = capsys.readouterr()
    assert rc_missing_store == 2
    assert "Store path does not exist" in err_store.err

    bad_store = tmp_path / "graph.yaml"
    bad_store.write_text("{}", encoding="utf-8")
    rc_bad_query_ext = main(["query", "--store", str(bad_store)])
    err_query_ext = capsys.readouterr()
    assert rc_bad_query_ext == 2
    assert "Unsupported store extension" in err_query_ext.err
