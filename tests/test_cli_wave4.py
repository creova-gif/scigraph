import json
from pathlib import Path

import pytest

import scigraph
from evals.benchmark import BENCHMARK_30_PAPERS
from ingest import extract_paper_from_layout
from scigraph.cli import build_parser, main


def _write_json_corpus(
    tmp_path: Path,
    start: int = 0,
    count: int = 2,
    name: str = "corpus.json",
) -> Path:
    papers = [
        extract_paper_from_layout(spec.paper_id, spec.blocks).model_dump(mode="json")
        for spec in BENCHMARK_30_PAPERS[start : start + count]
    ]
    corpus_path = tmp_path / name
    corpus_path.write_text(json.dumps({"papers": papers}), encoding="utf-8")
    return corpus_path


def test_wave4_package_exports() -> None:
    assert hasattr(scigraph, "SciGraphApp")
    assert hasattr(scigraph, "WorkspaceManager")
    assert hasattr(scigraph, "diff_claim_graphs")
    assert hasattr(scigraph, "export_bibtex")
    assert hasattr(scigraph, "export_ris")


def test_serve_arg_parsing_and_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser()
    default_args = parser.parse_args(["serve"])
    assert default_args.command == "serve"
    assert default_args.host == "127.0.0.1"
    assert default_args.port == 8765
    assert default_args.store is None

    store_file = tmp_path / "graph.db"
    custom_args = parser.parse_args(
        ["serve", "--host", "0.0.0.0", "--port", "9090", "--store", str(store_file)]
    )
    assert custom_args.host == "0.0.0.0"
    assert custom_args.port == 9090
    assert custom_args.store == str(store_file)

    recorded: dict[str, object] = {}

    def _fake_run_server(
        host: str = "127.0.0.1",
        port: int = 8765,
        store_path: Path | None = None,
    ) -> None:
        recorded["host"] = host
        recorded["port"] = port
        recorded["store_path"] = store_path

    monkeypatch.setattr("scigraph.cli.run_server", _fake_run_server)
    rc = main(["serve", "--host", "127.0.0.1", "--port", "8777", "--store", str(store_file)])
    assert rc == 0
    assert recorded == {
        "host": "127.0.0.1",
        "port": 8777,
        "store_path": store_file,
    }


def test_consensus_json_and_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _write_json_corpus(tmp_path, count=4)
    store_path = tmp_path / "graph.db"
    assert main(["ingest", str(corpus), "--store", str(store_path)]) == 0
    capsys.readouterr()

    rc_json = main(["consensus", "--store", str(store_path), "--json"])
    out_json = capsys.readouterr()
    assert rc_json == 0
    payload = json.loads(out_json.out)
    assert "consensus" in payload
    assert "claim_scores" in payload
    assert isinstance(payload["consensus"], list)
    assert isinstance(payload["claim_scores"], dict)
    assert len(payload["consensus"]) > 0
    assert len(payload["claim_scores"]) > 0

    rc_text = main(["consensus", "--store", str(store_path)])
    out_text = capsys.readouterr()
    assert rc_text == 0
    assert "Topic:" in out_text.out
    assert "Scored claims:" in out_text.out


def test_diff_json_and_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_corpus = _write_json_corpus(tmp_path, start=0, count=2, name="baseline.json")
    current_corpus = _write_json_corpus(tmp_path, start=0, count=4, name="current.json")
    baseline_store = tmp_path / "baseline.db"
    current_store = tmp_path / "current.json.store.json"

    assert main(["ingest", str(baseline_corpus), "--store", str(baseline_store)]) == 0
    assert main(["ingest", str(current_corpus), "--store", str(current_store)]) == 0
    capsys.readouterr()

    rc_json = main(
        ["diff", "--baseline", str(baseline_store), "--current", str(current_store), "--json"]
    )
    out_json = capsys.readouterr()
    assert rc_json == 0
    diff_payload = json.loads(out_json.out)
    assert len(diff_payload["added_papers"]) == 2
    assert diff_payload["removed_papers"] == []
    assert len(diff_payload["added_claims"]) > 0

    rc_text = main(
        ["diff", "--baseline", str(baseline_store), "--current", str(current_store)]
    )
    out_text = capsys.readouterr()
    assert rc_text == 0
    assert "Diff: added_papers=2 removed_papers=0" in out_text.out


def test_export_refs_bibtex_and_ris(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _write_json_corpus(tmp_path, count=2)
    store_path = tmp_path / "refs.db"
    assert main(["ingest", str(corpus), "--store", str(store_path)]) == 0
    capsys.readouterr()

    rc_bib_stdout = main(["export-refs", "--store", str(store_path), "--format", "bibtex"])
    bib_stdout = capsys.readouterr()
    assert rc_bib_stdout == 0
    assert "@article{" in bib_stdout.out

    ris_out_path = tmp_path / "refs.ris"
    rc_ris_file = main(
        [
            "export-refs",
            "--store",
            str(store_path),
            "--format",
            "ris",
            "--output",
            str(ris_out_path),
        ]
    )
    capsys.readouterr()
    assert rc_ris_file == 0
    ris_content = ris_out_path.read_text(encoding="utf-8")
    assert "TY  - JOUR" in ris_content
    assert "ER  - " in ris_content


def test_workspace_init_ingest_audit_roundtrip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspaces"
    corpus = _write_json_corpus(tmp_path, count=2)

    rc_init = main(
        [
            "workspace",
            "init",
            "--root",
            str(root),
            "--org",
            "acme-bio",
            "--workspace",
            "trial-alpha",
            "--name",
            "Trial Alpha",
            "--json",
        ]
    )
    init_out = capsys.readouterr()
    assert rc_init == 0
    init_payload = json.loads(init_out.out)
    assert init_payload["org_id"] == "acme-bio"
    assert init_payload["workspace_id"] == "trial-alpha"
    assert init_payload["name"] == "Trial Alpha"

    rc_ingest = main(
        [
            "workspace",
            "ingest",
            "--root",
            str(root),
            "--org",
            "acme-bio",
            "--workspace",
            "trial-alpha",
            "--input",
            str(corpus),
            "--json",
        ]
    )
    ingest_out = capsys.readouterr()
    assert rc_ingest == 0
    ingest_payload = json.loads(ingest_out.out)
    assert ingest_payload["papers"] == 2
    assert ingest_payload["verified_claims"] > 0

    rc_audit = main(
        [
            "workspace",
            "audit",
            "--root",
            str(root),
            "--org",
            "acme-bio",
            "--workspace",
            "trial-alpha",
            "--json",
        ]
    )
    audit_out = capsys.readouterr()
    assert rc_audit == 0
    events = json.loads(audit_out.out)
    assert len(events) == 2
    assert events[0]["action"] == "verify"
    assert events[1]["action"] == "ingest"

    rc_audit_text = main(
        [
            "workspace",
            "audit",
            "--root",
            str(root),
            "--org",
            "acme-bio",
            "--workspace",
            "trial-alpha",
        ]
    )
    audit_text = capsys.readouterr()
    assert rc_audit_text == 0
    assert "[ingest]" in audit_text.out

    bundle_dir = tmp_path / "bundle-out"
    rc_export = main(
        [
            "workspace",
            "export-bundle",
            "--root",
            str(root),
            "--org",
            "acme-bio",
            "--workspace",
            "trial-alpha",
            "--output",
            str(bundle_dir),
            "--json",
        ]
    )
    export_out = capsys.readouterr()
    assert rc_export == 0
    manifest_payload = json.loads(export_out.out)
    assert manifest_payload["manifest_version"] == "1.0"
    assert len(manifest_payload["paper_hashes"]) == 2
    assert len(manifest_payload["claim_hashes"]) > 0
    assert (bundle_dir / "graph.json").exists()
    assert (bundle_dir / "provenance.json").exists()
    assert (bundle_dir / "workspace.json").exists()
    assert (bundle_dir / "audit.jsonl").exists()

    bundle_text_dir = tmp_path / "bundle-out-text"
    rc_export_text = main(
        [
            "workspace",
            "export-bundle",
            "--root",
            str(root),
            "--org",
            "acme-bio",
            "--workspace",
            "trial-alpha",
            "--output",
            str(bundle_text_dir),
        ]
    )
    export_text_out = capsys.readouterr()
    assert rc_export_text == 0
    assert "Exported workspace acme-bio/trial-alpha bundle to" in export_text_out.out


def test_wave4_error_exit_code_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_store = tmp_path / "missing.db"
    bad_ext_store = tmp_path / "invalid.txt"
    bad_ext_store.write_text("x", encoding="utf-8")

    assert main(["consensus", "--store", str(missing_store)]) == 2
    assert main(["diff", "--baseline", str(missing_store), "--current", str(bad_ext_store)]) == 2
    assert main(["export-refs", "--store", str(missing_store), "--format", "bibtex"]) == 2
    assert main(["serve", "--store", str(missing_store)]) == 2

    root = tmp_path / "workspaces"
    assert (
        main(
            [
                "workspace",
                "init",
                "--root",
                str(root),
                "--org",
                "../escape",
                "--workspace",
                "ws1",
                "--name",
                "Bad",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "workspace",
                "audit",
                "--root",
                str(root),
                "--org",
                "missing-org",
                "--workspace",
                "missing-ws",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "workspace",
                "ingest",
                "--root",
                str(root),
                "--org",
                "missing-org",
                "--workspace",
                "missing-ws",
                "--input",
                str(tmp_path / "no-such-corpus.json"),
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "workspace",
                "export-bundle",
                "--root",
                str(root),
                "--org",
                "missing-org",
                "--workspace",
                "missing-ws",
                "--output",
                str(tmp_path / "missing-bundle"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.err != ""
