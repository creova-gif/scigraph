# ADR-004: Literature Connectors, Cryptographic Provenance, Bearer RBAC, Rate Limiting, and Batch Pipeline

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

ADRs 001–003 established SciGraph's verbatim claim verification, `/FlateDecode` PDF ingestion, persistent SQLite/JSON graph storage, multi-tenant workspaces, evidence scoring, and zero-dependency local HTTP/OpenAPI server. Moving SciGraph into reproducible enterprise and CI/CD scientific workflows introduces four additional requirements without adding external runtime dependencies beyond Pydantic v2 and Python 3.12's standard library:

1. **Live & Offline-Testable Literature Connectors:** Teams need to fetch papers from arXiv and EuropePMC into `Paper` models while remaining 100% deterministic in offline unit tests and protected against SSRF and unbounded response payloads.
2. **Cryptographic Provenance & Audit Chain Verification:** Regulated research pipelines need tamper-evident SHA-256 manifests covering every paper, claim, graph snapshot, and chained `audit.jsonl` log, with optional HMAC-SHA256 signing.
3. **API Access Control, Rate Limiting & Interactive Explorer Route:** When `SciGraphApp` is shared across a team or exposed behind a proxy, it needs constant-time Bearer-token RBAC, thread-safe per-client rate limiting, and a `GET /` interactive HTML Claim-Graph Explorer route.
4. **Declarative Reproducible Batch Pipeline:** CI/CD jobs need a single deterministic `run_pipeline` entrypoint that ingests a corpus, verifies claims, persists the graph, enforces quality gates, and atomically writes multi-format reports.

## Decision

1. **Offline-Testable arXiv & EuropePMC Connectors with SSRF Guards (`src/ingest/connectors.py`):**
   - `fetch_arxiv_papers(query, max_results=10, fetcher=None)` and `fetch_europepmc_papers(query, max_results=10, fetcher=None)` query arXiv Atom XML and EuropePMC REST JSON APIs and parse responses via `parse_arxiv_atom_xml` and `parse_europepmc_json` into validated `Paper` models.
   - An injectable `Fetcher = Callable[[str], bytes]` parameter enables deterministic offline testing without network I/O; `_validate_query_and_limit` enforces non-empty queries and `1 <= max_results <= 100`.
   - `default_https_fetcher` enforces `_validate_https_url` (SSRF guard rejecting non-`https://` schemes, empty hostnames, `localhost`/`.localhost`, and private, loopback, link-local, reserved, multicast, or unspecified IP literals) and bounds reads to `MAX_RESPONSE_BYTES = 10 * 1024 * 1024` (10 MiB).

2. **SHA-256 & HMAC-SHA256 Provenance Manifests & Audit Chain Verification (`src/scigraph/provenance.py`):**
   - `ProvenanceManifest` (frozen, strict Pydantic v2 model) records `manifest_version`, `created_at_utc`, `graph_sha256`, sorted per-paper (`paper_hashes`) and per-claim (`claim_hashes`) canonical SHA-256 digests, `audit_chain_head_sha256`, and optional `signature_hmac_sha256`.
   - `compute_audit_chain_head(audit_events)` computes an iterative SHA-256 hash chain over canonically serialized `AuditEvent` records (`sort_keys=True, separators=(",", ":")`).
   - `build_provenance_manifest` generates the manifest and optional HMAC-SHA256 signature; `verify_provenance_manifest` recomputes paper, claim, graph, audit-chain, and HMAC digests using `hmac.compare_digest`, returning `(is_valid, reasons)`.

3. **Constant-Time Bearer RBAC, Sliding-Window Rate Limiter & `GET /` Explorer (`src/scigraph/security.py`, `src/scigraph/server.py`):**
   - `TokenPolicy` binds a lowercase 64-char `token_sha256` digest, `org_id`, `role` (`"reader" | "ingestor" | "admin"`), and `label`.
   - `AuthGate` hashes incoming `Authorization: Bearer <token>` headers with `hash_bearer_token` and compares digests with `hmac.compare_digest`, enforcing hierarchical roles (`reader < ingestor < admin`) and returning `401` on missing/malformed/invalid tokens and `403` on insufficient roles (defaulting to open local mode when no policies are configured).
   - `SlidingWindowRateLimiter` provides a `threading.Lock`-protected per-client sliding window with an injectable monotonic `clock`, returning `(allowed, retry_after_seconds)` so `SciGraphApp` emits HTTP `429` (`rate_limit_exceeded`) when exceeded.
   - `SciGraphApp` integrates `auth_gate` (requiring `ingestor` on `POST /api/v1/verify` and `reader` on `GET /` and `/api/*` when enabled) and `rate_limiter`, and adds `GET /` serving the interactive HTML Claim-Graph Explorer.

4. **Declarative Batch `run_pipeline` Orchestrator (`src/scigraph/pipeline.py`):**
   - `PipelineConfig` (frozen, strict Pydantic v2 model) specifies `input_path`, `store_path`, `report_dir`, `formats`, `fail_on_contradictions`, and `min_verified_papers`.
   - `run_pipeline(config)` loads papers via `load_papers_from_path`, extracts and verbatim-verifies claims, persists the `ClaimGraph` to `.json` or SQLite (`.db`, `.sqlite`, `.sqlite3`), computes topic consensus and falsifiable experiments, atomically writes requested outputs (`markdown`, `html`, `sarif`, `json`, `bibtex`, `ris`) via `NamedTemporaryFile` + `os.fsync` + `os.replace`, and returns a frozen `PipelineSummary` with `graph_sha256` and gate status `passed`.

## Alternatives Considered

- **Third-party HTTP client (`httpx` / `requests`) and JWT libraries:** Rejected to keep SciGraph's runtime dependency footprint limited to Pydantic v2 and Python 3.12's stdlib (`urllib.request`, `hashlib`, `hmac`, `threading`).
- **In-memory-only rate limiting without lock or injectable clock:** Rejected because `ThreadingHTTPServer` dispatches concurrent worker threads and deterministic unit tests require clock injection without `time.sleep`.
- **Unchained `audit.jsonl` hashing:** Rejected in favor of iterative chaining (`prev_hash:canonical_event`) so reordering, deleting, or editing any historical audit entry invalidates `audit_chain_head_sha256`.

## Consequences & Failure Modes

- **Positive:** SciGraph supports SSRF-guarded literature fetching, offline-deterministic connector tests, cryptographically verifiable graph/audit manifests, constant-time Bearer RBAC, thread-safe rate limiting, an interactive `GET /` Explorer, and reproducible CI batch pipelines with zero new dependencies.
- **Negative:** `_validate_https_url` inspects IP literals and `localhost` hostnames directly rather than resolving DNS before connection; DNS rebinding is not mitigated at the Python socket layer.
- **Mitigation:** Deploy behind an egress proxy or network policy in untrusted environments, keep `AuthGate` enabled whenever `SciGraphApp` is bound beyond `127.0.0.1`, and manage HMAC signing keys outside the repository.
