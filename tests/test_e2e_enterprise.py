from __future__ import annotations

import csv
import http.client
import json
import threading
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

from graph.store import load_graph_json
from ingest.corpus_loader import load_papers_from_path
from ingest.verifier import verify_paper_claims
from scigraph.diagrams import export_graphml, export_mermaid_flowchart
from scigraph.exporters import export_sarif_v210
from scigraph.provenance import ProvenanceManifest, verify_provenance_manifest
from scigraph.security import (
    AuthGate,
    SlidingWindowRateLimiter,
    TokenPolicy,
    hash_bearer_token,
)
from scigraph.server import SciGraphApp, create_http_server
from scigraph.workspace import AuditEvent, WorkspaceManager
from solver.symbolic import detect_contradictions


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


def _escape_pdf_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _http_request(
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body_bytes = resp.read()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, resp_headers, body_bytes.decode("utf-8")
    finally:
        conn.close()


def test_enterprise_end_to_end_lifecycle(tmp_path: Path) -> None:
    # 1. Initialize multi-tenant workspace
    wm = WorkspaceManager(tmp_path / "workspaces")
    org_id = "acme-bio"
    workspace_id = "prod-metabolic"
    wm.init_workspace(org_id, workspace_id, "ACME Metabolic Trials")

    # 2. Build mixed corpus (.csv + /FlateDecode .pdf) with contradictory claims
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    csv_path = corpus_dir / "01_metformin_increase.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "paper_id",
                "doi",
                "title",
                "authors",
                "publication_year",
                "venue",
                "abstract",
            ]
        )
        writer.writerow(
            [
                "paper-csv-001",
                "10.1000/e2e.csv.001",
                "Metformin activates AMPK under normoxia",
                "Alice Researcher; Bob Scientist",
                "2025",
                "Journal of Metabolic Studies",
                (
                    "Treatment with Metformin under normoxia increased AMPK "
                    "phosphorylation compared with vehicle (d=0.85; n=48, p<0.001)."
                ),
            ]
        )

    pdf_lines = [
        "DOI: 10.1000/e2e.pdf.002",
        "Title: Metformin suppresses AMPK phosphorylation in normoxic hepatocytes",
        (
            "Treatment with Metformin under normoxia decreased AMPK "
            "phosphorylation compared with vehicle (d=-0.72; n=52, p=0.002)."
        ),
    ]
    pdf_stream_ops = "\n".join(
        f"BT /F1 12 Tf ({_escape_pdf_literal(line)}) Tj ET" for line in pdf_lines
    )
    pdf_path = corpus_dir / "02_metformin_decrease.pdf"
    pdf_path.write_bytes(_build_flate_pdf(pdf_stream_ops.encode("utf-8")))

    papers = load_papers_from_path(corpus_dir)
    assert len(papers) == 2

    wm.ingest_papers(org_id, workspace_id, papers)
    workspace_graph = wm.load_graph(org_id, workspace_id)
    assert len(workspace_graph.papers) == 2
    assert len(workspace_graph.claims) >= 2

    # 3. Start live ThreadingHTTPServer wrapping SciGraphApp + AuthGate + RateLimiter
    raw_token = "enterprise-e2e-reader-token"
    auth_gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token(raw_token),
                org_id=org_id,
                role="reader",
                label="e2e-reader",
            )
        ]
    )
    rate_limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60.0)
    app = SciGraphApp(
        auth_gate=auth_gate,
        rate_limiter=rate_limiter,
        workspace_manager=wm,
        org_id=org_id,
        workspace_id=workspace_id,
    )

    server = create_http_server("127.0.0.1", 0, app)
    port = int(server.server_address[1])
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    auth_headers = {"Authorization": f"Bearer {raw_token}"}
    try:
        # 4. Exercise live HTTP endpoints
        head_status, _, head_body = _http_request(port, "HEAD", "/health")
        assert head_status == 200
        assert head_body == ""

        ui_status, ui_headers, ui_body = _http_request(
            port, "GET", "/", headers=auth_headers
        )
        assert ui_status == 200
        assert "text/html" in ui_headers.get("content-type", "")
        assert 'id="claim-search"' in ui_body
        assert "Skip to main content" in ui_body

        claims_status, _, claims_body = _http_request(
            port, "GET", "/api/v1/claims", headers=auth_headers
        )
        assert claims_status == 200
        claims_payload: dict[str, Any] = json.loads(claims_body)
        assert claims_payload["count"] >= 2

        consensus_status, _, consensus_body = _http_request(
            port, "GET", "/api/v1/consensus", headers=auth_headers
        )
        assert consensus_status == 200
        consensus_payload: dict[str, Any] = json.loads(consensus_body)
        assert isinstance(consensus_payload, dict)

        prioritize_status, _, prioritize_body = _http_request(
            port, "GET", "/api/v1/prioritize", headers=auth_headers
        )
        assert prioritize_status == 200
        prioritize_payload: dict[str, Any] = json.loads(prioritize_body)
        assert isinstance(prioritize_payload, dict)

        metrics_status, metrics_headers, metrics_body = _http_request(
            port, "GET", "/metrics", headers=auth_headers
        )
        assert metrics_status == 200
        assert "text/plain" in metrics_headers.get("content-type", "")
        assert "scigraph_requests_total" in metrics_body
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)

    # 5. Export compliance bundle and verify provenance manifest
    bundle_dir = tmp_path / "compliance_bundle"
    signing_key = b"enterprise-e2e-signing-key"
    exported_manifest = wm.export_workspace_bundle(
        org_id,
        workspace_id,
        bundle_dir,
        hmac_key=signing_key,
    )

    loaded_graph = load_graph_json(bundle_dir / "graph.json")
    loaded_manifest = ProvenanceManifest.model_validate_json(
        (bundle_dir / "provenance.json").read_text(encoding="utf-8")
    )
    assert loaded_manifest == exported_manifest

    bundle_audit_lines = (
        (bundle_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    )
    bundle_events = [
        AuditEvent.model_validate_json(line)
        for line in bundle_audit_lines
        if line.strip()
    ]

    verified_ok, reasons = verify_provenance_manifest(
        loaded_graph,
        loaded_manifest,
        audit_events=bundle_events,
        hmac_key=signing_key,
    )
    assert verified_ok is True, f"Provenance verification failed: {reasons}"
    assert reasons == ()

    # 6. Verify interoperability exports (GraphML, Mermaid, SARIF v2.1.0)
    contradictions = detect_contradictions(loaded_graph)
    assert len(contradictions) >= 1

    reports = [
        verify_paper_claims(
            paper,
            [c for c in loaded_graph.claims if c.paper_id == paper.paper_id],
        )
        for paper in loaded_graph.papers
    ]

    graphml_xml = export_graphml(loaded_graph)
    graphml_root = ET.fromstring(graphml_xml)
    assert graphml_root.tag.endswith("graphml")

    mermaid_text = export_mermaid_flowchart(loaded_graph, contradictions)
    assert mermaid_text.startswith("flowchart LR")
    assert "contradicts" in mermaid_text

    sarif_raw = export_sarif_v210(contradictions, reports)
    sarif_payload: dict[str, Any] = json.loads(sarif_raw)
    assert sarif_payload["version"] == "2.1.0"
    assert len(sarif_payload["runs"]) == 1
    assert len(sarif_payload["runs"][0]["results"]) >= 1
