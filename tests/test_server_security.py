from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

from graph.claim_graph import ClaimGraph
from ingest.extractor import extract_claims_from_paper
from scigraph.models import Paper
from scigraph.security import (
    AuthGate,
    SlidingWindowRateLimiter,
    TokenPolicy,
    hash_bearer_token,
)
from scigraph.server import SciGraphApp, create_http_server


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


def _make_auth_gate() -> tuple[AuthGate, str, str]:
    reader_token = "reader-secret-token"
    ingestor_token = "ingestor-secret-token"
    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token(reader_token),
                org_id="org-1",
                role="reader",
                label="test-reader",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token(ingestor_token),
                org_id="org-1",
                role="ingestor",
                label="test-ingestor",
            ),
        ]
    )
    return gate, reader_token, ingestor_token


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


def test_explorer_root_route() -> None:
    app = SciGraphApp(_build_populated_graph())
    status, ctype, body = app.handle_request("GET", "/")
    assert status == 200
    assert ctype == "text/html; charset=utf-8"
    assert "<!DOCTYPE html>" in body or "<html" in body
    assert "Metformin" in body

    post_status, _, _ = app.handle_request("POST", "/")
    assert post_status == 405


def test_auth_gate_rbac_and_health_bypass() -> None:
    gate, reader_token, ingestor_token = _make_auth_gate()
    app = SciGraphApp(_build_populated_graph(), auth_gate=gate)

    # /health remains accessible without auth when AuthGate is enabled.
    h_status, h_ctype, h_body = app.handle_request("GET", "/health")
    assert h_status == 200
    assert h_ctype == "application/json"
    assert json.loads(h_body)["status"] == "ok"

    # GET / requires reader role.
    root_unauth_status, root_unauth_ctype, root_unauth_body = app.handle_request("GET", "/")
    assert root_unauth_status == 401
    assert root_unauth_ctype == "application/json"
    assert "error" in json.loads(root_unauth_body)

    root_reader_status, root_reader_ctype, _ = app.handle_request(
        "GET",
        "/",
        incoming_header=f"Bearer {reader_token}",
    )
    assert root_reader_status == 200
    assert root_reader_ctype == "text/html; charset=utf-8"

    # GET /api/v1/claims: 401 without token or with invalid token, 200 with reader.
    claims_no_auth, _, claims_no_auth_body = app.handle_request("GET", "/api/v1/claims")
    assert claims_no_auth == 401
    assert "error" in json.loads(claims_no_auth_body)

    claims_bad_auth, _, _ = app.handle_request(
        "GET",
        "/api/v1/claims",
        incoming_header="Bearer wrong-token",
    )
    assert claims_bad_auth == 401

    claims_ok, _, claims_ok_body = app.handle_request(
        "GET",
        "/api/v1/claims",
        incoming_header=f"Bearer {reader_token}",
    )
    assert claims_ok == 200
    assert json.loads(claims_ok_body)["count"] == 2

    # POST /api/v1/verify: 401 without token, 403 for reader, 200 for ingestor.
    paper = _make_paper(
        paper_id="paper-verify",
        doi="10.5555/verify.100",
        title="Rapamycin extends lifespan",
        claim_sentence=(
            "Treatment with Rapamycin under standard diet increased median lifespan "
            "compared with control (d=0.70; n=120, p<0.001)."
        ),
    )
    payload = json.dumps({"papers": [paper.model_dump(mode="json")]}).encode("utf-8")

    v_unauth, _, _ = app.handle_request("POST", "/api/v1/verify", payload)
    assert v_unauth == 401

    v_forbidden, v_forbidden_ctype, v_forbidden_body = app.handle_request(
        "POST",
        "/api/v1/verify",
        payload,
        incoming_header=f"Bearer {reader_token}",
    )
    assert v_forbidden == 403
    assert v_forbidden_ctype == "application/json"
    assert "insufficient role" in json.loads(v_forbidden_body)["error"]

    v_ok, _, v_ok_body = app.handle_request(
        "POST",
        "/api/v1/verify",
        payload,
        incoming_header=f"Bearer {ingestor_token}",
    )
    assert v_ok == 200
    assert len(json.loads(v_ok_body)["reports"]) == 1


def test_rate_limiter_enforces_429() -> None:
    now = [100.0]
    limiter = SlidingWindowRateLimiter(
        max_requests=2,
        window_seconds=10.0,
        clock=lambda: now[0],
    )
    app = SciGraphApp(_build_populated_graph(), rate_limiter=limiter)

    s1, _, _ = app.handle_request("GET", "/health", remote_addr="client-a")
    s2, _, _ = app.handle_request("GET", "/api/v1/claims", remote_addr="client-a")
    assert s1 == 200
    assert s2 == 200

    now[0] = 102.5
    s3, ctype3, body3 = app.handle_request("GET", "/api/v1/claims", remote_addr="client-a")
    assert s3 == 429
    assert ctype3 == "application/json"
    err_payload = json.loads(body3)
    assert err_payload == {
        "error": "rate_limit_exceeded",
        "retry_after_seconds": 7.5,
    }

    # Independent client key is unaffected.
    s_other, _, _ = app.handle_request("GET", "/health", remote_addr="client-b")
    assert s_other == 200

    # Advancing past the window allows requests again.
    now[0] = 110.0
    s4, _, _ = app.handle_request("GET", "/api/v1/claims", remote_addr="client-a")
    assert s4 == 200


def test_http_server_forwards_auth_and_rate_limits() -> None:
    now = [0.0]
    gate, reader_token, ingestor_token = _make_auth_gate()
    limiter = SlidingWindowRateLimiter(
        max_requests=4,
        window_seconds=60.0,
        clock=lambda: now[0],
    )
    app = SciGraphApp(
        _build_populated_graph(),
        auth_gate=gate,
        rate_limiter=limiter,
    )
    with _running_server(app) as base_url:
        # 1. /health succeeds without auth.
        status, _, _ = _http_request(f"{base_url}/health")
        assert status == 200

        # 2. / without auth returns 401.
        status, _, _ = _http_request(f"{base_url}/")
        assert status == 401

        # 3. / with reader token returns 200 HTML.
        status, headers, body = _http_request(
            f"{base_url}/",
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        assert status == 200
        assert headers["content-type"] == "text/html; charset=utf-8"
        assert "<html" in body

        # 4. POST /api/v1/verify with ingestor token returns 200.
        paper = _make_paper(
            paper_id="paper-http-sec",
            doi="10.5555/http.sec.1",
            title="HTTP auth test",
            claim_sentence=(
                "Treatment with Aspirin under normoxia decreased platelet aggregation "
                "compared with placebo (d=0.90; n=64, p<0.001)."
            ),
        )
        payload = json.dumps({"papers": [paper.model_dump(mode="json")]}).encode("utf-8")
        status, _, _ = _http_request(
            f"{base_url}/api/v1/verify",
            method="POST",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ingestor_token}",
            },
        )
        assert status == 200

        # 5. Fifth request from same client IP hits rate limit (429).
        status, _, body = _http_request(f"{base_url}/health")
        assert status == 429
        assert json.loads(body)["error"] == "rate_limit_exceeded"
