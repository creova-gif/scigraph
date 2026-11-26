from __future__ import annotations

import json
import re
import socket
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from graph.claim_graph import ClaimGraph
from ingest.extractor import extract_claims_from_paper
from scigraph.models import Paper
from scigraph.server import (
    MAX_REQUEST_BYTES,
    SciGraphApp,
    _sanitize_request_id,
    _SciGraphHTTPServer,
    create_http_server,
)


def _make_paper(
    paper_id: str,
    doi: str,
    title: str,
    claim_sentence: str,
) -> Paper:
    full_text = f"Title: {title}\nDOI: {doi}\nResults: {claim_sentence}\n"
    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=("Alice Researcher", "Bob Scientist"),
        publication_year=2025,
        venue="Journal of Reproducibility",
        full_text=full_text,
    )


def _build_populated_graph() -> ClaimGraph:
    graph = ClaimGraph()
    paper_a = _make_paper(
        paper_id="paper-a",
        doi="10.1234/alpha.001",
        title="Metformin increases AMPK phosphorylation",
        claim_sentence=(
            "Treatment with Metformin under normoxia increased AMPK phosphorylation "
            "compared with vehicle (d=0.85; n=48, p<0.001)."
        ),
    )
    paper_b = _make_paper(
        paper_id="paper-b",
        doi="10.1234/beta.002",
        title="Metformin decreases AMPK phosphorylation",
        claim_sentence=(
            "Treatment with Metformin under normoxia decreased AMPK phosphorylation "
            "compared with vehicle (d=0.62; n=36, p=0.004)."
        ),
    )
    for paper in (paper_a, paper_b):
        for claim in extract_claims_from_paper(paper):
            graph.add_verified_claim(paper, claim)
    graph.build_edges()
    return graph


@contextmanager
def _running_server(app: SciGraphApp) -> Iterator[str]:
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    host_str = host.decode("ascii") if isinstance(host, bytes) else host
    try:
        yield f"http://{host_str}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _http_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp_headers, resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        resp_headers = {k.lower(): v for k, v in err.headers.items()}
        body = err.read().decode("utf-8")
        return err.code, resp_headers, body


def test_app_health_and_openapi() -> None:
    app = SciGraphApp(_build_populated_graph())

    status, ctype, body = app.handle_request("GET", "/health")
    assert status == 200
    assert ctype == "application/json"
    health = json.loads(body)
    assert health == {
        "status": "ok",
        "version": "0.1.0",
        "papers": 2,
        "claims": 2,
    }

    status_oa, ctype_oa, body_oa = app.handle_request("GET", "/openapi.json")
    assert status_oa == 200
    assert ctype_oa == "application/json"
    spec: dict[str, Any] = json.loads(body_oa)
    assert spec["openapi"] == "3.1.0"
    for route in (
        "/health",
        "/api/v1/claims",
        "/api/v1/contradictions",
        "/api/v1/report",
        "/api/v1/verify",
    ):
        assert route in spec["paths"]


def test_app_claims_filtering_and_invalid_direction() -> None:
    app = SciGraphApp(_build_populated_graph())

    status, _, body = app.handle_request(
        "GET",
        "/api/v1/claims?intervention=metformin&direction=increases",
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["count"] == 1
    assert payload["claims"][0]["paper_id"] == "paper-a"

    status_bad, _, body_bad = app.handle_request("GET", "/api/v1/claims?direction=sideways")
    assert status_bad == 400
    assert "error" in json.loads(body_bad)


def test_app_contradictions_and_reports() -> None:
    app = SciGraphApp(_build_populated_graph())

    status, _, body = app.handle_request("GET", "/api/v1/contradictions")
    assert status == 200
    data = json.loads(body)
    assert len(data["contradictions"]) == 1
    assert len(data["experiments"]) == 1

    expected_types = {
        "json": "application/json",
        "markdown": "text/markdown; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "sarif": "application/sarif+json",
    }
    for fmt, expected_ctype in expected_types.items():
        r_status, r_ctype, r_body = app.handle_request("GET", f"/api/v1/report?format={fmt}")
        assert r_status == 200
        assert r_ctype == expected_ctype
        assert len(r_body) > 0

    bad_status, _, bad_body = app.handle_request("GET", "/api/v1/report?format=xml")
    assert bad_status == 400
    assert "error" in json.loads(bad_body)


def test_app_verify_valid_invalid_and_oversized() -> None:
    app = SciGraphApp()
    paper = _make_paper(
        paper_id="paper-verify",
        doi="10.5555/verify.100",
        title="Rapamycin extends lifespan",
        claim_sentence=(
            "Treatment with Rapamycin under standard diet increased median lifespan "
            "compared with control (d=0.70; n=120, p<0.001)."
        ),
    )
    valid_body = json.dumps({"papers": [paper.model_dump(mode="json")]}).encode("utf-8")
    status, ctype, body = app.handle_request("POST", "/api/v1/verify", valid_body)
    assert status == 200
    assert ctype == "application/json"
    parsed = json.loads(body)
    assert len(parsed["reports"]) == 1
    assert parsed["reports"][0]["doi_verified"] is True
    assert len(parsed["reports"][0]["verified_claims"]) == 1

    bad_json_status, _, _ = app.handle_request("POST", "/api/v1/verify", b"{not-json")
    assert bad_json_status == 400

    bad_model_status, _, _ = app.handle_request(
        "POST",
        "/api/v1/verify",
        json.dumps({"papers": [{"paper_id": "incomplete"}]}).encode("utf-8"),
    )
    assert bad_model_status == 400

    oversized_status, _, _ = app.handle_request(
        "POST",
        "/api/v1/verify",
        b"x" * (MAX_REQUEST_BYTES + 1),
    )
    assert oversized_status == 413

    not_found_status, _, not_found_body = app.handle_request("GET", "/nonexistent")
    assert not_found_status == 404
    assert "error" in json.loads(not_found_body)


def test_http_server_end_to_end() -> None:
    app = SciGraphApp(_build_populated_graph())
    with _running_server(app) as base_url:
        # GET /health
        status, headers, body = _http_request(f"{base_url}/health")
        assert status == 200
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["cache-control"] == "no-store"
        assert json.loads(body)["claims"] == 2

        # GET /openapi.json
        status, _, body = _http_request(f"{base_url}/openapi.json")
        assert status == 200
        assert json.loads(body)["openapi"] == "3.1.0"

        # GET /api/v1/claims
        status, _, body = _http_request(f"{base_url}/api/v1/claims?paper_id=paper-b")
        assert status == 200
        claims_data = json.loads(body)
        assert claims_data["count"] == 1
        assert claims_data["claims"][0]["paper_id"] == "paper-b"

        # GET /api/v1/contradictions
        status, _, body = _http_request(f"{base_url}/api/v1/contradictions")
        assert status == 200
        contra_data = json.loads(body)
        assert len(contra_data["contradictions"]) == 1

        # GET /api/v1/report?format=html
        status, headers, body = _http_request(f"{base_url}/api/v1/report?format=html")
        assert status == 200
        assert headers["content-type"] == "text/html; charset=utf-8"
        assert "<!DOCTYPE html>" in body or "<html" in body

        # POST /api/v1/verify (valid)
        paper = _make_paper(
            paper_id="paper-http",
            doi="10.5555/http.200",
            title="HTTP verification test",
            claim_sentence=(
                "Treatment with Aspirin under normoxia decreased platelet aggregation "
                "compared with placebo (d=0.90; n=64, p<0.001)."
            ),
        )
        payload = json.dumps({"papers": [paper.model_dump(mode="json")]}).encode("utf-8")
        status, _, body = _http_request(
            f"{base_url}/api/v1/verify",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        assert status == 200
        assert len(json.loads(body)["reports"][0]["verified_claims"]) == 1

        # POST /api/v1/verify (invalid)
        status, _, _ = _http_request(
            f"{base_url}/api/v1/verify",
            method="POST",
            data=b"{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400

        # POST /api/v1/verify (oversized -> 413)
        status, _, _ = _http_request(
            f"{base_url}/api/v1/verify",
            method="POST",
            data=b"a" * (MAX_REQUEST_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
        assert status == 413

        # Unknown route -> 404
        status, headers, body = _http_request(f"{base_url}/does-not-exist")
        assert status == 404
        assert headers["x-content-type-options"] == "nosniff"
        assert "error" in json.loads(body)


def test_http_server_hardening_attributes_and_socket_timeout() -> None:
    app = SciGraphApp(_build_populated_graph())
    server = create_http_server("127.0.0.1", 0, app)
    try:
        assert isinstance(server, _SciGraphHTTPServer)
        assert server.daemon_threads is True
        assert server.allow_reuse_address is True
        assert server.request_queue_size == 64

        client_sock, server_sock = socket.socketpair()
        try:
            client_sock.sendall(
                b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            client_sock.shutdown(socket.SHUT_WR)
            server.RequestHandlerClass(server_sock, ("127.0.0.1", 12345), server)
            assert server_sock.gettimeout() == 30.0
            response = client_sock.recv(4096)
            assert b"200 OK" in response
            assert b"X-Request-Id:" in response
        finally:
            client_sock.close()
            server_sock.close()
    finally:
        server.server_close()


def test_sanitize_request_id_and_http_correlation_header() -> None:
    hex_uuid_re = re.compile(r"^[0-9a-f]{32}$")

    # Valid IDs (including surrounding whitespace) are preserved.
    assert _sanitize_request_id("req-123.abc_XYZ") == "req-123.abc_XYZ"
    assert _sanitize_request_id("  valid_id-01  ") == "valid_id-01"

    # Missing, empty, oversized, or newline-containing IDs are regenerated.
    for invalid in (None, "", "   ", "bad\nid", "bad\r\nid", "bad id", "x" * 65, "bad/id"):
        regenerated = _sanitize_request_id(invalid)
        assert hex_uuid_re.fullmatch(regenerated) is not None
        assert regenerated != invalid

    app = SciGraphApp(_build_populated_graph())
    with _running_server(app) as base_url:
        # Echo valid X-Request-Id on GET
        status, headers, _ = _http_request(
            f"{base_url}/health",
            headers={"X-Request-Id": "trace-abc_123.v1"},
        )
        assert status == 200
        assert headers["x-request-id"] == "trace-abc_123.v1"

        # Regenerate when X-Request-Id is omitted
        status, headers, _ = _http_request(f"{base_url}/health")
        assert status == 200
        assert hex_uuid_re.fullmatch(headers["x-request-id"]) is not None

        # Regenerate when X-Request-Id is invalid (e.g. disallowed chars / too long)
        bad_id = "invalid/id with spaces"
        status, headers, _ = _http_request(
            f"{base_url}/health",
            headers={"X-Request-Id": bad_id},
        )
        assert status == 200
        assert headers["x-request-id"] != bad_id
        assert hex_uuid_re.fullmatch(headers["x-request-id"]) is not None

        # Echo valid X-Request-Id on POST (including error responses)
        status, headers, _ = _http_request(
            f"{base_url}/api/v1/verify",
            method="POST",
            data=b"{bad",
            headers={
                "Content-Type": "application/json",
                "X-Request-Id": "post-req-99",
            },
        )
        assert status == 400
        assert headers["x-request-id"] == "post-req-99"
