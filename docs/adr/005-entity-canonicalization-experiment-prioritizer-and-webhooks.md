# ADR-005: Entity Canonicalization, Experiment ROI Prioritization, Webhook Alerting, and Workspace-Bound HTTP Persistence

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

ADRs 001–004 established SciGraph's verbatim claim verification, persistent SQLite/JSON graph storage, multi-tenant workspaces, evidence scoring, literature connectors, cryptographic provenance, Bearer RBAC, rate limiting, and batch pipeline. Deploying SciGraph across heterogeneous scientific corpora and automated CI/CD research workflows surfaces four additional gaps:

1. **Surface-Form Synonym Fragmentation:** Different papers refer to the same intervention, outcome, or condition using distinct surface strings (e.g., `"LFP"` vs `"lithium iron phosphate"` vs `"LiFePO4"`, or `"T2DM"` vs `"type 2 diabetes"`). Rewriting the underlying `EvidenceSpan` or `quote` would break verbatim verification, so canonicalization must normalize `ClaimTuple` fields while preserving exact `EvidenceSpan` offsets.
2. **Experiment Triage & ROI Ranking:** When `propose_falsifiable_experiments` surfaces multiple candidate experiments across contradictions, research teams need a deterministic ranking that weighs contradiction severity, underlying evidence strength, and participant sample-size feasibility (`LOW` / `MEDIUM` / `HIGH` cost tiers).
3. **Automated CI/CD & Slack/Webhook Alerting:** Teams running `scigraph pipeline` or contradiction checks in CI need structured, machine-readable alerts dispatched to HTTPS webhooks with SSRF protection and offline-testable sender injection.
4. **Workspace-Bound Server Persistence & CLI RBAC Configuration:** `SciGraphApp` previously verified `POST /api/v1/verify` payloads statelessly in memory without persisting verified claims to a workspace `graph.db` or loading `TokenPolicy` configurations from disk via `scigraph serve`.

## Decision

1. **Non-Destructive Entity Canonicalization (`src/graph/canonicalizer.py`):**
   - `AliasRule` (frozen, strict Pydantic v2 model) maps a `canonical` string and `aliases` tuple within a scoped `EntityCategory` (`"intervention" | "outcome" | "condition"`).
   - `DEFAULT_SCIENTIFIC_ALIASES` provides built-in canonicalization rules covering common biomedical and materials-science entities (`CRISPR-Cas9`, `LiFePO4`, `NMC811`, `metformin`, `HbA1c`, `IL-6`, `capacity retention`, `type 2 diabetes`, `room temperature`).
   - `EntityCanonicalizer` normalizes whitespace and casefolds lookup keys (`_normalize_lookup_key`), exposes `canonicalize_text(text, category)`, `canonicalize_claim(claim)` (updating `claim_tuple` via `model_copy` while preserving `evidence_span` offsets, `quote`, and `statistical_evidence` verbatim), and `find_canonical_clusters(graph)` to group claim IDs sharing a canonical `(intervention, outcome)` pair across `>= 2` distinct surface forms.

2. **Deterministic Experiment ROI Prioritization (`src/solver/prioritizer.py`):**
   - `PrioritizedExperiment` (frozen, strict Pydantic v2 model) records `rank`, `experiment_id`, `contradiction_id`, `priority_score` (`[0.0, 1.0]`), `cost_tier` (`CostTier = Literal["LOW", "MEDIUM", "HIGH"]`), `estimated_participants`, and `reason`.
   - `prioritize_experiments(graph, contradictions, experiments)` scores each `FalsifiableExperiment` deterministically from:
     - Contradiction kind weight (`DIRECT_DIRECTION_CONFLICT`: `0.45`, `NULL_VS_SIGNIFICANT_CONFLICT`: `0.35`, `CONDITION_DEPENDENT_DIVERGENCE`: `0.25` via exhaustive `assert_never` matching).
     - Mean `evidence_strength` of `claim_a` and `claim_b` from `score_claim_evidence(graph)` weighted by `0.35`.
     - Sample-size feasibility tier and bonus (`n <= 80` -> `LOW` / `0.20`, `81 <= n <= 300` -> `MEDIUM` / `0.10`, `n > 300` -> `HIGH` / `0.02`).
   - Results are sorted descending by `(priority_score, -estimated_participants, experiment_id)` and assigned 1-based `rank` values.

3. **SSRF-Guarded Webhook & Slack Alerting (`src/scigraph/alerts.py`):**
   - `AlertPayload` (frozen, strict Pydantic v2 model) captures `event_type` (`"contradiction_detected" | "verification_failed" | "pipeline_passed"`), `severity` (`"critical" | "warning" | "info"`), `title`, `summary`, `contradiction_ids`, `rejected_claim_ids`, and `timestamp_utc`.
   - `build_alert_payload(contradictions, rejected_claim_ids=())` maps rejected claims to `critical` (`verification_failed`), contradictions without rejections to `warning` (`contradiction_detected`), and clean runs to `info` (`pipeline_passed`).
   - `dispatch_webhook_alert(webhook_url, payload, *, sender=None, timeout=10.0)` validates `webhook_url` with `_validate_https_webhook_url` (requiring `https://`, non-empty hostname, and rejecting `localhost`/`.localhost` and private, loopback, link-local, reserved, multicast, or unspecified IP literals), serializes a Slack-compatible `{"text": ..., "scigraph": ...}` JSON envelope, and supports an injectable `WebhookSender = Callable[[str, bytes], int]` for deterministic offline testing.

4. **Workspace-Bound `SciGraphApp` Persistence & `load_token_policies` (`src/scigraph/server.py`):**
   - `load_token_policies(path)` reads and validates a JSON list (or `{"policies": [...]}` object) into `tuple[TokenPolicy, ...]` for `AuthGate`.
   - `SciGraphApp` accepts optional `workspace_manager`, `org_id`, and `workspace_id` parameters, loading the workspace's persisted `ClaimGraph` on startup when no explicit `graph` is passed.
   - `POST /api/v1/verify?persist=true` validates the `persist` boolean query parameter, requires a configured `(workspace_manager, org_id, workspace_id)` binding (returning HTTP `400` otherwise), and acquires `self._lock` to call `workspace_manager.ingest_papers(org_id, workspace_id, papers)` and update `self.graph` atomically.

## Alternatives Considered

- **Mutating `EvidenceSpan` text during canonicalization:** Rejected because altering `quote` or character offsets invalidates `verify_claim_verbatim` and breaks auditability against the original PDF/text source.
- **Unbounded or non-HTTPS webhook targets:** Rejected to prevent SSRF against internal metadata endpoints (`169.254.169.254`, `127.0.0.1`, RFC 1918 ranges) and plaintext credential/payload leakage.
- **Separate `/api/v1/ingest` endpoint instead of `POST /api/v1/verify?persist=true`:** Rejected to keep the OpenAPI surface compact while reusing the existing `ingestor`-scoped `POST /api/v1/verify` validation and verification pipeline.

## Consequences & Failure Modes

- **Positive:** Cross-paper synonym clusters are surfaced without compromising verbatim evidence guarantees, proposed experiments are ranked by quantitative ROI and sample-size cost, CI/CD pipelines can emit SSRF-safe webhook alerts, and `SciGraphApp` supports persistent multi-tenant ingestion alongside file-loaded RBAC policies.
- **Negative:** Built-in `DEFAULT_SCIENTIFIC_ALIASES` only covers curated domain terms; unrecognized synonyms still require custom `AliasRule` entries. As with `src/ingest/connectors.py`, `_validate_https_webhook_url` inspects hostnames and IP literals rather than performing pre-connect DNS resolution against DNS rebinding.
- **Mitigation:** Allow custom `AliasRule` sequences in `EntityCanonicalizer` and `scigraph canonicalize`, and deploy webhook dispatchers behind egress network policies in untrusted environments.
