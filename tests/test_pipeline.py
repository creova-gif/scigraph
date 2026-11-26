"""Deterministic unit and end-to-end tests for scigraph.pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from graph.store import GraphSQLiteStore, load_graph_json
from scigraph.pipeline import OutputFormat, PipelineConfig, PipelineSummary, run_pipeline


def _write_corpus_json(path: Path, papers: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"papers": papers}, indent=2), encoding="utf-8")
    return path


def _make_contradicting_corpus() -> list[dict[str, object]]:
    return [
        {
            "paper_id": "paper-alpha",
            "doi": "10.1000/scigraph.2026.001",
            "title": "Metformin Effects on Glycemic Control",
            "authors": ["Alice Smith", "Bob Jones"],
            "publication_year": 2026,
            "venue": "Journal of Metabolic Research",
            "full_text": (
                "DOI: 10.1000/scigraph.2026.001\n"
                "Results: Treatment with Metformin under insulin resistance "
                "decreased fasting glucose compared with placebo "
                "(d = -0.82; n = 240, p < 0.001)."
            ),
            "sections": [],
        },
        {
            "paper_id": "paper-beta",
            "doi": "10.1000/scigraph.2026.002",
            "title": "Re-evaluation of Metformin Under Insulin Resistance",
            "authors": ["Carol Lee"],
            "publication_year": 2026,
            "venue": "Clinical Endocrinology Letters",
            "full_text": (
                "DOI: 10.1000/scigraph.2026.002\n"
                "Results: Treatment with Metformin under insulin resistance "
                "increased fasting glucose compared with placebo "
                "(d = 0.45; n = 120, p = 0.020)."
            ),
            "sections": [],
        },
    ]


def test_run_pipeline_end_to_end_sqlite_and_all_formats(tmp_path: Path) -> None:
    corpus_path = _write_corpus_json(
        tmp_path / "corpus.json",
        _make_contradicting_corpus(),
    )
    store_path = tmp_path / "store" / "claims.db"
    report_dir = tmp_path / "reports"
    all_formats: tuple[OutputFormat, ...] = (
        "markdown",
        "html",
        "sarif",
        "json",
        "bibtex",
        "ris",
    )

    config = PipelineConfig(
        input_path=str(corpus_path),
        store_path=str(store_path),
        report_dir=str(report_dir),
        formats=all_formats,
        fail_on_contradictions=False,
        min_verified_papers=2,
    )
    summary = run_pipeline(config)

    assert isinstance(summary, PipelineSummary)
    assert summary.papers_loaded == 2
    assert summary.papers_verified == 2
    assert summary.claims_verified == 2
    assert summary.claims_rejected == 0
    assert summary.contradictions_found == 1
    assert summary.consensus_topics == 1
    assert summary.passed is True
    assert len(summary.graph_sha256) == 64

    expected_files = (
        report_dir / "report.md",
        report_dir / "report.html",
        report_dir / "report.sarif",
        report_dir / "report.json",
        report_dir / "references.bib",
        report_dir / "references.ris",
        report_dir / "summary.json",
    )
    assert summary.outputs_written == tuple(str(p) for p in expected_files)
    for out_file in expected_files:
        assert out_file.is_file()

    assert "# SciGraph Contradiction & Experiment Briefing" in (
        report_dir / "report.md"
    ).read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in (report_dir / "report.html").read_text(encoding="utf-8")

    sarif_doc = json.loads((report_dir / "report.sarif").read_text(encoding="utf-8"))
    assert sarif_doc["version"] == "2.1.0"
    assert len(sarif_doc["runs"][0]["results"]) == 1

    bundle_doc = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert len(bundle_doc["papers"]) == 2
    assert len(bundle_doc["claims"]) == 2
    assert len(bundle_doc["contradictions"]) == 1
    assert len(bundle_doc["experiments"]) == 1

    assert "@article{paper-alpha," in (report_dir / "references.bib").read_text(
        encoding="utf-8"
    )
    assert "TY  - JOUR" in (report_dir / "references.ris").read_text(encoding="utf-8")

    summary_json = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_json["graph_sha256"] == summary.graph_sha256
    assert summary_json["passed"] is True

    loaded_graph = GraphSQLiteStore(store_path).load_graph()
    assert len(loaded_graph.papers) == 2
    assert len(loaded_graph.claims) == 2
    assert len(loaded_graph.edges) == 1

    # Re-running with identical input produces identical graph_sha256.
    second_summary = run_pipeline(config)
    assert second_summary.graph_sha256 == summary.graph_sha256


def test_run_pipeline_fail_on_contradictions_gate(tmp_path: Path) -> None:
    corpus_path = _write_corpus_json(
        tmp_path / "corpus.json",
        _make_contradicting_corpus(),
    )
    store_path = tmp_path / "graph.json"
    report_dir = tmp_path / "reports"

    config = PipelineConfig(
        input_path=str(corpus_path),
        store_path=str(store_path),
        report_dir=str(report_dir),
        fail_on_contradictions=True,
        min_verified_papers=1,
    )
    summary = run_pipeline(config)

    assert summary.contradictions_found == 1
    assert summary.claims_rejected == 0
    assert summary.passed is False

    loaded_graph = load_graph_json(store_path)
    assert len(loaded_graph.papers) == 2
    assert len(loaded_graph.claims) == 2


def test_run_pipeline_invalid_store_suffix_raises_value_error(tmp_path: Path) -> None:
    corpus_path = _write_corpus_json(
        tmp_path / "corpus.json",
        _make_contradicting_corpus(),
    )
    config = PipelineConfig(
        input_path=str(corpus_path),
        store_path=str(tmp_path / "invalid.txt"),
        report_dir=str(tmp_path / "reports"),
    )

    with pytest.raises(ValueError, match="Unsupported store suffix"):
        run_pipeline(config)


def test_pipeline_config_rejects_negative_min_verified_papers() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(
            input_path="corpus.json",
            store_path="graph.db",
            report_dir="reports",
            min_verified_papers=-1,
        )
