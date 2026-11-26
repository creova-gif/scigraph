"""Deterministic CLI and lazy-export tests for Wave 5 commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scigraph
from scigraph.cli import build_parser, main
from scigraph.models import Paper, PaperSection, SectionKind
from scigraph.workspace import AuditEvent


def _make_sample_paper(
    *,
    paper_id: str = "paper-alpha",
    doi: str = "10.1000/scigraph.2026.001",
    direction_verb: str = "decreased",
    effect_size: str = "-0.82",
    sample_size: int = 240,
    p_clause: str = "p < 0.001",
) -> Paper:
    abstract = (
        f"DOI: {doi}\n"
        f"Results: Treatment with Metformin under insulin resistance "
        f"{direction_verb} fasting glucose compared with placebo "
        f"(d = {effect_size}; n = {sample_size}, {p_clause})."
    )
    section = PaperSection(
        kind=SectionKind.ABSTRACT,
        heading="Abstract",
        text=abstract,
        start_char=0,
        end_char=len(abstract),
    )
    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=f"Study {paper_id}",
        authors=("Alice Smith",),
        publication_year=2026,
        venue="Journal of Metabolic Research",
        full_text=abstract,
        sections=(section,),
    )


def _write_corpus(path: Path, papers: list[Paper]) -> Path:
    payload = {"papers": [paper.model_dump(mode="json") for paper in papers]}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_wave5_lazy_package_exports() -> None:
    expected = (
        "AuthGate",
        "PipelineConfig",
        "PipelineSummary",
        "ProvenanceManifest",
        "SlidingWindowRateLimiter",
        "build_provenance_manifest",
        "run_pipeline",
        "verify_provenance_manifest",
    )
    for symbol in expected:
        assert symbol in scigraph.__all__
        assert hasattr(scigraph, symbol)


def test_fetch_arxiv_writes_atomic_corpus_and_handles_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()
    parsed = parser.parse_args(
        [
            "fetch",
            "--source",
            "arxiv",
            "--query",
            "metformin",
            "--output",
            str(tmp_path / "fetched.json"),
        ]
    )
    assert parsed.command == "fetch"
    assert parsed.max_results == 10

    sample = _make_sample_paper(paper_id="arxiv:2601.00001")
    recorded: dict[str, object] = {}

    def _fake_fetch_arxiv(query: str, max_results: int = 10) -> list[Paper]:
        recorded["query"] = query
        recorded["max_results"] = max_results
        return [sample]

    monkeypatch.setattr("scigraph.cli.fetch_arxiv_papers", _fake_fetch_arxiv)

    output_path = tmp_path / "fetched.json"
    rc = main(
        [
            "fetch",
            "--source",
            "arxiv",
            "--query",
            "metformin glucose",
            "--output",
            str(output_path),
            "--max-results",
            "5",
        ]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert "Fetched 1 papers from arxiv" in out.out
    assert recorded == {"query": "metformin glucose", "max_results": 5}

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(written["papers"]) == 1
    assert written["papers"][0]["paper_id"] == "arxiv:2601.00001"

    def _failing_fetch(query: str, max_results: int = 10) -> list[Paper]:
        raise ValueError("invalid query")

    monkeypatch.setattr("scigraph.cli.fetch_arxiv_papers", _failing_fetch)
    rc_err = main(
        [
            "fetch",
            "--source",
            "arxiv",
            "--query",
            " ",
            "--output",
            str(tmp_path / "err.json"),
        ]
    )
    assert rc_err == 2


def test_provenance_build_and_verify_intact_and_tampered(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _write_corpus(tmp_path / "corpus.json", [_make_sample_paper()])
    store_path = tmp_path / "graph.json"
    assert main(["ingest", str(corpus), "--store", str(store_path)]) == 0
    capsys.readouterr()

    audit_path = tmp_path / "audit.jsonl"
    audit_event = AuditEvent(
        event_id="evt-1",
        timestamp_utc="2026-11-26T00:00:00+00:00",
        org_id="org-1",
        workspace_id="ws-1",
        action="ingest",
        paper_count=1,
        claim_count=1,
        status="ok",
        detail="initial ingest",
    )
    audit_path.write_text(audit_event.model_dump_json() + "\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    rc_build = main(
        [
            "provenance",
            "build",
            "--store",
            str(store_path),
            "--output",
            str(manifest_path),
            "--audit-log",
            str(audit_path),
        ]
    )
    capsys.readouterr()
    assert rc_build == 0
    assert manifest_path.is_file()

    rc_verify_ok = main(
        [
            "provenance",
            "verify",
            "--store",
            str(store_path),
            "--manifest",
            str(manifest_path),
            "--audit-log",
            str(audit_path),
            "--json",
        ]
    )
    ok_out = capsys.readouterr()
    assert rc_verify_ok == 0
    ok_payload = json.loads(ok_out.out)
    assert ok_payload == {"intact": True, "reasons": []}

    # Tamper with manifest graph_sha256 to trigger exit code 1.
    manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_doc["graph_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest_doc), encoding="utf-8")

    rc_verify_tampered = main(
        [
            "provenance",
            "verify",
            "--store",
            str(store_path),
            "--manifest",
            str(manifest_path),
            "--audit-log",
            str(audit_path),
            "--json",
        ]
    )
    tampered_out = capsys.readouterr()
    assert rc_verify_tampered == 1
    tampered_payload = json.loads(tampered_out.out)
    assert tampered_payload["intact"] is False
    assert "graph_sha256_mismatch" in tampered_payload["reasons"]


def test_pipeline_pass_and_fail_on_contradictions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paper_a = _make_sample_paper(
        paper_id="paper-alpha",
        doi="10.1000/scigraph.2026.001",
        direction_verb="decreased",
        effect_size="-0.82",
        sample_size=240,
        p_clause="p < 0.001",
    )
    paper_b = _make_sample_paper(
        paper_id="paper-beta",
        doi="10.1000/scigraph.2026.002",
        direction_verb="increased",
        effect_size="0.45",
        sample_size=120,
        p_clause="p = 0.020",
    )
    corpus = _write_corpus(tmp_path / "contradicting.json", [paper_a, paper_b])

    store_pass = tmp_path / "pass.db"
    report_pass = tmp_path / "reports_pass"
    rc_pass = main(
        [
            "pipeline",
            "--input",
            str(corpus),
            "--store",
            str(store_pass),
            "--report-dir",
            str(report_pass),
            "--format",
            "markdown",
            "json",
            "--json",
        ]
    )
    pass_out = capsys.readouterr()
    assert rc_pass == 0
    pass_summary = json.loads(pass_out.out)
    assert pass_summary["passed"] is True
    assert pass_summary["contradictions_found"] == 1
    assert (report_pass / "report.md").is_file()
    assert (report_pass / "report.json").is_file()
    assert (report_pass / "summary.json").is_file()

    store_fail = tmp_path / "fail.db"
    report_fail = tmp_path / "reports_fail"
    rc_fail = main(
        [
            "pipeline",
            "--input",
            str(corpus),
            "--store",
            str(store_fail),
            "--report-dir",
            str(report_fail),
            "--fail-on-contradictions",
        ]
    )
    fail_out = capsys.readouterr()
    assert rc_fail == 1
    assert "Pipeline passed=False" in fail_out.out


def test_wave5_error_exit_code_2(tmp_path: Path) -> None:
    # Missing store for provenance build
    assert (
        main(
            [
                "provenance",
                "build",
                "--store",
                str(tmp_path / "missing.json"),
                "--output",
                str(tmp_path / "manifest.json"),
            ]
        )
        == 2
    )

    # Missing input for pipeline
    assert (
        main(
            [
                "pipeline",
                "--input",
                str(tmp_path / "missing_corpus.json"),
                "--store",
                str(tmp_path / "out.db"),
                "--report-dir",
                str(tmp_path / "reports"),
            ]
        )
        == 2
    )

    # Invalid store extension for pipeline
    corpus = _write_corpus(tmp_path / "ok.json", [_make_sample_paper()])
    assert (
        main(
            [
                "pipeline",
                "--input",
                str(corpus),
                "--store",
                str(tmp_path / "bad.txt"),
                "--report-dir",
                str(tmp_path / "reports"),
            ]
        )
        == 2
    )
