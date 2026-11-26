# ADR-003: Multi-Tenant Workspaces, Evidence Scoring, Graph Diff, Reference Export, and Local HTTP Server

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

ADRs 001 and 002 established SciGraph's core neuro-symbolic claim verification pipeline, `/FlateDecode` PDF ingestion, and persistent single-graph SQLite/JSON storage. Moving from a single-user local CLI to a team-ready product requires four additional capabilities without adding third-party web, ORM, or database dependencies:

1. **Multi-Tenant Workspace Isolation & Auditability:** Organizations and teams need isolated graph stores and an append-only audit trail per `(org_id, workspace_id)` without path-traversal risks.
2. **Evidence Quality Scoring & Topic Consensus:** Users need deterministic, reproducible evidence tiers (`HIGH`, `MODERATE`, `PRELIMINARY`) per claim and aggregated directional consensus across `(intervention, outcome)` topics.
3. **Zero-Dependency Local HTTP & OpenAPI Server:** External tools, IDEs, and CI workflows need a local REST API with OpenAPI 3.1.0 discovery, bounded request bodies, and safe response headers.
4. **Graph Diffing & Reference Management Export:** Researchers need to track paper, claim, and contradiction regressions across graph snapshots and export verified citations to BibTeX and RIS.

## Decision

1. **Multi-Tenant Workspaces & Append-Only Audit Log (`src/scigraph/workspace.py`):**
   - `WorkspaceManager` manages tenant directories under `<root_dir>/<org_id>/<workspace_id>/`.
   - `_validate_slug` enforces `^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$` on `org_id` and `workspace_id`, explicitly rejecting `..`, `/`, `\`, and whitespace.
   - `_resolve_workspace_dir` resolves paths and enforces `resolved.is_relative_to(base)` as a defense-in-depth path-traversal guard.
   - Each workspace provisions an isolated `workspace.json` (`WorkspaceConfig`, written atomically via `NamedTemporaryFile` + `os.fsync` + `os.replace`), a per-workspace SQLite `graph.db` (`GraphSQLiteStore`), and an append-only `audit.jsonl` (`AuditEvent` records).

2. **Deterministic Evidence Scoring & Topic Consensus (`src/graph/scoring.py`):**
   - `score_claim_evidence(graph)` deterministically computes a bounded `evidence_strength` in `[0.0, 1.0]` for each claim from sample size `n`, p-value thresholds (`< 0.01`, `< 0.05`), effect-size presence, supporting/replicating edges, and contradiction penalties, assigning `EvidenceTier` (`HIGH` >= 0.70, `MODERATE` >= 0.40, `PRELIMINARY` < 0.40).
   - `compute_topic_consensus(graph)` groups claims by normalized `(intervention, outcome)` pairs, aggregates supporting, contradicting, and neutral counts, determines `consensus_direction`, computes `consensus_score`, and flags `contested` topics.

3. **Zero-Dependency HTTP/OpenAPI Server (`src/scigraph/server.py`):**
   - `SciGraphApp` provides a framework-free request router with `threading.Lock` synchronization over a `ClaimGraph`, paired with `create_http_server` / `run_server` backed by Python stdlib `http.server.ThreadingHTTPServer`.
   - Exposes `GET /health`, `GET /openapi.json`, `GET /api/v1/claims` (with `intervention`, `condition`, `outcome`, `direction`, and `paper_id` filters), `GET /api/v1/contradictions`, `GET /api/v1/report` (`json`, `markdown`, `html`, `sarif`), and `POST /api/v1/verify`.
   - Enforces `MAX_REQUEST_BYTES = 2 * 1024 * 1024` (2 MiB) on `POST` bodies (returning `413` when exceeded) and sets `X-Content-Type-Options: nosniff` and `Cache-Control: no-store` on all HTTP responses.

4. **Graph Diff & BibTeX/RIS Reference Exporters (`src/scigraph/diff.py`):**
   - `diff_claim_graphs(baseline, current)` returns a frozen `GraphDiff` summarizing `added_papers`, `removed_papers`, `added_claims`, `removed_claims`, `new_contradictions`, and `resolved_contradictions`.
   - `export_bibtex(papers)` and `export_ris(papers)` emit deterministic, `paper_id`-sorted `@article` BibTeX entries (with LaTeX special-character escaping) and RIS `TY  - JOUR` records.

## Alternatives Considered

- **FastAPI / Starlette + Uvicorn for the HTTP server:** Rejected to preserve SciGraph's zero-external-runtime-dependency footprint beyond Pydantic v2 and Python 3.12's standard library.
- **Shared multi-tenant SQLite database with `org_id`/`workspace_id` row filtering:** Rejected in favor of per-workspace `graph.db` files so tenant data isolation, backup, and deletion are filesystem-atomic and cannot suffer from missing `WHERE` clauses.
- **Database-backed audit table:** Rejected in favor of append-only `audit.jsonl` so audit records remain human-inspectable, streamable, and decoupled from SQLite schema migrations.

## Consequences & Failure Modes

- **Positive:** Teams gain isolated per-workspace graphs, tamper-evident JSONL audit trails, deterministic evidence/consensus scoring, regression diffing, BibTeX/RIS export, and a local OpenAPI server with zero new dependencies.
- **Negative:** `ThreadingHTTPServer` is intended for local and single-node team workflows rather than internet-facing multi-worker production traffic without a reverse proxy.
- **Mitigation:** Bind to `127.0.0.1` by default, enforce `MAX_REQUEST_BYTES = 2 MiB` and strict Pydantic validation on all inputs, and place TLS/auth termination in front of `SciGraphApp` if exposed beyond localhost.
