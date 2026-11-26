from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from graph.claim_graph import ClaimGraph
from graph.scoring import compute_topic_consensus, score_claim_evidence
from graph.store import GraphSQLiteStore, load_graph_json
from ingest.extractor import extract_claims_from_paper
from ingest.verifier import verify_paper_claims
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import (
    export_json_bundle,
    export_sarif_v210,
    render_markdown_report,
)
from scigraph.models import EffectDirection, Paper
from scigraph.security import ApiRole, AuthGate, SlidingWindowRateLimiter, TokenPolicy
from scigraph.workspace import WorkspaceManager
from solver.prioritizer import prioritize_experiments
from solver.symbolic import detect_contradictions, propose_falsifiable_experiments

MAX_REQUEST_BYTES = 2 * 1024 * 1024
_API_VERSION = "0.1.0"
_SQLITE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _sanitize_request_id(raw: str | None) -> str:
    """Return stripped raw request ID if valid, otherwise generate a fresh UUID hex."""
    if raw is not None:
        stripped = raw.strip()
        if _REQUEST_ID_PATTERN.fullmatch(stripped):
            return stripped
    return uuid.uuid4().hex


class ServerResponse(BaseModel):
    """Structured HTTP response returned by SciGraphApp."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    status: int
    content_type: str
    body: str


def _json_response(status: int, payload: object) -> ServerResponse:
    return ServerResponse(
        status=status,
        content_type="application/json",
        body=json.dumps(payload, indent=2) + "\n",
    )


def _error_response(status: int, message: str) -> ServerResponse:
    return _json_response(status, {"error": message})


def load_token_policies(path: Path) -> tuple[TokenPolicy, ...]:
    """Load and validate TokenPolicy entries from a JSON list or {'policies': [...]} file."""
    if not path.exists() or not path.is_file():
        raise ValueError(f"Token policies path does not exist or is not a file: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
        decoded = json.loads(raw_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid token policies JSON in {path}: {exc}") from exc

    raw_policies: object
    if isinstance(decoded, list):
        raw_policies = decoded
    elif isinstance(decoded, dict) and isinstance(decoded.get("policies"), list):
        raw_policies = decoded["policies"]
    else:
        raise ValueError(
            f"Token policies JSON in {path} must be a list or an object with a 'policies' list"
        )

    assert isinstance(raw_policies, list)
    policies: list[TokenPolicy] = []
    for item in raw_policies:
        try:
            policies.append(TokenPolicy.model_validate(item))
        except ValidationError as exc:
            raise ValueError(f"Invalid token policy schema in {path}: {exc}") from exc
    return tuple(policies)


def _build_openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SciGraph Local API",
            "version": _API_VERSION,
            "description": (
                "Zero-dependency HTTP/REST API for SciGraph claim verification, "
                "contradiction detection, and report generation."
            ),
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health and corpus counts",
                    "responses": {
                        "200": {
                            "description": "Service health status",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/metrics": {
                "get": {
                    "summary": "Prometheus-format operational metrics",
                    "responses": {
                        "200": {
                            "description": "Prometheus text exposition metrics",
                            "content": {
                                "text/plain; version=0.0.4; charset=utf-8": {
                                    "schema": {"type": "string"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/v1/claims": {
                "get": {
                    "summary": "Query verified claims in the graph",
                    "parameters": [
                        {"name": "intervention", "in": "query", "schema": {"type": "string"}},
                        {"name": "condition", "in": "query", "schema": {"type": "string"}},
                        {"name": "outcome", "in": "query", "schema": {"type": "string"}},
                        {
                            "name": "direction",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "enum": [d.value for d in EffectDirection],
                            },
                        },
                        {"name": "paper_id", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "Matching claims"},
                        "400": {"description": "Invalid direction parameter"},
                    },
                }
            },
            "/api/v1/contradictions": {
                "get": {
                    "summary": "Detect contradictions and propose falsifiable experiments",
                    "responses": {
                        "200": {"description": "Detected contradictions and experiments"}
                    },
                }
            },
            "/api/v1/consensus": {
                "get": {
                    "summary": "Compute topic consensus and claim evidence scores",
                    "responses": {
                        "200": {"description": "Topic consensus and claim evidence scores"}
                    },
                }
            },
            "/api/v1/prioritize": {
                "get": {
                    "summary": "Prioritize falsifiable experiments by ROI and cost tier",
                    "responses": {
                        "200": {"description": "Prioritized falsifiable experiments"}
                    },
                }
            },
            "/api/v1/report": {
                "get": {
                    "summary": "Render full SciGraph report",
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "enum": ["json", "markdown", "html", "sarif"],
                                "default": "json",
                            },
                        }
                    ],
                    "responses": {
                        "200": {"description": "Rendered report"},
                        "400": {"description": "Unsupported report format"},
                    },
                }
            },
            "/api/v1/verify": {
                "post": {
                    "summary": "Extract and verify claims from submitted papers",
                    "parameters": [
                        {
                            "name": "persist",
                            "in": "query",
                            "schema": {"type": "boolean", "default": False},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["papers"],
                                    "properties": {
                                        "papers": {"type": "array", "items": {"type": "object"}}
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Paper verification reports"},
                        "400": {"description": "Invalid JSON or Paper validation error"},
                        "413": {"description": "Request payload exceeds MAX_REQUEST_BYTES"},
                    },
                }
            },
        },
    }


def _first_param(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


class SciGraphApp:
    """In-process HTTP request dispatcher for SciGraph."""

    def __init__(
        self,
        graph: ClaimGraph | None = None,
        *,
        auth_gate: AuthGate | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        workspace_manager: WorkspaceManager | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.auth_gate: AuthGate | None = auth_gate
        self.rate_limiter: SlidingWindowRateLimiter | None = rate_limiter
        self.workspace_manager: WorkspaceManager | None = workspace_manager
        self.org_id: str | None = org_id
        self.workspace_id: str | None = workspace_id
        if graph is not None:
            self.graph: ClaimGraph = graph
        elif (
            workspace_manager is not None
            and org_id is not None
            and workspace_id is not None
        ):
            self.graph = workspace_manager.load_graph(org_id, workspace_id)
        else:
            self.graph = ClaimGraph()
        self._lock = threading.Lock()
        self._started_at: float = time.monotonic()
        self._requests_total: int = 0
        self._errors_total: int = 0
        self._rate_limited_total: int = 0

    def handle_request(
        self,
        method: str,
        target: str,
        body: bytes = b"",
        *,
        incoming_header: str | None = None,
        remote_addr: str = "local",
    ) -> tuple[int, str, str]:
        resp = self._dispatch(
            method.upper(),
            target,
            body,
            incoming_header,
            remote_addr,
        )
        return (resp.status, resp.content_type, resp.body)

    def _dispatch(
        self,
        method: str,
        target: str,
        body: bytes,
        incoming_header: str | None,
        remote_addr: str,
    ) -> ServerResponse:
        resp = self._route_request(
            method,
            target,
            body,
            incoming_header,
            remote_addr,
        )
        with self._lock:
            self._requests_total += 1
            if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
                self._rate_limited_total += 1
            if resp.status >= 400:
                self._errors_total += 1
        return resp

    def _route_request(
        self,
        method: str,
        target: str,
        body: bytes,
        incoming_header: str | None,
        remote_addr: str,
    ) -> ServerResponse:
        if self.rate_limiter is not None:
            allowed, retry_after = self.rate_limiter.check(remote_addr)
            if not allowed:
                return _json_response(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {
                        "error": "rate_limit_exceeded",
                        "retry_after_seconds": round(retry_after, 3),
                    },
                )

        try:
            parsed = urlsplit(target)
        except ValueError as exc:
            return _error_response(HTTPStatus.BAD_REQUEST, f"Malformed request target: {exc}")
        path = parsed.path or "/"
        params = parse_qs(parsed.query, keep_blank_values=False)

        if (
            self.auth_gate is not None
            and self.auth_gate.enabled
            and (path.startswith("/api/") or path == "/")
        ):
            required_role: ApiRole = (
                "ingestor" if (path == "/api/v1/verify" and method == "POST") else "reader"
            )
            decision = self.auth_gate.authorize(incoming_header, required_role)
            if not decision.allowed:
                return _error_response(decision.status_code, decision.reason)
            if self.org_id is not None and decision.org_id != self.org_id:
                return _error_response(
                    HTTPStatus.FORBIDDEN,
                    "Token org_id does not match workspace org_id",
                )

        if path == "/":
            return self._require_get(method, lambda: self._handle_explorer())
        if path == "/health":
            return self._require_get(method, lambda: self._handle_health())
        if path == "/metrics":
            return self._require_get(method, lambda: self._handle_metrics())
        if path == "/openapi.json":
            return self._require_get(method, lambda: _json_response(200, _build_openapi_spec()))
        if path == "/api/v1/claims":
            return self._require_get(method, lambda: self._handle_claims(params))
        if path == "/api/v1/contradictions":
            return self._require_get(method, lambda: self._handle_contradictions())
        if path == "/api/v1/consensus":
            return self._require_get(method, lambda: self._handle_consensus())
        if path == "/api/v1/prioritize":
            return self._require_get(method, lambda: self._handle_prioritize())
        if path == "/api/v1/report":
            return self._require_get(method, lambda: self._handle_report(params))
        if path == "/api/v1/verify":
            if method != "POST":
                return _error_response(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    f"Method {method} not allowed",
                )
            return self._handle_verify(body, params)

        return _error_response(HTTPStatus.NOT_FOUND, f"Unknown route: {path}")

    @staticmethod
    def _require_get(method: str, handler: Callable[[], ServerResponse]) -> ServerResponse:
        if method != "GET":
            return _error_response(HTTPStatus.METHOD_NOT_ALLOWED, f"Method {method} not allowed")
        return handler()

    def _handle_explorer(self) -> ServerResponse:
        with self._lock:
            contradictions = detect_contradictions(self.graph)
            experiments = propose_falsifiable_experiments(contradictions)
            rendered = render_claim_graph_html(self.graph, contradictions, experiments)
        return ServerResponse(
            status=HTTPStatus.OK,
            content_type="text/html; charset=utf-8",
            body=rendered,
        )

    def _handle_health(self) -> ServerResponse:
        with self._lock:
            paper_count = len(self.graph.papers)
            claim_count = len(self.graph.claims)
        return _json_response(
            HTTPStatus.OK,
            {
                "status": "ok",
                "version": _API_VERSION,
                "papers": paper_count,
                "claims": claim_count,
            },
        )

    def _handle_metrics(self) -> ServerResponse:
        with self._lock:
            requests_total = self._requests_total
            errors_total = self._errors_total
            rate_limited_total = self._rate_limited_total
            paper_count = len(self.graph.papers)
            claim_count = len(self.graph.claims)
        uptime_seconds = max(0.0, time.monotonic() - self._started_at)
        lines = [
            "# HELP scigraph_requests_total Total number of HTTP requests processed",
            "# TYPE scigraph_requests_total counter",
            f"scigraph_requests_total {requests_total}",
            "# HELP scigraph_errors_total Total number of HTTP responses with status >= 400",
            "# TYPE scigraph_errors_total counter",
            f"scigraph_errors_total {errors_total}",
            "# HELP scigraph_rate_limited_total Total number of HTTP 429 rate-limited responses",
            "# TYPE scigraph_rate_limited_total counter",
            f"scigraph_rate_limited_total {rate_limited_total}",
            "# HELP scigraph_papers_total Total number of papers in the claim graph",
            "# TYPE scigraph_papers_total gauge",
            f"scigraph_papers_total {paper_count}",
            "# HELP scigraph_claims_total Total number of claims in the claim graph",
            "# TYPE scigraph_claims_total gauge",
            f"scigraph_claims_total {claim_count}",
            "# HELP scigraph_uptime_seconds Seconds since SciGraphApp initialization",
            "# TYPE scigraph_uptime_seconds gauge",
            f"scigraph_uptime_seconds {uptime_seconds:.6f}",
        ]
        return ServerResponse(
            status=HTTPStatus.OK,
            content_type="text/plain; version=0.0.4; charset=utf-8",
            body="\n".join(lines) + "\n",
        )

    def _handle_claims(self, params: dict[str, list[str]]) -> ServerResponse:
        direction_raw = _first_param(params, "direction")
        effect_direction: EffectDirection | None = None
        if direction_raw is not None:
            try:
                effect_direction = EffectDirection(direction_raw)
            except ValueError:
                valid = ", ".join(d.value for d in EffectDirection)
                return _error_response(
                    HTTPStatus.BAD_REQUEST,
                    f"Invalid direction {direction_raw!r}; expected one of: {valid}",
                )

        with self._lock:
            matched = self.graph.query_claims(
                intervention=_first_param(params, "intervention"),
                condition=_first_param(params, "condition"),
                outcome=_first_param(params, "outcome"),
                effect_direction=effect_direction,
                paper_id=_first_param(params, "paper_id"),
            )
        return _json_response(
            HTTPStatus.OK,
            {
                "count": len(matched),
                "claims": [claim.model_dump(mode="json") for claim in matched],
            },
        )

    def _handle_contradictions(self) -> ServerResponse:
        with self._lock:
            contradictions = detect_contradictions(self.graph)
        experiments = propose_falsifiable_experiments(contradictions)
        return _json_response(
            HTTPStatus.OK,
            {
                "contradictions": [pair.model_dump(mode="json") for pair in contradictions],
                "experiments": [exp.model_dump(mode="json") for exp in experiments],
            },
        )

    def _handle_consensus(self) -> ServerResponse:
        with self._lock:
            consensus = compute_topic_consensus(self.graph)
            claim_scores = score_claim_evidence(self.graph)
        return _json_response(
            HTTPStatus.OK,
            {
                "consensus": [item.model_dump(mode="json") for item in consensus],
                "claim_scores": {
                    claim_id: score.model_dump(mode="json")
                    for claim_id, score in claim_scores.items()
                },
            },
        )

    def _handle_prioritize(self) -> ServerResponse:
        with self._lock:
            contradictions = detect_contradictions(self.graph)
            experiments = propose_falsifiable_experiments(contradictions)
            prioritized = prioritize_experiments(self.graph, contradictions, experiments)
        return _json_response(
            HTTPStatus.OK,
            {
                "prioritized": [item.model_dump(mode="json") for item in prioritized],
            },
        )

    def _handle_report(self, params: dict[str, list[str]]) -> ServerResponse:
        fmt = (_first_param(params, "format") or "json").lower()
        with self._lock:
            contradictions = detect_contradictions(self.graph)
            experiments = propose_falsifiable_experiments(contradictions)
            renderers: dict[str, tuple[str, Callable[[], str]]] = {
                "json": (
                    "application/json",
                    lambda: export_json_bundle(self.graph, contradictions, experiments),
                ),
                "markdown": (
                    "text/markdown; charset=utf-8",
                    lambda: render_markdown_report(self.graph, contradictions, experiments),
                ),
                "html": (
                    "text/html; charset=utf-8",
                    lambda: render_claim_graph_html(self.graph, contradictions, experiments),
                ),
                "sarif": (
                    "application/sarif+json",
                    lambda: export_sarif_v210(contradictions),
                ),
            }
            entry = renderers.get(fmt)
            if entry is None:
                return _error_response(
                    HTTPStatus.BAD_REQUEST,
                    f"Unsupported report format {fmt!r}; expected json, markdown, html, or sarif",
                )
            content_type, render_fn = entry
            rendered = render_fn()

        return ServerResponse(status=HTTPStatus.OK, content_type=content_type, body=rendered)

    @staticmethod
    def _parse_bool_param(params: dict[str, list[str]], key: str) -> bool | None:
        raw = _first_param(params, key)
        if raw is None:
            return False
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        return None

    def _handle_verify(self, body: bytes, params: dict[str, list[str]]) -> ServerResponse:
        if len(body) > MAX_REQUEST_BYTES:
            return _error_response(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"Request body exceeds {MAX_REQUEST_BYTES} bytes",
            )

        persist = self._parse_bool_param(params, "persist")
        if persist is None:
            raw_persist = _first_param(params, "persist")
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                f"Invalid persist parameter {raw_persist!r}; expected true or false",
            )

        if persist and (
            self.workspace_manager is None
            or self.org_id is None
            or self.workspace_id is None
        ):
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                "Cannot persist verification results without a configured workspace",
            )

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _error_response(HTTPStatus.BAD_REQUEST, f"Invalid JSON payload: {exc}")

        if not isinstance(decoded, dict) or "papers" not in decoded:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                "Request body must be a JSON object with a 'papers' list",
            )

        raw_papers = decoded["papers"]
        if not isinstance(raw_papers, list):
            return _error_response(HTTPStatus.BAD_REQUEST, "'papers' must be a JSON array")

        papers: list[Paper] = []
        for raw_paper in raw_papers:
            try:
                papers.append(Paper.model_validate(raw_paper, strict=False))
            except ValidationError as exc:
                return _error_response(HTTPStatus.BAD_REQUEST, f"Paper validation error: {exc}")

        if persist:
            assert self.workspace_manager is not None
            assert self.org_id is not None
            assert self.workspace_id is not None
            with self._lock:
                try:
                    updated_graph, verification_reports = self.workspace_manager.ingest_papers(
                        self.org_id,
                        self.workspace_id,
                        papers,
                    )
                except FileNotFoundError as exc:
                    return _error_response(HTTPStatus.NOT_FOUND, str(exc))
                except ValueError as exc:
                    return _error_response(HTTPStatus.BAD_REQUEST, str(exc))
                except (OSError, sqlite3.Error) as exc:
                    return _error_response(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"Workspace persistence error: {exc}",
                    )
                self.graph = updated_graph
            reports = [report.model_dump(mode="json") for report in verification_reports]
            return _json_response(HTTPStatus.OK, {"reports": reports})

        reports = []
        for paper in papers:
            claims = extract_claims_from_paper(paper)
            report = verify_paper_claims(paper, claims)
            reports.append(report.model_dump(mode="json"))

        return _json_response(HTTPStatus.OK, {"reports": reports})


class _SciGraphHTTPServer(ThreadingHTTPServer):
    """Hardened ThreadingHTTPServer with bounded queue, daemon threads, and address reuse."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def create_http_server(
    host: str,
    port: int,
    app: SciGraphApp,
) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer wired to a SciGraphApp instance."""

    class _Handler(BaseHTTPRequestHandler):
        _current_request_id: str = ""

        def setup(self) -> None:
            self.request.settimeout(30.0)
            self._current_request_id = ""
            super().setup()

        def log_message(self, format: str, *args: object) -> None:
            # Suppress default stderr request logging for clean CLI/test output.
            return

        def do_GET(self) -> None:
            self._current_request_id = _sanitize_request_id(self.headers.get("X-Request-Id"))
            hdr_value = self.headers.get("Authorization")
            status, content_type, body_text = app.handle_request(
                "GET",
                self.path,
                incoming_header=hdr_value,
                remote_addr=self.client_address[0],
            )
            self._write_response(status, content_type, body_text)

        def do_POST(self) -> None:
            self._current_request_id = _sanitize_request_id(self.headers.get("X-Request-Id"))
            raw_len = self.headers.get("Content-Length", "0")
            try:
                content_length = int(raw_len)
            except ValueError:
                self._write_response(
                    HTTPStatus.BAD_REQUEST,
                    "application/json",
                    json.dumps({"error": "Invalid Content-Length header"}) + "\n",
                )
                return

            if content_length < 0:
                self._write_response(
                    HTTPStatus.BAD_REQUEST,
                    "application/json",
                    json.dumps({"error": "Negative Content-Length header"}) + "\n",
                )
                return

            if content_length > MAX_REQUEST_BYTES:
                if content_length <= MAX_REQUEST_BYTES * 2:
                    remaining = content_length
                    try:
                        while remaining > 0:
                            chunk = self.rfile.read(min(remaining, 65536))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                    except TimeoutError:
                        self._write_response(
                            HTTPStatus.REQUEST_TIMEOUT,
                            "application/json",
                            json.dumps({"error": "Request body read timed out"}) + "\n",
                        )
                        return
                self._write_response(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "application/json",
                    json.dumps({"error": f"Request body exceeds {MAX_REQUEST_BYTES} bytes"}) + "\n",
                )
                return

            try:
                body = self.rfile.read(content_length) if content_length > 0 else b""
            except TimeoutError:
                self._write_response(
                    HTTPStatus.REQUEST_TIMEOUT,
                    "application/json",
                    json.dumps({"error": "Request body read timed out"}) + "\n",
                )
                return
            hdr_value = self.headers.get("Authorization")
            status, content_type, body_text = app.handle_request(
                "POST",
                self.path,
                body,
                incoming_header=hdr_value,
                remote_addr=self.client_address[0],
            )
            self._write_response(status, content_type, body_text)

        def _write_response(self, status: int, content_type: str, body_text: str) -> None:
            payload = body_text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Request-Id", self._current_request_id)
            self.end_headers()
            self.wfile.write(payload)

    return _SciGraphHTTPServer((host, port), _Handler)


def _load_graph_from_store(store_path: Path) -> ClaimGraph:
    if not store_path.exists() or not store_path.is_file():
        raise ValueError(f"Store path does not exist or is not a file: {store_path}")
    suffix = store_path.suffix.lower()
    if suffix == ".json":
        return load_graph_json(store_path)
    if suffix in _SQLITE_SUFFIXES:
        return GraphSQLiteStore(store_path).load_graph()
    raise ValueError(
        f"Unsupported store extension {store_path.suffix!r} for {store_path}; "
        "expected .json, .db, .sqlite, or .sqlite3"
    )


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    store_path: Path | None = None,
) -> None:
    """Start a blocking ThreadingHTTPServer serving the SciGraph API."""
    graph = _load_graph_from_store(store_path) if store_path is not None else ClaimGraph()
    app = SciGraphApp(graph=graph)
    server = create_http_server(host, port, app)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
