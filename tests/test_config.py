import json
from pathlib import Path

import pytest

from evals.benchmark import BENCHMARK_30_PAPERS
from graph.store import GraphSQLiteStore
from ingest import extract_paper_from_layout
from scigraph import SciGraphConfig, load_scigraph_config
from scigraph.cli import main
from scigraph.server import SciGraphApp


def test_load_scigraph_config_defaults_when_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = load_scigraph_config()
    assert cfg == SciGraphConfig()
    assert cfg.default_store is None
    assert cfg.workspace_root is None
    assert cfg.default_org == "default-org"
    assert cfg.server_host == "127.0.0.1"
    assert cfg.server_port == 8765
    assert cfg.rate_limit is None
    assert cfg.rate_window_seconds == 60.0


def test_load_scigraph_config_valid_scigraph_table(tmp_path: Path) -> None:
    cfg_file = tmp_path / "scigraph.toml"
    cfg_file.write_text(
        "\n".join(
            [
                "[scigraph]",
                'default_store = "graph.sqlite"',
                'workspace_root = "/tmp/scigraph-ws"',
                'default_org = "bio-lab"',
                'server_host = "0.0.0.0"',
                "server_port = 9000",
                "rate_limit = 120",
                "rate_window_seconds = 30",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_scigraph_config(cfg_file)
    assert cfg.default_store == "graph.sqlite"
    assert cfg.workspace_root == "/tmp/scigraph-ws"
    assert cfg.default_org == "bio-lab"
    assert cfg.server_host == "0.0.0.0"
    assert cfg.server_port == 9000
    assert cfg.rate_limit == 120
    assert cfg.rate_window_seconds == 30.0


def test_load_scigraph_config_top_level_keys_without_table(tmp_path: Path) -> None:
    cfg_file = tmp_path / "custom.toml"
    cfg_file.write_text(
        'default_org = "top-level-org"\nserver_port = 8080\n',
        encoding="utf-8",
    )
    cfg = load_scigraph_config(cfg_file)
    assert cfg.default_org == "top-level-org"
    assert cfg.server_port == 8080


@pytest.mark.parametrize(
    "toml_content",
    [
        "[scigraph]\nserver_port = 0\n",
        "[scigraph]\nserver_port = 70000\n",
        "[scigraph]\nrate_limit = 0\n",
        "[scigraph]\nrate_window_seconds = 0\n",
        "[scigraph]\nunknown_key = true\n",
        "not = [valid toml",
    ],
)
def test_load_scigraph_config_invalid_values_raise_value_error(
    tmp_path: Path,
    toml_content: str,
) -> None:
    cfg_file = tmp_path / "bad.toml"
    cfg_file.write_text(toml_content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_scigraph_config(cfg_file)


def test_load_scigraph_config_missing_or_directory_raises_value_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(ValueError):
        load_scigraph_config(missing)

    with pytest.raises(ValueError):
        load_scigraph_config(tmp_path)


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--version"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "scigraph 0.1.0"


def test_cli_config_json_and_text_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg_file = tmp_path / "scigraph.toml"
    cfg_file.write_text(
        '[scigraph]\ndefault_org = "cli-org"\nserver_port = 9123\n',
        encoding="utf-8",
    )

    rc = main(["config", "--path", str(cfg_file), "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["default_org"] == "cli-org"
    assert payload["server_port"] == 9123
    assert payload["server_host"] == "127.0.0.1"

    monkeypatch.chdir(tmp_path)
    rc_text = main(["config"])
    captured_text = capsys.readouterr()
    assert rc_text == 0
    assert "default_org=cli-org" in captured_text.out
    assert "server=127.0.0.1:9123" in captured_text.out

    rc_err = main(["config", "--path", str(tmp_path / "nope.toml"), "--json"])
    captured_err = capsys.readouterr()
    assert rc_err == 2
    assert "Failed to load config" in captured_err.err


def test_cli_query_sqlite_uses_indexed_pushdown_without_load_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    papers = [
        extract_paper_from_layout(spec.paper_id, spec.blocks).model_dump(mode="json")
        for spec in BENCHMARK_30_PAPERS[:2]
    ]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"papers": papers}), encoding="utf-8")

    db_path = tmp_path / "graph.db"
    json_path = tmp_path / "graph.json"
    assert main(["ingest", str(corpus_path), "--store", str(db_path)]) == 0
    assert main(["ingest", str(corpus_path), "--store", str(json_path)]) == 0
    capsys.readouterr()

    def _fail_load_graph(self: GraphSQLiteStore) -> object:
        raise AssertionError("GraphSQLiteStore.load_graph should not be called by scigraph query")

    monkeypatch.setattr(GraphSQLiteStore, "load_graph", _fail_load_graph)

    target_paper = BENCHMARK_30_PAPERS[0].paper_id
    rc_db = main(["query", "--store", str(db_path), "--paper-id", target_paper, "--json"])
    out_db = capsys.readouterr()
    assert rc_db == 0
    db_claims = json.loads(out_db.out)
    assert len(db_claims) > 0
    assert all(claim["paper_id"] == target_paper for claim in db_claims)

    rc_json = main(["query", "--store", str(json_path), "--paper-id", target_paper, "--json"])
    out_json = capsys.readouterr()
    assert rc_json == 0
    json_claims = json.loads(out_json.out)
    assert [c["claim_id"] for c in db_claims] == [c["claim_id"] for c in json_claims]


def test_cli_serve_loads_scigraph_toml_defaults_and_allows_cli_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    papers = [
        extract_paper_from_layout(spec.paper_id, spec.blocks).model_dump(mode="json")
        for spec in BENCHMARK_30_PAPERS[:1]
    ]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"papers": papers}), encoding="utf-8")

    default_store = tmp_path / "default.db"
    override_store = tmp_path / "override.db"
    assert main(["ingest", str(corpus_path), "--store", str(default_store)]) == 0
    assert main(["ingest", str(corpus_path), "--store", str(override_store)]) == 0
    capsys.readouterr()

    ws_default = tmp_path / "ws-default"
    ws_override = tmp_path / "ws-override"

    cfg_file = tmp_path / "scigraph.toml"
    cfg_file.write_text(
        "\n".join(
            [
                "[scigraph]",
                f'default_store = "{default_store}"',
                f'workspace_root = "{ws_default}"',
                'default_org = "toml-org"',
                "rate_limit = 25",
                "rate_window_seconds = 15",
            ]
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    class _FakeServer:
        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    def _fake_create_http_server(
        host: str,
        port: int,
        app: SciGraphApp,
    ) -> _FakeServer:
        captured["host"] = host
        captured["port"] = port
        captured["app"] = app
        return _FakeServer()

    monkeypatch.setattr("scigraph.cli.create_http_server", _fake_create_http_server)
    monkeypatch.chdir(tmp_path)

    rc_defaults = main(["serve"])
    assert rc_defaults == 0
    app_default = captured["app"]
    assert isinstance(app_default, SciGraphApp)
    assert app_default.org_id == "toml-org"
    assert app_default.rate_limiter is not None
    assert app_default.rate_limiter._max_requests == 25
    assert app_default.rate_limiter._window_seconds == 15.0
    assert app_default.workspace_manager is not None
    assert app_default.workspace_manager.root_dir == ws_default
    assert len(app_default.graph.claims) > 0

    captured.clear()
    rc_override = main(
        [
            "serve",
            "--store",
            str(override_store),
            "--workspace-root",
            str(ws_override),
            "--org",
            "cli-org",
            "--rate-limit",
            "5",
            "--rate-window",
            "10.0",
        ]
    )
    assert rc_override == 0
    app_override = captured["app"]
    assert isinstance(app_override, SciGraphApp)
    assert app_override.org_id == "cli-org"
    assert app_override.rate_limiter is not None
    assert app_override.rate_limiter._max_requests == 5
    assert app_override.rate_limiter._window_seconds == 10.0
    assert app_override.workspace_manager is not None
    assert app_override.workspace_manager.root_dir == ws_override
