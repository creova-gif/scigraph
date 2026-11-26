from __future__ import annotations

import concurrent.futures
import http.client
import json
import re
import threading

from evals.benchmark import BENCHMARK_30_PAPERS
from graph.claim_graph import ClaimGraph
from ingest.extractor import extract_claims_from_paper, extract_paper_from_layout
from ingest.verifier import verify_paper_claims
from scigraph.server import SciGraphApp, create_http_server


def _build_benchmark_graph() -> ClaimGraph:
    graph = ClaimGraph()
    for spec in BENCHMARK_30_PAPERS[:10]:
        paper = extract_paper_from_layout(spec.paper_id, spec.blocks)
        graph.add_paper(paper)
        claims = extract_claims_from_paper(paper)
        report = verify_paper_claims(paper, claims)
        for verified_claim in report.verified_claims:
            graph.add_verified_claim(paper, verified_claim)
    graph.build_edges()
    return graph


def _send_request(
    port: int,
    method: str,
    path: str,
) -> tuple[str, str, int, dict[str, str], str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        headers = {k.lower(): v for k, v in resp.getheaders()}
        return method, path, resp.status, headers, body
    finally:
        conn.close()


def _parse_prometheus_metric(metrics_body: str, metric_name: str) -> int:
    match = re.search(rf"^{re.escape(metric_name)}\s+(\d+)\s*$", metrics_body, re.MULTILINE)
    assert match is not None, f"Metric {metric_name!r} not found in /metrics output"
    return int(match.group(1))


def test_http_server_concurrent_load_and_metrics() -> None:
    graph = _build_benchmark_graph()
    assert len(graph.papers) > 0
    assert len(graph.claims) > 0

    app = SciGraphApp(graph=graph)
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    targets: list[tuple[str, str]] = [
        ("GET", "/health"),
        ("HEAD", "/health"),
        ("GET", "/api/v1/claims"),
        ("GET", "/api/v1/consensus"),
        ("GET", "/api/v1/prioritize"),
    ]
    requests_plan = targets * 8
    assert len(requests_plan) == 40

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(_send_request, port, method, path)
                for method, path in requests_plan
            ]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        assert len(results) == 40
        for method, path, status, headers, body in results:
            assert status == 200, f"{method} {path} returned {status}: {body}"
            request_id = headers.get("x-request-id", "").strip()
            assert request_id != "", f"{method} {path} missing X-Request-Id header"

            if method == "HEAD":
                assert body == ""
                continue

            payload = json.loads(body)
            assert isinstance(payload, dict)
            if path == "/health":
                assert payload["status"] == "ok"
                assert payload["papers"] == len(graph.papers)
                assert payload["claims"] == len(graph.claims)
            elif path == "/api/v1/claims":
                assert isinstance(payload["count"], int)
                assert isinstance(payload["claims"], list)
                assert payload["count"] == len(payload["claims"])
            elif path == "/api/v1/consensus":
                assert isinstance(payload["consensus"], list)
                assert isinstance(payload["claim_scores"], dict)
            elif path == "/api/v1/prioritize":
                assert isinstance(payload["prioritized"], list)

        _, _, metrics_status, metrics_headers, metrics_body = _send_request(port, "GET", "/metrics")
        assert metrics_status == 200
        assert metrics_headers.get("x-request-id", "").strip() != ""
        requests_total = _parse_prometheus_metric(metrics_body, "scigraph_requests_total")
        errors_total = _parse_prometheus_metric(metrics_body, "scigraph_errors_total")
        assert requests_total >= 40
        assert errors_total == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
