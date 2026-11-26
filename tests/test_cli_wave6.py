import json
from pathlib import Path

import pytest

import scigraph
from evals.benchmark import BENCHMARK_30_PAPERS
from graph.claim_graph import ClaimGraph
from graph.store import save_graph_json
from ingest import extract_paper_from_layout
from scigraph.alerts import AlertPayload
from scigraph.cli import build_parser, main
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    Paper,
    PaperSection,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)
from scigraph.security import hash_bearer_token
from scigraph.server import SciGraphApp
from scigraph.workspace import WorkspaceManager


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


def _write_alias_store(tmp_path: Path) -> Path:
    claim_text_a = "CRISPR-Cas9 reduced IL-6 in sepsis (n=60, p=0.01)."
    full_text_a = f"DOI: 10.1000/alias-1\n{claim_text_a}"
    claim_start_a = full_text_a.index(claim_text_a)

    claim_text_b = "CRISPR/Cas9 reduced interleukin-6 in sepsis (n=80, p=0.02)."
    full_text_b = f"DOI: 10.1000/alias-2\n{claim_text_b}"
    claim_start_b = full_text_b.index(claim_text_b)

    paper_a = Paper(
        paper_id="alias-p1",
        title="CRISPR Paper 1",
        doi="10.1000/alias-1",
        authors=("Alice",),
        publication_year=2024,
        venue="SciGraph Journal",
        full_text=full_text_a,
        sections=(
            PaperSection(
                kind=SectionKind.RESULTS,
                heading="Results",
                text=claim_text_a,
                start_char=claim_start_a,
                end_char=claim_start_a + len(claim_text_a),
            ),
        ),
    )
    paper_b = Paper(
        paper_id="alias-p2",
        title="CRISPR Paper 2",
        doi="10.1000/alias-2",
        authors=("Bob",),
        publication_year=2025,
        venue="SciGraph Journal",
        full_text=full_text_b,
        sections=(
            PaperSection(
                kind=SectionKind.RESULTS,
                heading="Results",
                text=claim_text_b,
                start_char=claim_start_b,
                end_char=claim_start_b + len(claim_text_b),
            ),
        ),
    )
    claim_a = ScientificClaim(
        claim_id="c-alias-1",
        paper_id="alias-p1",
        doi="10.1000/alias-1",
        claim_tuple=ClaimTuple(
            intervention="CRISPR-Cas9",
            condition="sepsis",
            outcome="IL-6",
            direction=EffectDirection.DECREASES,
        ),
        statistics=StatisticalEvidence(
            sample_size=60,
            sample_size_raw="n=60",
            p_value=0.01,
            p_operator=ComparisonOperator.EQ,
            p_value_raw="p=0.01",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=claim_start_a,
            end_char=claim_start_a + len(claim_text_a),
            verbatim_text=claim_text_a,
        ),
    )
    claim_b = ScientificClaim(
        claim_id="c-alias-2",
        paper_id="alias-p2",
        doi="10.1000/alias-2",
        claim_tuple=ClaimTuple(
            intervention="CRISPR/Cas9",
            condition="sepsis",
            outcome="interleukin-6",
            direction=EffectDirection.DECREASES,
        ),
        statistics=StatisticalEvidence(
            sample_size=80,
            sample_size_raw="n=80",
            p_value=0.02,
            p_operator=ComparisonOperator.EQ,
            p_value_raw="p=0.02",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=claim_start_b,
            end_char=claim_start_b + len(claim_text_b),
            verbatim_text=claim_text_b,
        ),
    )

    graph = ClaimGraph()
    graph.add_paper(paper_a)
    graph.add_paper(paper_b)
    graph.add_verified_claim(paper_a, claim_a)
    graph.add_verified_claim(paper_b, claim_b)
    graph.build_edges()

    store_path = tmp_path / "aliases.json"
    save_graph_json(graph, store_path)
    return store_path


def test_wave6_lazy_exports() -> None:
    assert hasattr(scigraph, "AlertPayload")
    assert hasattr(scigraph, "build_alert_payload")
    assert hasattr(scigraph, "dispatch_webhook_alert")
    assert scigraph.AlertPayload is AlertPayload


def test_prioritize_json_and_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_path = _write_benchmark_store(tmp_path, count=30)
    capsys.readouterr()

    rc_json = main(["prioritize", "--store", str(store_path), "--json"])
    out_json = capsys.readouterr()
    assert rc_json == 0
    payload = json.loads(out_json.out)
    assert "prioritized" in payload
    assert isinstance(payload["prioritized"], list)
    assert len(payload["prioritized"]) > 0
    first = payload["prioritized"][0]
    assert first["rank"] == 1
    assert "experiment_id" in first
    assert "priority_score" in first

    rc_text = main(["prioritize", "--store", str(store_path)])
    out_text = capsys.readouterr()
    assert rc_text == 0
    assert "#1 " in out_text.out
    assert "score=" in out_text.out


def test_canonicalize_json_and_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_path = _write_alias_store(tmp_path)

    rc_json = main(["canonicalize", "--store", str(store_path), "--json"])
    out_json = capsys.readouterr()
    assert rc_json == 0
    payload = json.loads(out_json.out)
    assert len(payload["clusters"]) == 1
    cluster = payload["clusters"][0]
    assert cluster["intervention"] == "CRISPR-Cas9"
    assert cluster["outcome"] == "IL-6"
    assert cluster["claim_ids"] == ["c-alias-1", "c-alias-2"]

    rc_text = main(["canonicalize", "--store", str(store_path)])
    out_text = capsys.readouterr()
    assert rc_text == 0
    assert "Cluster: CRISPR-Cas9 -> IL-6" in out_text.out
    assert "c-alias-1, c-alias-2" in out_text.out


def test_alert_dry_run_ssrf_and_mocked_dispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = _write_benchmark_store(tmp_path, count=30)
    capsys.readouterr()

    rc_dry = main(["alert", "--store", str(store_path), "--json"])
    out_dry = capsys.readouterr()
    assert rc_dry == 0
    dry_payload = json.loads(out_dry.out)
    assert dry_payload["event_type"] == "contradiction_detected"
    assert dry_payload["severity"] == "warning"
    assert len(dry_payload["contradiction_ids"]) > 0

    rc_ssrf = main(
        [
            "alert",
            "--store",
            str(store_path),
            "--webhook-url",
            "http://127.0.0.1:9000/hook",
        ]
    )
    err_ssrf = capsys.readouterr()
    assert rc_ssrf == 2
    assert "rejected" in err_ssrf.err.lower()

    calls: list[tuple[str, AlertPayload]] = []

    def _fake_ok(url: str, payload: AlertPayload) -> tuple[bool, int, str]:
        calls.append((url, payload))
        return (True, 200, "Webhook returned HTTP 200")

    monkeypatch.setattr("scigraph.cli.dispatch_webhook_alert", _fake_ok)
    rc_ok = main(
        [
            "alert",
            "--store",
            str(store_path),
            "--webhook-url",
            "https://hooks.example.com/services/test",
            "--json",
        ]
    )
    out_ok = capsys.readouterr()
    assert rc_ok == 0
    ok_payload = json.loads(out_ok.out)
    assert ok_payload["ok"] is True
    assert ok_payload["status"] == 200
    assert len(calls) == 1

    def _fake_fail(url: str, payload: AlertPayload) -> tuple[bool, int, str]:
        return (False, 503, "Webhook returned HTTP 503")

    monkeypatch.setattr("scigraph.cli.dispatch_webhook_alert", _fake_fail)
    rc_fail = main(
        [
            "alert",
            "--store",
            str(store_path),
            "--webhook-url",
            "https://hooks.example.com/services/test",
        ]
    )
    capsys.readouterr()
    assert rc_fail == 1


def test_serve_wave6_flags_and_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser()
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(
        json.dumps(
            [
                {
                    "token_sha256": hash_bearer_token("secret-token"),
                    "org_id": "acme",
                    "role": "admin",
                    "label": "test-admin",
                }
            ]
        ),
        encoding="utf-8",
    )
    ws_root = tmp_path / "workspaces"
    WorkspaceManager(ws_root).init_workspace(
        org_id="acme",
        workspace_id="ws1",
        name="WS 1",
    )

    parsed = parser.parse_args(
        [
            "serve",
            "--tokens",
            str(tokens_path),
            "--rate-limit",
            "15",
            "--rate-window",
            "30.0",
            "--workspace-root",
            str(ws_root),
            "--org",
            "acme",
            "--workspace",
            "ws1",
        ]
    )
    assert parsed.tokens == str(tokens_path)
    assert parsed.rate_limit == 15
    assert parsed.rate_window == 30.0
    assert parsed.workspace_root == str(ws_root)
    assert parsed.org == "acme"
    assert parsed.workspace == "ws1"

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
    rc = main(
        [
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8999",
            "--tokens",
            str(tokens_path),
            "--rate-limit",
            "15",
            "--workspace-root",
            str(ws_root),
            "--org",
            "acme",
            "--workspace",
            "ws1",
        ]
    )
    assert rc == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8999
    assert captured["served"] is True
    assert captured["closed"] is True
    app = captured["app"]
    assert isinstance(app, SciGraphApp)
    assert app.auth_gate is not None
    assert app.auth_gate.enabled is True
    assert app.rate_limiter is not None
    assert app.workspace_manager is not None
    assert app.org_id == "acme"
    assert app.workspace_id == "ws1"
