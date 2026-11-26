# ADR-007: Enterprise Hardening, Lifecycle Operations, and Accessibility

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

ADRs 001–006 established SciGraph's core claim verification, persistent SQLite store, multi-tenant workspaces, REST/OpenAPI server, provenance manifests, canonicalization, prioritization, diagrams, tabular/PubMed ingestion, lab protocols, and `scigraph doctor`. Production deployment and security review across Waves 8–18 identified several hardening, lifecycle, observability, interoperability, and accessibility gaps:

1. **Shared Atomic I/O & SSRF Guards:** Multiple modules duplicated temporary-file write logic and SSRF validation rules.
2. **SQLite Concurrency & Query Pushdown:** Concurrent readers/writers needed WAL mode, and filtered claim queries needed SQL pushdown instead of full-graph deserialization.
3. **Rate-Limiter Eviction Resistance:** Unbounded client-key tracking risks memory exhaustion, while naive LRU eviction allows attackers to evict active rate-limit windows.
4. **RFC 9110 HTTP Compliance & Observability:** Health checks needed `HEAD /health`, unsupported methods needed `405 Method Not Allowed` with `Allow` headers, and operators needed `GET /metrics`.
5. **API Parity & Paper Lifecycle:** The HTTP server lacked consensus, prioritization, audit-log inspection, and paper deletion endpoints, and workspaces lacked atomic compliance bundle export and CLI paper removal.
6. **Graph Interoperability, Accessibility, & Deployment:** Teams needed GraphML export for Cytoscape/Gephi/NetworkX, WCAG 2.1 AA compliance in the HTML Explorer, a container image (`Dockerfile`), and a `SECURITY.md` policy.

## Decision

1. **Shared Atomic I/O & SSRF Network Guard (`src/scigraph/io_utils.py`, `src/scigraph/net_guard.py`):**
   - `atomic_write_text` centralizes `NamedTemporaryFile` + `os.fsync` + `os.replace` with cleanup on `OSError`.
   - `net_guard` centralizes `NoRedirectHandler`, `is_non_public_ip`, `assert_public_dns_resolution`, and `validate_public_https_url` for connectors and webhook alerts.

2. **SQLite WAL & Query Pushdown (`src/graph/store.py`):**
   - `GraphSQLiteStore` enables `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`, and exposes `query_claims` for SQL-level filtering before hydrating Pydantic models.

3. **Anti-Eviction Rate Limiting (`src/scigraph/security.py`):**
   - `SlidingWindowRateLimiter` bounds tracked keys (`max_keys`) and protects active windows from eviction under key-flooding by tracking earliest-eviction timestamps and rejecting/evicting expired entries safely.

4. **RFC 9110 HTTP Semantics, Observability & API Parity (`src/scigraph/server.py`):**
   - Added `HEAD /health` (`do_HEAD` / `_handle_no_body_method`) and `405 Method Not Allowed` responses with explicit `Allow` headers.
   - Added `GET /metrics`, `GET /api/v1/consensus`, `GET /api/v1/prioritize`, `GET /api/v1/audit`, and `DELETE /api/v1/papers/{paper_id}` (backed by `WorkspaceManager.remove_paper` and `scigraph workspace remove-paper`).

5. **Compliance Bundles, GraphML, Accessibility & Packaging:**
   - `WorkspaceManager.export_workspace_bundle` (`scigraph workspace export-bundle`) atomically exports `graph.json`, `provenance.json`, `workspace.json`, and `audit.jsonl`.
   - `export_graphml` (`src/scigraph/diagrams.py`, `scigraph diagram --format graphml`) emits standard GraphML XML.
   - `src/scigraph/explorer.py` adds WCAG 2.1 AA semantics (`aria-pressed`, `aria-live="polite"`, `role="region"`, `role="group"`, and keyboard-accessible scroll regions).
   - Added `Dockerfile` for containerized deployment and `SECURITY.md` for vulnerability reporting.

## Alternatives Considered

- **In-memory-only rate limiting without `max_keys` bounds:** Rejected due to unbounded memory growth under distributed or spoofed client keys.
- **Returning `404` or `400` on wrong HTTP methods:** Rejected in favor of RFC 9110 `405 Method Not Allowed` with an `Allow` header.
- **Adding external GraphML or web-framework dependencies:** Rejected to preserve SciGraph's zero-external-server-dependency footprint (`xml.etree.ElementTree` and `http.server.ThreadingHTTPServer`).

## Consequences & Failure Modes

- **Positive:** Stronger SSRF and rate-limit defenses, higher SQLite read concurrency, full paper lifecycle management via CLI and REST, GraphML interoperability, WCAG 2.1 AA explorer navigation, and container-ready packaging.
- **Negative:** SQLite WAL mode creates `-wal` and `-shm` sidecar files alongside `graph.db`.
- **Mitigation:** `WorkspaceManager.export_workspace_bundle` exports canonical `graph.json` and `provenance.json` snapshots rather than raw SQLite sidecar files.
