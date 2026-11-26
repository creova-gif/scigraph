# scigraph — Execution Checklist

## Wave 1: Day 1–5 Setup
- [x] Set up ingest/, graph/, solver/, and evals/ directories
- [x] Define Pydantic models for Paper, ScientificClaim, and EvidenceEdge
- [x] Test layout-aware PDF extraction on 5 open-access arXiv/PubMed papers
- [x] Build deterministic verifier confirming extracted p-values/sample sizes exist verbatim

## Wave 2: MVP & Eval Gate
- [x] Write ADR-001 in `docs/adr/`
- [x] Implement core pipeline + deterministic unit/eval tests
- [x] Verify CI workflow passes (`ruff`/`mypy` or `cargo clippy`/`test` or `go test -race`)

## Wave 3: Launch & Design Partner Validation
- [x] Publish clean README with reproducible benchmark numbers
- [x] Add local `/FlateDecode` PDF/JSON corpus ingestion, persistent SQLite/JSON graph store, `query` CLI, and ADR-002
- [ ] Run first external design-partner or open-source release

## Wave 4: Full Product Engineering & Scope Expansion
- [x] Add multi-tenant `WorkspaceManager` (`graph.db` isolation, slug & `is_relative_to` traversal guards, append-only `audit.jsonl`)
- [x] Implement deterministic evidence scoring (`HIGH`/`MODERATE`/`PRELIMINARY` tiers) and topic consensus (`src/graph/scoring.py`)
- [x] Build zero-dependency local HTTP & OpenAPI 3.1.0 server (`SciGraphApp` / `ThreadingHTTPServer`, 2 MiB body cap, `nosniff`/`no-store` headers)
- [x] Add `ClaimGraph` regression diff (`diff_claim_graphs`), BibTeX/RIS reference exporters (`src/scigraph/diff.py`), and ADR-003

## Wave 5: Enterprise Security, Connectors & Reproducible Pipelines
- [x] Add offline-testable arXiv Atom XML & EuropePMC JSON connectors with `https://` + non-public IP SSRF guards and `MAX_RESPONSE_BYTES = 10 MiB` (`src/ingest/connectors.py`)
- [x] Implement SHA-256 & HMAC-SHA256 provenance manifests and chained `audit.jsonl` verification (`src/scigraph/provenance.py`)
- [x] Add constant-time Bearer-token RBAC (`AuthGate`), thread-safe `SlidingWindowRateLimiter`, and `GET /` interactive HTML Explorer route (`src/scigraph/security.py`, `src/scigraph/server.py`)
- [x] Build declarative batch `run_pipeline` orchestrator (`src/scigraph/pipeline.py`) and ADR-004

## Wave 6: Domain Canonicalization, Experiment ROI & Alerting
- [x] Implement `EntityCanonicalizer`, `AliasRule`, and `DEFAULT_SCIENTIFIC_ALIASES` preserving verbatim `EvidenceSpan` offsets (`src/graph/canonicalizer.py`)
- [x] Implement deterministic `prioritize_experiments` and `PrioritizedExperiment` with `LOW`/`MEDIUM`/`HIGH` cost tiers (`src/solver/prioritizer.py`)
- [x] Add `AlertPayload`, `build_alert_payload`, and SSRF-guarded `dispatch_webhook_alert` (`src/scigraph/alerts.py`)
- [x] Bind `SciGraphApp` to workspace persistence (`POST /api/v1/verify?persist=true`), `load_token_policies` (`src/scigraph/server.py`), and write ADR-005

## Wave 7: Diagrams, Tabular/PubMed Ingest, Lab Protocols & Diagnostics
- [x] Implement deterministic Mermaid (`export_mermaid_flowchart`) and Graphviz DOT (`export_graphviz_dot`) diagram exporters (`src/scigraph/diagrams.py`)
- [x] Add `load_papers_from_csv` (`.csv`/`.tsv`) and `parse_pubmed_efetch_xml` (`.xml`) wired into `load_papers_from_path` (`src/ingest/tabular.py`, `src/ingest/corpus_loader.py`)
- [x] Implement `generate_experiment_protocols` and `render_protocols_markdown` (`ExperimentProtocol`, `ProtocolStep`) (`src/solver/protocols.py`)
- [x] Add `run_doctor` and `DoctorReport` system diagnostics (`src/scigraph/doctor.py`) and write ADR-006
