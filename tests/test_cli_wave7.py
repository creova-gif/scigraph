import json
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

import scigraph
from evals.benchmark import BENCHMARK_30_PAPERS
from ingest import extract_paper_from_layout
from scigraph.cli import main
from scigraph.diagrams import export_graphviz_dot, export_mermaid_flowchart
from scigraph.doctor import DoctorReport, run_doctor


def _write_benchmark_store(tmp_path: Path, count: int = 30) -> Path:
    papers = [
        extract_paper_from_layout(spec.paper_id, spec.blocks).model_dump(mode="json")
        for spec in BENCHMARK_30_PAPERS[:count]
    ]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"papers": papers}), encoding="utf-8")
    store_path = tmp_path / "graph.db"
    assert main(["ingest", str(corpus_path), "--store", str(store_path)]) == 0
    return store_path


def test_wave7_lazy_exports() -> None:
    assert "DoctorReport" in scigraph.__all__
    assert "export_graphviz_dot" in scigraph.__all__
    assert "export_mermaid_flowchart" in scigraph.__all__
    assert "run_doctor" in scigraph.__all__

    assert scigraph.DoctorReport is DoctorReport
    assert scigraph.export_graphviz_dot is export_graphviz_dot
    assert scigraph.export_mermaid_flowchart is export_mermaid_flowchart
    assert scigraph.run_doctor is run_doctor


def test_diagram_mermaid_and_dot_stdout_and_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_path = _write_benchmark_store(tmp_path, count=30)
    capsys.readouterr()

    rc_mmd = main(["diagram", "--store", str(store_path), "--format", "mermaid"])
    out_mmd = capsys.readouterr()
    assert rc_mmd == 0
    assert out_mmd.out.startswith("flowchart LR\n")
    assert "CONFLICT:" in out_mmd.out

    mmd_file = tmp_path / "graph.mmd"
    rc_mmd_file = main(
        [
            "diagram",
            "--store",
            str(store_path),
            "--format",
            "mermaid",
            "--output",
            str(mmd_file),
        ]
    )
    capsys.readouterr()
    assert rc_mmd_file == 0
    assert mmd_file.read_text(encoding="utf-8") == out_mmd.out

    rc_dot = main(["diagram", "--store", str(store_path), "--format", "dot"])
    out_dot = capsys.readouterr()
    assert rc_dot == 0
    assert out_dot.out.startswith("digraph SciGraph {\n")
    assert "subgraph cluster_" in out_dot.out
    assert "CONFLICT:" in out_dot.out

    dot_file = tmp_path / "graph.dot"
    rc_dot_file = main(
        [
            "diagram",
            "--store",
            str(store_path),
            "--format",
            "dot",
            "--output",
            str(dot_file),
        ]
    )
    capsys.readouterr()
    assert rc_dot_file == 0
    assert dot_file.read_text(encoding="utf-8") == out_dot.out

    rc_graphml = main(["diagram", "--store", str(store_path), "--format", "graphml"])
    out_graphml = capsys.readouterr()
    assert rc_graphml == 0
    assert "<graphml " in out_graphml.out
    assert "<graph id=\"scigraph\"" in out_graphml.out


def test_protocols_markdown_and_json_stdout_and_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_path = _write_benchmark_store(tmp_path, count=30)
    capsys.readouterr()

    rc_md = main(["protocols", "--store", str(store_path)])
    out_md = capsys.readouterr()
    assert rc_md == 0
    assert out_md.out.startswith("# Experiment Protocols\n")
    assert "## proto-" in out_md.out
    assert "[PRE_REGISTRATION]" in out_md.out

    md_file = tmp_path / "protocols.md"
    rc_md_file = main(
        [
            "protocols",
            "--store",
            str(store_path),
            "--format",
            "markdown",
            "--output",
            str(md_file),
        ]
    )
    capsys.readouterr()
    assert rc_md_file == 0
    assert md_file.read_text(encoding="utf-8") == out_md.out

    rc_json = main(["protocols", "--store", str(store_path), "--format", "json"])
    out_json = capsys.readouterr()
    assert rc_json == 0
    payload = json.loads(out_json.out)
    assert "protocols" in payload
    assert isinstance(payload["protocols"], list)
    assert len(payload["protocols"]) > 0
    first = payload["protocols"][0]
    assert first["protocol_id"].startswith("proto-")
    assert first["priority_rank"] == 1
    assert len(first["steps"]) == 4

    json_file = tmp_path / "protocols.json"
    rc_json_file = main(
        [
            "protocols",
            "--store",
            str(store_path),
            "--format",
            "json",
            "--output",
            str(json_file),
        ]
    )
    capsys.readouterr()
    assert rc_json_file == 0
    assert json_file.read_text(encoding="utf-8") == out_json.out


class _Py312Info(NamedTuple):
    major: int = 3
    minor: int = 12
    micro: int = 0
    releaselevel: str = "final"
    serial: int = 0


def test_doctor_pass_and_fail_workspace_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "version_info", _Py312Info())
    rc_ok = main(["doctor", "--workspace-root", str(tmp_path), "--json"])
    out_ok = capsys.readouterr()
    assert rc_ok == 0
    report_ok = json.loads(out_ok.out)
    assert report_ok["all_passed"] is True
    check_names = {c["name"] for c in report_ok["checks"]}
    assert {
        "python_version",
        "flate_pdf_roundtrip",
        "benchmark_gate",
        "workspace_writable",
    } <= check_names

    rc_ok_text = main(["doctor", "--workspace-root", str(tmp_path)])
    out_ok_text = capsys.readouterr()
    assert rc_ok_text == 0
    assert "[PASS] python_version:" in out_ok_text.out
    assert "[PASS] workspace_writable:" in out_ok_text.out

    missing_dir = tmp_path / "does-not-exist"
    rc_fail = main(["doctor", "--workspace-root", str(missing_dir)])
    out_fail = capsys.readouterr()
    assert rc_fail == 1
    assert "[FAIL] workspace_writable:" in out_fail.out

    rc_fail_json = main(["doctor", "--workspace-root", str(missing_dir), "--json"])
    out_fail_json = capsys.readouterr()
    assert rc_fail_json == 1
    report_fail = json.loads(out_fail_json.out)
    assert report_fail["all_passed"] is False


def test_wave7_error_exit_code_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_store = tmp_path / "missing.db"
    bad_ext_store = tmp_path / "graph.txt"
    bad_ext_store.write_text("bad", encoding="utf-8")

    assert main(["diagram", "--store", str(missing_store), "--format", "mermaid"]) == 2
    assert main(["diagram", "--store", str(bad_ext_store), "--format", "dot"]) == 2
    assert main(["protocols", "--store", str(missing_store)]) == 2
    assert main(["protocols", "--store", str(bad_ext_store), "--format", "json"]) == 2
    capsys.readouterr()

    store_path = _write_benchmark_store(tmp_path, count=4)
    capsys.readouterr()

    missing_parent_out = tmp_path / "no-such-dir" / "out.mmd"
    rc_diagram_out = main(
        [
            "diagram",
            "--store",
            str(store_path),
            "--format",
            "mermaid",
            "--output",
            str(missing_parent_out),
        ]
    )
    assert rc_diagram_out == 2

    rc_protocols_out = main(
        [
            "protocols",
            "--store",
            str(store_path),
            "--output",
            str(tmp_path / "no-such-dir" / "protocols.md"),
        ]
    )
    assert rc_protocols_out == 2

    assert main(["diagram", "--store", str(store_path), "--format", "svg"]) == 2
    capsys.readouterr()
