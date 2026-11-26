# Changelog

All notable changes to SciGraph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-26

### Added

- **Wave 1 — Core Claim Graph & Symbolic Contradiction Engine (ADR-001):**
  - Typed claim tuples and strict Pydantic v2 domain models (`scigraph.models`).
  - Verbatim evidence verification (`ingest.verifier`), claim graph (`graph.claim_graph`), symbolic contradiction solver (`solver.symbolic`), and 30-paper benchmark (`evals.benchmark`).
- **Wave 2 — CLI, Exporters & Quantitative Regime Solver:**
  - `scigraph` CLI (`scigraph.cli`), interactive HTML explorer (`scigraph.explorer`), quantitative regime boundary solver (`solver.regime`), SARIF/JSON/Markdown exporters (`scigraph.exporters`), and statistical power calculator.
- **Wave 3 — PDF Ingestion & Persistent Graph Store (ADR-002):**
  - FlateDecode PDF extraction and open-access corpus loaders (`ingest.corpus_loader`, `ingest.extractor`, `ingest.open_access_corpus`) and persistent graph storage (`graph.store`).
- **Wave 4 — Multi-Tenant Workspaces, Scoring & HTTP Server (ADR-003):**
  - Isolated multi-tenant workspaces (`scigraph.workspace`), evidence scoring (`graph.scoring`), graph diffing (`scigraph.diff`), and HTTP API server (`scigraph.server`).
- **Wave 5 — Connectors, Provenance, RBAC & Pipeline (ADR-004):**
  - Literature connectors (`ingest.connectors`), provenance tracking (`scigraph.provenance`), RBAC/security controls (`scigraph.security`), configuration (`scigraph.config`), and unified ingestion-to-solver pipeline (`scigraph.pipeline`).
- **Wave 6 — Canonicalization, Prioritization & Alerts (ADR-005):**
  - Entity canonicalization (`graph.canonicalizer`), experiment prioritizer (`solver.prioritizer`), and webhook/alerting (`scigraph.alerts`).
- **Wave 7 — Diagrams, Tabular/PubMed Ingestion, Protocols & Doctor (ADR-006):**
  - Mermaid and Graphviz DOT diagram generation (`scigraph.diagrams`), CSV/TSV and PubMed EFetch XML ingestion (`ingest.tabular`), experimental protocol generation (`solver.protocols`), and environment diagnostics (`scigraph.doctor`).
- **Security:** Centralized SSRF network guards (`net_guard`) with redirect blocking, anti-eviction sliding-window rate limiting, and a documented `SECURITY.md` policy.
- **Operations:** Shared atomic file writes (`io_utils`), SQLite WAL mode with query pushdown, RFC 9110 `HEAD /health` and `405 Allow` responses, `GET /metrics`, `Dockerfile`, and `.env.example`.
- **Accessibility:** WCAG 2.1 AA semantics in the interactive HTML Claim-Graph Explorer (`aria-pressed`, `aria-live`, landmark regions, and keyboard-focusable tables).
- **Lifecycle:** Workspace paper removal (`DELETE /api/v1/papers/{paper_id}` and `scigraph workspace remove-paper`), atomic compliance bundle export (`scigraph workspace export-bundle`), `GET /api/v1/consensus`, `GET /api/v1/prioritize`, `GET /api/v1/audit`, and GraphML diagram export (`scigraph diagram --format graphml`).
