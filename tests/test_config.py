import json
from pathlib import Path

import pytest

from scigraph import SciGraphConfig, load_scigraph_config
from scigraph.cli import main


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
