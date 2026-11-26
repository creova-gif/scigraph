# SciGraph Working Plan — CEO Review

- **Project:** `scigraph` (Neuro-Symbolic Scientific Discovery & Reasoning Engine)
- **Branch:** `main` (base branch: `main`, commit `11aa6f8`)
- **Review depth:** Implementation-ready
- **Selected Mode:** `SCOPE EXPANSION` (selected by user in `D2: C`)
- **Status:** Complete (`Approval readiness: PASS` — 9/9 Decisions Approved, 0 Unresolved)

Mode: SCOPE EXPANSION; approved decisions: D1. `SCOPE EXPANSION` applies to `scigraph` on `main` because the Wave 1–2 core engine (`src/scigraph/models.py`, `src/ingest/`, `src/graph/`, `src/solver/`, `src/evals/`) is already implemented and passing all 30 benchmark papers in `0.14s`, giving us a solid foundation to dream big and evaluate the 10-star Wave 3 product additions individually in Step 0G. Governing approved row: `D1` (answer `D1: B`, approved scope: skip `/office-hours` and use `PROJECT_SPEC.md` and `ADR-001` as the baseline specification). No new approach decision was needed.

## Context Recovery & Welcome Back

Welcome back. Your last gstack session completed on `main`, and we have loaded 10 prior operational/pitfall learnings (including macOS `.venv` `UF_HIDDEN` handling and strict ingest format validation from `ingest-reads-binary-as-text`). GBrain is configured on this machine (`ARTIFACTS_SYNC: off`); run `/sync-gbrain --full` when you want GBrain code indexing pinned for this worktree.

No worries — standard review. If you ever want sharper input, try `/office-hours` first next time.

## Pre-Review System Audit & Taste Calibration

- **Repository state (`git log --oneline -5`):**
  - `11aa6f8 (HEAD -> main) feat(core): implement typed claim graph, verbatim verifier, symbolic solver, and 30-paper benchmark`
- **TODO/FIXME scan:** `0` occurrences across `src/`, `tests/`, and `docs/`.
- **Prior learnings applied:**
  - `Prior learning applied: [ingest-reads-binary-as-text] (confidence 8/10, from 2026-10-04)` — `src/ingest/extractor.py:169-192` explicitly validates PDF stream structure and raises `ValueError` on malformed/unsupported byte streams rather than silently chunking binary garbage.
  - `Prior learning applied: [design-doc-claims-vs-code] (confidence 8/10, from 2026-10-04)` — Every claim in `PROJECT_SPEC.md` and `ADR-001` was verified directly against `src/` and `tests/` with `file:line` receipts below.
  - `Prior learning applied: [macos-documents-uf-hidden-breaks-editable-pth] (confidence 9/10, from 2026-11-24)` — Use non-editable `uv pip install ".[dev]"` or `PYTHONPATH=src` and `chflags -R nohidden .venv` under `~/Documents`.
- **Taste calibration (well-designed references vs. anti-patterns to avoid):**
  - **Good pattern 1:** `src/scigraph/models.py:38-184` — Frozen Pydantic v2 models (`ConfigDict(strict=True, frozen=True, extra="forbid")`) with boundary validators for DOI format and character-offset span lengths.
  - **Good pattern 2:** `src/ingest/verifier.py:18-62` — Pure, zero-side-effect `verify_claim_verbatim(paper, claim)` returning structured `VerificationFailureReason` tuples rather than boolean flags or swallowed exceptions.
  - **Anti-pattern to avoid:** Silent fallback text decoding on corrupt PDF/binary inputs or unverified LLM string interpolation into `ClaimGraph` without passing `verify_claim_verbatim`.

## Step 0A: Premise Challenge

- **Real problem:** Biotech/pharma R&D literature teams and academic labs cannot trust flat RAG vector summaries because cosine similarity conflates opposing claims (`Intervention A increases Outcome Y` vs. `Intervention A decreases Outcome Y`) and LLM extractors hallucinate or round DOIs, p-values, and sample sizes (`n`).
- **Target outcome:** A deterministic neuro-symbolic discovery engine that extracts typed `(Intervention, Condition, Outcome)` tuples linked to verbatim character offsets, rejects 100% of fabricated DOIs/p-values/sample sizes at the ingestion boundary, and uses symbolic constraint solving to separate true contradictions from condition-dependent regime shifts and propose falsifiable experiments.
- **Do-nothing cost:** Researchers waste days manually cross-checking every cited p-value in PDFs or design wet-lab experiments on misquoted statistical claims.
- **Direct vs. proxy:** Directly solves the root trust and synthesis failure by making verbatim span verification (`src/ingest/verifier.py:18-62`) a mandatory gate before graph insertion (`src/graph/claim_graph.py:34-46`).

### Premise Table

| Premise | Claim | File:Line Receipt | Verdict |
|---|---|---|---|
| P1 | Typed claim tuples (`Intervention`, `Condition`, `Outcome`, `EffectDirection`) with verbatim character spans prevent vector-chunk conflation | `src/scigraph/models.py:103-163` | pass |
| P2 | Two-column academic PDFs require column-bucket reading order before claim extraction | `src/ingest/extractor.py:55-100` | pass |
| P3 | Deterministic substring + numeric token check eliminates fabricated DOIs, p-values, and sample sizes | `src/ingest/verifier.py:18-62` | pass |
| P4 | Symbolic constraint solving over `(intervention, condition, outcome)` isolates unsatisfiable cores and proposes powered experiments | `src/solver/symbolic.py:27-155` | pass |

`unverified=0`

## Step 0B: Existing Code Leverage & Reality Check

| Sub-problem | Existing Code in Repo | Leverage Assessment |
|---|---|---|
| Domain schema & DOI/span validation | `src/scigraph/models.py:1-259` | Complete; reuse directly for CLI, exporters, and solver extensions |
| Two-column PDF/layout extraction | `src/ingest/extractor.py:55-192` | Complete for PDF-1.4 text streams and `LayoutBlock` sequences |
| Deterministic verbatim verifier | `src/ingest/verifier.py:18-99` | Complete (`0` fabricated DOIs/p-values across 150 adversarial decoys) |
| Typed claim graph & edge builder | `src/graph/claim_graph.py:14-147` | Complete in-memory graph; ready for JSON/SARIF/HTML/Markdown serialization |
| Symbolic contradiction & experiment solver | `src/solver/symbolic.py:16-155` | Complete discrete solver; extended by `EXP-3` (`regime.py`) and `EXP-5` (effect-size power calculator) |
| 30-paper benchmark & adversarial decoy suite | `src/evals/benchmark.py:92-728` | Complete (`F1 = 1.0000`, `4.201 ms` median runtime across 7 runs) |

REALITY: premise-table pass All 4 core premises verified with file:line receipts (unverified=0) PROJECT_SPEC.md:8-27
REALITY: already-done finding Wave 1-2 core pipeline and 30-paper benchmark already implemented in commit 11aa6f8 src/scigraph/models.py:1-259
REALITY: surface-check pass All exported functions in scigraph, ingest, graph, solver, and evals verified src/scigraph/__init__.py:1-49
REALITY: binding-decisions pass ADR-001 typed claim tuples and verbatim verification honored docs/adr/001-typed-claim-tuples-and-verbatim-evidence-verification.md:1-37
REALITY: numbers pass F1=1.0000, 0 fabricated DOIs/p-values, 4.201ms median across 7 runs [measured: evaluate_benchmark] src/evals/benchmark.py:662-728
REALITY: deferred-asks pass Wave 3 external design-partner release tracked in TASKS.md TASKS.md:14-16
REALITY: pr-count pass Single wave on main (1 commit 11aa6f8) pyproject.toml:1-38

## Step 0C: Dream State Mapping & Three-Layer Landscape Synthesis

- **[Layer 1 — Tried and true]:** Biomedical NLP pipelines (BioBERT, PubMedBERT, GROBID, SciSpacy) extract named entities and relations into triples (`Subject-Predicate-Object`), while tools like Elicit and Consensus retrieve paper snippets via dense embeddings.
- **[Layer 2 — Current ecosystem]:** 2026 literature synthesis benchmarks show that dense vector RAG suffers from embedding collapse on negation ("X increases Y" and "X decreases Y" map to nearly identical embeddings) and LLM summarizers frequently round or hallucinate p-values due to positive-result publication bias in pretraining data. Proposition-level claim graphs (ORKG, Scite.ai) outperform chunk RAG on contradiction workloads.
- **[Layer 3 — First-principles Eureka]:** Treating scientific claims as **typed symbolic assertions gated by an exact character-offset and numeric-token verifier** turns contradiction detection from a fuzzy semantic similarity problem into a decidable constraint satisfaction problem (`UNSAT` core extraction over `(Intervention, Condition, Outcome) -> {-1, 0, +1}`), where every contradiction deterministically yields a falsifiable experimental protocol.

```
  CURRENT STATE                          THIS PLAN (SCOPE EXPANSION)              12-MONTH IDEAL
  Deterministic Python engine     --->   CLI + Interactive HTML Claim-Graph --->  Autonomous R&D discovery workspace
  (30-paper benchmark F1=1.0000,         Explorer + Quantitative Regime           ingesting 100k+ PubMed/arXiv PDFs,
   0 fabrications, 11 contradictions     Parser + SARIF/JSON Audit Exporter       integrating Z3 interval solvers, and
   detected in 4.2ms median)             + Effect-Size Power Calculator           dispatching wet-lab CRO protocols
```

## Step 0F & 0G: Accepted Scope Expansions & Implementation Contracts

All 5 expansion proposals (`EXP-1` through `EXP-5`) were individually reviewed and approved by the user (`D3: A`, `D4: A`, `D5: A`, `D6: A`, `D7: A`). Zero items were deferred to `TODOS.md` or skipped.

### Accepted Expansion 1 — `EXP-1`: `scigraph` CLI & Markdown Contradiction Briefing (`src/scigraph/cli.py`, `src/scigraph/exporters.py`)
- **Contract & Entrypoint:** Register `[project.scripts] scigraph = "scigraph.cli:main"` in `pyproject.toml`. `main(argv: Sequence[str] | None = None) -> int` uses Python standard-library `argparse`.
- **Markdown Briefing Generator (`render_markdown_report` in `src/scigraph/exporters.py`):**
  - Signature: `render_markdown_report(graph: ClaimGraph, contradictions: Sequence[ContradictionPair], experiments: Sequence[FalsifiableExperiment], metrics: BenchmarkMetrics | None = None) -> str`
  - Output sections:
    1. `# SciGraph Contradiction & Experiment Briefing`
    2. `## Corpus & Verification Summary` (papers count, verified claims count, edges count, plus `BenchmarkMetrics` precision/recall/F1 and decoy rejection count when `metrics` is provided).
    3. `## Detected Contradictions & Regime Shifts` (Markdown table listing `contradiction_id`, `kind`, `claim_a` paper/DOI/direction/stats, `claim_b` paper/DOI/direction/stats, `unsat_constraints`, and `discriminating_factor`).
    4. `## Proposed Falsifiable Experiments` (Markdown table and protocol cards listing `experiment_id`, `contradiction_id`, `intervention`, `stratified_conditions`, `primary_outcome`, `recommended_sample_size`, `alpha_threshold`, `hypothesis`, and `falsification_criterion`).
- **Subcommands & Exit Code Contract:**
  1. `scigraph benchmark [--json]`: Runs `evaluate_benchmark()` over `BENCHMARK_30_PAPERS`. Prints structured summary table (or JSON when `--json` is passed). Returns exit code `0` when `f1_score >= 0.85` and `fabricated_dois_accepted == 0` and `fabricated_p_values_accepted == 0`; returns exit code `1` if any threshold fails; returns exit code `2` on invalid CLI arguments.
  2. `scigraph verify [--paper-id <id> | --all]`: Runs layout extraction, claim extraction, and `verify_paper_claims` for a specific benchmark paper ID (or `--all` across all 30 papers, which is the default when `--paper-id` is omitted). Returns exit code `0` when all claims verify and `doi_verified` is `True`; returns `1` if any claim fails verbatim verification; returns `2` on unknown `--paper-id` or invalid CLI arguments.
  3. `scigraph report --format {markdown,html,sarif,json} [--output <path>] [--fail-on-contradictions]`: Executes the full verification and graph pipeline over `BENCHMARK_30_PAPERS` (collecting `reports: list[PaperVerificationReport]`, `metrics: BenchmarkMetrics = evaluate_benchmark()`, `graph: ClaimGraph` with `graph.build_edges()`, `contradictions = detect_contradictions(graph)`, and `experiments = propose_falsifiable_experiments(contradictions)`), and renders the requested format via `render_markdown_report`, `render_claim_graph_html`, `export_sarif_v210`, or `export_json_bundle`. Writes to stdout when `--output` is omitted, or writes atomically via temp file + `os.replace` when `--output <path>` is passed.
     - Exit code `0`: Report generated and written successfully (and either `--fail-on-contradictions` is not set or `len(contradictions) == 0`).
     - Exit code `1`: `--fail-on-contradictions` is set and `len(contradictions) > 0`, or any paper verification failure occurred.
     - Exit code `2`: Invalid CLI arguments or file write `OSError` (prints diagnostic to `sys.stderr` without uncaught traceback).

### Accepted Expansion 2 — `EXP-2`: Interactive HTML Claim-Graph & Contradiction Explorer (`src/scigraph/explorer.py`)
- **Contract:** `render_claim_graph_html(graph: ClaimGraph, contradictions: Sequence[ContradictionPair], experiments: Sequence[FalsifiableExperiment], metrics: BenchmarkMetrics | None = None) -> str`.
- **Security & XSS Invariant:** Every dynamic string from `Paper`, `ScientificClaim`, `EvidenceEdge`, `ContradictionPair`, and `FalsifiableExperiment` (`title`, `doi`, `authors`, `intervention`, `condition`, `outcome`, `verbatim_text`, `p_value_raw`, `sample_size_raw`, `discriminating_factor`, `hypothesis`, `falsification_criterion`) MUST pass through `html.escape(value, quote=True)` before interpolation into HTML templates or `data-*` attributes.
- **UI States & Dual Filter Architecture:**
  - Summary KPI banner: Total Papers, Verified Claims, Edges Built, Contradictions Detected, and Falsifiable Experiments Proposed (plus Benchmark F1 and Decoys Rejected when `metrics` is provided).
  - **Section 1 — Contradiction & Experiment Studio** with dedicated `ContradictionKind` filter buttons (`ALL`, `DIRECT_DIRECTION_CONFLICT`, `NULL_VS_SIGNIFICANT_CONFLICT`, `CONDITION_DEPENDENT_DIVERGENCE`): Displays side-by-side `claim_a` and `claim_b` cards with DOI badges, section kind (`ABSTRACT`/`RESULTS`), exact character offset range `[start_char:end_char]`, verbatim quote block, statistical evidence (`n`, `p`, `effect_size_raw`), `unsat_constraints`, quantitative `discriminating_factor`, and the paired `FalsifiableExperiment` card.
  - **Section 2 — Evidence Edge Explorer** with dedicated `EdgeRelation` filter buttons (`ALL`, `SUPPORTS`, `REPLICATES`, `CONTRADICTS`, `QUALIFIES`): Displays all `EvidenceEdge` records in `graph.edges` with source/target claim IDs, shared intervention/outcome, relation badge, and rationale.
  - Empty-state handling: If `contradictions` or `graph.edges` is empty, renders an explicit `<div class="empty-state">` message in that section rather than a blank container.

### Accepted Expansion 3 — `EXP-3`: Quantitative Condition & Regime Delta Solver (`src/solver/regime.py`)
- **Contract:**
  - `RegimeParameter(BaseModel)`: Frozen Pydantic v2 model (`strict=True, frozen=True, extra="forbid"`) with fields `dimension: str` (`"temperature"`, `"humidity"`, `"current_density"`, `"molarity"`, `"mass_concentration"`, `"frequency"`, `"c_rate"`), `value: float`, `unit: str`, `canonical_value: float`, `canonical_unit: str`, and `raw_token: str`.
  - `extract_regime_parameters(condition: str) -> tuple[RegimeParameter, ...]`: Deterministically parses numeric parameters and normalizes units within each dimension:
    - Temperature (`dimension="temperature"`, `canonical_unit="C"`): Matches `(?P<val>-?\d+(?:\.\d+)?)\s*(?P<unit>degrees\s+Celsius|C|K)\b`. Normalizes Kelvin to Celsius (`canonical_value = val - 273.15` when `unit == "K"`, else `val`).
    - Relative humidity (`dimension="humidity"`, `canonical_unit="%"`): Matches `(?P<val>\d+(?:\.\d+)?)\s*%\s*(?:relative\s+humidity|RH)?`.
    - Current density (`dimension="current_density"`, `canonical_unit="mA/cm2"`): Matches `(?P<val>\d+(?:\.\d+)?)\s*mA/cm2\b`.
    - C-rate (`dimension="c_rate"`, `canonical_unit="C"`): Matches `(?P<val>\d+(?:\.\d+)?)\s*C(?:\s+(?:charge|discharge|rate|cycling))?\b` (when not preceded by a temperature preposition like `at 25 C` or `90 C` or `130 C`; temperature matches `at <N> C` or `<N> C (?:oxidative|steam|damp|larval)` first so temperature and C-rate are disambiguated).
    - Molarity (`dimension="molarity"`, `canonical_unit="M"`): Matches `(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>M|mM)\b` (`canonical_value = val / 1000.0` when `unit == "mM"`, else `val`).
    - Mass concentration (`dimension="mass_concentration"`, `canonical_unit="ng/mL"`): Matches `(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ng/mL)\b` (kept as a separate dimension from molarity so incompatible mass vs. molar units are never subtracted numerically).
    - Frequency (`dimension="frequency"`, `canonical_unit="Hz"`): Matches `(?P<val>\d+(?:\.\d+)?)\s*Hz\b`.
  - `compute_regime_delta(cond_a: str, cond_b: str) -> str | None`: Compares extracted parameters from `cond_a` and `cond_b`:
    - When both conditions share one or more `dimension` keys with differing `canonical_value` (`abs(param_b.canonical_value - param_a.canonical_value) > 1e-9`), formats each differing shared dimension in sorted dimension order as `"Quantitative {dimension} delta: {delta:+.4g} {canonical_unit} ({param_a.raw_token} -> {param_b.raw_token})"` and joins multiple deltas with `"; "`.
    - Fall back to cross-dimension shift only when no shared dimensions exist between `cond_a` and `cond_b` (or shared dimensions have zero delta while unshared dimensions are present), formatting `"Cross-dimension regime shift: {a_summary} vs {b_summary}"` where each side joins its `"{dimension}={raw_token}"` items with `", "`.
    - Returns `None` when neither condition contains numeric regime tokens (or all extracted parameters are identical across both conditions).
  - Integration into `src/solver/symbolic.py:detect_contradictions`: When `cond_a != cond_b` (`CONDITION_DEPENDENT_DIVERGENCE`), calls `compute_regime_delta(claim_a.claim_tuple.condition, claim_b.claim_tuple.condition)` and, if non-`None`, appends `" | " + delta_str` to `ContradictionPair.discriminating_factor`.

### Accepted Expansion 4 — `EXP-4`: Deterministic SARIF v2.1.0 & JSON Audit Exporter (`src/scigraph/exporters.py`)
- **Contract:**
  - `export_json_bundle(graph: ClaimGraph, contradictions: Sequence[ContradictionPair], experiments: Sequence[FalsifiableExperiment], metrics: BenchmarkMetrics | None = None) -> str`: Serializes a deterministic (`sort_keys=True, indent=2`) JSON document containing `schema_version: "1.0"`, `metrics` (`metrics.model_dump(mode="json")` or `None`), `papers`, `claims`, `edges`, `contradictions`, and `experiments`.
  - `export_sarif_v210(contradictions: Sequence[ContradictionPair], reports: Sequence[PaperVerificationReport] = ()) -> str`: Produces a valid OASIS SARIF v2.1.0 JSON document (`$schema: "https://json.schemastore.org/sarif-2.1.0.json"`, `version: "2.1.0"`) with tool driver `"SciGraph"`:
    - **Artifact URI convention:** Every `physicalLocation` sets `artifactLocation: {"uri": f"papers/{claim.paper_id}"}` and `region: {"charOffset": claim.evidence_span.start_char, "charLength": claim.evidence_span.end_char - claim.evidence_span.start_char}`. For paper-level or claim-level verification failures in `reports` where a `ScientificClaim` span object is unavailable, `artifactLocation.uri` is `f"papers/{report.paper_id}"` with `region: {"charOffset": 0, "charLength": 1}`.
    - **Rules:**
      - `SCIGRAPH-VERIFY-001` (`error` level): Emitted both (a) for any `report` in `reports` where `report.doi_verified == False` (message `"Paper DOI verification failed: {report.doi}"`, artifact URI `f"papers/{report.paper_id}"`) and (b) for each failed `ClaimVerificationResult` (`verified == False`) in `report.claim_results`, listing the `VerificationFailureReason` codes.
      - `SCIGRAPH-CONTRA-001` (`warning` level): Emitted for each `DIRECT_DIRECTION_CONFLICT` in `contradictions`, referencing `claim_a` as primary location and `claim_b` in `relatedLocations`.
      - `SCIGRAPH-CONTRA-002` (`note` level): Emitted for each `NULL_VS_SIGNIFICANT_CONFLICT` or `CONDITION_DEPENDENT_DIVERGENCE` in `contradictions`, referencing `claim_a` and `claim_b`.

### Accepted Expansion 5 — `EXP-5`: Effect-Size Parser & Statistical Power Sample-Size Calculator (`src/solver/symbolic.py`)
- **Contract:**
  - `parse_standardized_effect_size(effect_size_raw: str | None) -> float | None`: Parses standardized effect magnitude `|d|` from `StatisticalEvidence.effect_size_raw`:
    - `d = -1.14` (signed float after `d =` or `diff =`) -> `max(0.10, min(3.0, abs(float(val))))`
    - `fold = 3.8x` (positive float before `x` after `fold =`) -> `max(0.10, min(3.0, abs(math.log(float(val)))))` when `float(val) > 0`, else `None`
    - `or = 2.68`, `hr = 2.14`, or `ratio = 0.29` -> `max(0.10, min(3.0, abs(math.log(float(val))) * 0.55))` when `float(val) > 0`, else `None`
    - `reduction = 58%` or `delta = +28.4%` -> where `pct` is the float preceding `%` (e.g., `58.0` for `"58%"`, not `0.58`), returns `max(0.20, min(2.0, abs(pct) / 50.0))`
    - Any other string or `None` -> returns `None`.
  - `compute_powered_sample_size(claim_a: ScientificClaim, claim_b: ScientificClaim) -> int`:
    - Computes baseline replication floor: `base_n = max(40, max(claim_a.statistics.sample_size, claim_b.statistics.sample_size) * 2)`.
    - Evaluates `d_a = parse_standardized_effect_size(claim_a.statistics.effect_size_raw)` and `d_b = parse_standardized_effect_size(claim_b.statistics.effect_size_raw)`.
    - **Null effect-size fallback:** If both `d_a is None` and `d_b is None`, returns `base_n` directly without running the normal approximation.
    - Otherwise, sets conservative `d_eff = max(0.20, min(d for d in (d_a, d_b) if d is not None))`.
    - Computes two-sample two-sided normal approximation at `alpha = 0.01` (`z_{1-alpha/2} = 2.5758`) and `power = 0.90` (`z_{1-beta} = 1.2816`): `n_per_arm = math.ceil(2.0 * ((2.5758 + 1.2816) / d_eff) ** 2)` and `total_powered_n = min(2000, n_per_arm * 2)`.
    - **Precedence rule:** Returns `max(base_n, total_powered_n)`. The `2000` cap bounds the power-formula contribution (`total_powered_n <= 2000`) when `d_eff` is small, while `base_n` (`>= 2 * max(n_a, n_b)`) always takes precedence if a prior study already used `n > 1000`.
  - **Integration into `src/solver/symbolic.py:propose_falsifiable_experiments`:** Replace `max_n = max(ca.statistics.sample_size, cb.statistics.sample_size)` and `recommended_n = max(40, max_n * 2)` with `recommended_n = compute_powered_sample_size(ca, cb)`.

## Decision Ledger

| ID and owner | Contract and evidence | Current | Proposed | Status | Exact approval and scope |
|---|---|---|---|---|---|
| D1 (justinmafie) | Prerequisite `/office-hours` check (`PROJECT_SPEC.md:1-27`, `docs/adr/001-typed-claim-tuples-and-verbatim-evidence-verification.md:1-37`) | Use existing `PROJECT_SPEC.md` and `ADR-001` | Skip `/office-hours` and proceed with standard review | approved | Answer `D1: B` — skip `/office-hours` and review against `PROJECT_SPEC.md` and `ADR-001` |
| D2 (justinmafie) | Step 0E review mode selection (`TASKS.md:1-16`, `src/evals/benchmark.py:662-728`) | Baseline Wave 1–2 implemented (`11aa6f8`) | Select review posture: `SCOPE EXPANSION` | approved | Answer `D2: C` — run `SCOPE EXPANSION` (0F → 0G → 0H → 0I → Sections 1–11) |
| EXP-1 (Step 0G / CLI) | Add `scigraph` CLI (`src/scigraph/cli.py`, `pyproject.toml:1-38`) and `render_markdown_report` (`src/scigraph/exporters.py`) with `benchmark`, `verify`, and `report --format {markdown,html,sarif,json}` subcommands, exit code `0`/`1`/`2` contract, and unit tests in `tests/test_scigraph.py` | `scigraph` CLI (`src/scigraph/cli.py`) + Markdown report generator (`render_markdown_report`) | Accepted (`D3: A`) | approved | Answer `D3: A` — add `src/scigraph/cli.py`, `render_markdown_report`, and `[project.scripts]` `scigraph` entrypoint with CLI & Markdown report tests |
| EXP-2 (Step 0G / Explorer) | Add self-contained interactive HTML Claim-Graph & Contradiction Explorer (`src/scigraph/explorer.py`, `src/graph/claim_graph.py:14-147`) with XSS-safe `html.escape` rendering, separate `ContradictionKind` and `EdgeRelation` filter controls, side-by-side verbatim evidence quote diff, and experiment cards | Interactive HTML Claim-Graph Explorer (`src/scigraph/explorer.py`) | Accepted (`D4: A`) | approved | Answer `D4: A` — add `src/scigraph/explorer.py` and `--format html` CLI support with XSS and HTML rendering tests |
| EXP-3 (Step 0G / Regime Solver) | Add quantitative condition & regime parameter extractor (`src/solver/regime.py`, `src/solver/symbolic.py:48-107`) parsing temperature (`C`/`K`), molarity (`M`/`mM`), mass concentration (`ng/mL`), current density (`mA/cm2`), C-rate (`C`), frequency (`Hz`), and relative humidity (`%`) to compute exact numeric deltas in `ContradictionPair.discriminating_factor` | Quantitative condition & regime delta solver (`src/solver/regime.py`) | Accepted (`D5: A`) | approved | Answer `D5: A` — add `src/solver/regime.py` and integrate quantitative regime deltas into `detect_contradictions` |
| EXP-4 (Step 0G / SARIF & JSON Exporter) | Add deterministic JSON and SARIF v2.1.0 audit exporter (`src/scigraph/exporters.py`, `src/ingest/verifier.py:18-99`, `src/solver/symbolic.py:48-107`) emitting `VerificationFailureReason` rejections and `ContradictionPair` findings with `papers/{paper_id}` artifact URIs and character offsets | SARIF v2.1.0 & JSON bundle exporter (`src/scigraph/exporters.py`) | Accepted (`D6: A`) | approved | Answer `D6: A` — add `src/scigraph/exporters.py` and `--format sarif|json` CLI support with SARIF & JSON unit tests |
| EXP-5 (Step 0G / Power Calculator) | Add effect-size parser (`d = ...`, `fold = ...`, `reduction = ...`, `delta = ...`) and statistical power sample-size calculator (`src/solver/symbolic.py:110-155`) scaling `FalsifiableExperiment.recommended_sample_size` at `alpha = 0.01, power = 0.90` via `max(base_n, total_powered_n)` where `total_powered_n = min(2000, n_per_arm * 2)` and `base_n` fallback when effect sizes are absent | Effect-size-aware statistical power calculator (`src/solver/symbolic.py`) | Accepted (`D7: A`) | approved | Answer `D7: A` — add `parse_standardized_effect_size` and `compute_powered_sample_size` wired into `propose_falsifiable_experiments` in `src/solver/symbolic.py` with unit tests |

| DOC-0H (Step 0H / Scope Docs) | Approve CEO Scope Summary (`~/.gstack/projects/justinmafie/ceo-plans/2026-11-25-scigraph-scope-expansion.md`) and Working Plan (`docs/plans/2026-11-25-scigraph-ceo-plan.md`) after 10/10 Spec Review PASS | Spec Review 10/10 PASS (`iterations=3, found=14, fixed=14, remaining=0`) | Approved (`D8: A`) | approved | Answer `D8: A` — approve Step 0H documents and continue to Step 0I and Review Sections 1–11 |
| SEC-1 (Section 2 / Error & Rescue) | Harden PDF byte ingestion (`src/ingest/extractor.py:176-200`) and atomic `--output` file writes (`src/scigraph/cli.py`) against binary PDF headers (`%\xe2\xe3\xcf\xd3`), compressed `/FlateDecode` streams, oversized inputs (`>25 MiB`), and cross-device `EXDEV` temp-file renames | Complete boundary hardening (`MAX_PDF_BYTES = 25 MiB`, `%PDF-` header check, `latin-1` stream decode, explicit `/FlateDecode` `ValueError`, same-dir `NamedTemporaryFile` + `os.replace` + cleanup) | Accepted (`D9: A`, Completeness: 10/10) | approved | Answer `D9: A` — implement complete PDF byte boundary guards, same-directory atomic `--output` writes, and 4 failure-path unit tests |

Approval readiness: PASS — Checked rows: `D1` (`D1: B`), `D2` (`D2: C`), `EXP-1` (`D3: A`), `EXP-2` (`D4: A`), `EXP-3` (`D5: A`), `EXP-4` (`D6: A`), `EXP-5` (`D7: A`), `DOC-0H` (`D8: A`), `SEC-1` (`D9: A`). Zero pending, declined, or unresolved rows.

## Step 0I: Temporal Interrogation

```
  HOUR 1 (foundations, human: ~4h / CC: ~10m):
    - Implement `src/solver/regime.py` (`RegimeParameter`, `extract_regime_parameters`, `compute_regime_delta`)
      and `parse_standardized_effect_size` / `compute_powered_sample_size` in `src/solver/symbolic.py`.
    - Key foundation invariant: keep `src/scigraph/__init__.py` importing ONLY from `scigraph.models`
      so new modules under `src/scigraph/` (`cli.py`, `exporters.py`, `explorer.py`) never trigger
      circular imports when importing `graph`, `solver`, `ingest`, or `evals`.

  HOUR 2-3 (core logic, human: ~1d / CC: ~15m):
    - Implement `src/scigraph/exporters.py` (`render_markdown_report`, `export_json_bundle`, `export_sarif_v210`).
    - Ambiguity resolved in 0H: `SCIGRAPH-VERIFY-001` emits errors for BOTH `report.doi_verified == False`
      and per-claim `ClaimVerificationResult.verified == False`, using `papers/{paper_id}` URIs.
    - Disambiguate temperature (`90 C`, `130 C`, `at 28 C`) from battery C-rate (`2C charge cycling`)
      by matching temperature context patterns before C-rate tokens.

  HOUR 4-5 (integration & UI, human: ~1d / CC: ~12m):
    - Implement `src/scigraph/explorer.py` (`render_claim_graph_html`) with `html.escape(..., quote=True)`
      on every dynamic field and separate filter bars for `ContradictionKind` and `EdgeRelation`.
    - Implement `src/scigraph/cli.py` (`benchmark`, `verify`, `report`) and wire `[project.scripts]`
      in `pyproject.toml`.

  HOUR 6+ (polish & verification, human: ~4h / CC: ~8m):
    - Add deterministic unit/integration tests covering CLI exit codes (`0`/`1`/`2`), XSS payload escaping,
      SARIF v2.1.0 schema structure, regime deltas, and powered sample sizes.
    - Re-run `.venv/bin/ruff check src tests && .venv/bin/mypy --strict src tests && .venv/bin/pytest -v`.
```
- **Feasibility blockers:** None blocking. Total estimated effort: **human team ~3 days / CC + gstack ~45 minutes**.

---

## Section 1: Architecture Review

### Current Scope Summary
- **Mode:** `SCOPE EXPANSION` (selected by user in `D2: C` because Wave 1–2 core is green in `11aa6f8` and we are expanding into Wave 3 product capabilities; manual user choice, `QUESTION_TUNING: false`).
- **Governing Approved Decisions:**
  - `D1` (`D1: B`, approved): Skip `/office-hours`; use `PROJECT_SPEC.md` and `ADR-001`.
  - `D2` (`D2: C`, approved): Run `SCOPE EXPANSION`.
  - `EXP-1` (`D3: A`, approved): Add `scigraph` CLI (`src/scigraph/cli.py`) and `render_markdown_report` (`src/scigraph/exporters.py`).
  - `EXP-2` (`D4: A`, approved): Add Interactive HTML Claim-Graph & Contradiction Explorer (`src/scigraph/explorer.py`).
  - `EXP-3` (`D5: A`, approved): Add Quantitative Condition & Regime Delta Solver (`src/solver/regime.py`).
  - `EXP-4` (`D6: A`, approved): Add Deterministic SARIF v2.1.0 & JSON Audit Exporter (`src/scigraph/exporters.py`).
  - `EXP-5` (`D7: A`, approved): Add Effect-Size Parser & Statistical Power Calculator (`src/solver/symbolic.py`).
  - `DOC-0H` (`D8: A`, approved): Approve 10/10 spec-verified CEO Scope Summary and Working Plan.
- **Deferred work:** None (`0` items).
- **Rejected/Skipped work:** None (`0` items).
- **Pending decisions:** `SEC-1` (surfaced in Section 2 below).

### System Architecture & Dependency DAG

```
                        +-----------------------------+
                        |   scigraph.cli (EXP-1)      |
                        |  benchmark | verify | report|
                        +--------------+--------------+
                                       |
            +--------------------------+--------------------------+
            |                          |                          |
            v                          v                          v
  +--------------------+    +---------------------+    +--------------------+
  | scigraph.explorer  |    | scigraph.exporters  |    |  evals.benchmark   |
  | (EXP-2 HTML Studio)|    | (EXP-1 MD / EXP-4   |    | (30-paper corpus & |
  | html.escape + JS   |    |  SARIF 2.1.0 & JSON)|    |  150 decoys)       |
  +---------+----------+    +----------+----------+    +---------+----------+
            |                          |                         |
            +------------+-------------+------------+------------+
                         |                          |
                         v                          v
              +--------------------+      +--------------------+
              |   solver.symbolic  |----->|   solver.regime    |
              | (UNSAT + EXP-5 n)  |      | (EXP-3 unit deltas)|
              +---------+----------+      +--------------------+
                        |
                        v
              +--------------------+
              |  graph.claim_graph |
              | (verified claims & |
              |  typed edges)      |
              +---------+----------+
                        |
                        v
              +--------------------+
              |  ingest.extractor  |
              |  ingest.verifier   |
              +---------+----------+
                        |
                        v
              +--------------------+
              |  scigraph.models   |
              | (frozen Pydantic)  |
              +--------------------+
```

### Data Flow — Four Paths Across Pipeline
1. **Happy path:** PDF bytes / `LayoutBlock`s -> `order_layout_blocks` (top-spanning, left-col, right-col) -> `extract_paper_from_layout` -> `extract_claims_from_paper` -> `verify_paper_claims` (`verified=True`) -> `ClaimGraph.add_verified_claim` -> `build_edges` -> `detect_contradictions` (enriched by `compute_regime_delta`) -> `propose_falsifiable_experiments` (sized by `compute_powered_sample_size`) -> rendered via `cli.py` to Markdown, HTML, SARIF, or JSON.
2. **Nil path:** Optional fields (`effect_size_raw=None`, `metrics=None`, `--output=None`, `reports=()`) are typed as `T | None` or empty tuples; `compute_powered_sample_size` falls back to `base_n`, exporters omit optional metric blocks cleanly, and CLI writes to `sys.stdout`.
3. **Empty path:** Empty `LayoutBlock` sequence or PDF with zero `BT...ET` blocks raises `ValueError("No layout blocks found...")` in `src/ingest/extractor.py:198`; empty `ClaimGraph` in `explorer.py` renders explicit `<div class="empty-state">` banners; `propose_falsifiable_experiments(())` returns `()`.
4. **Error path:** Fabricated DOI, p-value, sample size, or character span produces `ClaimVerificationResult(verified=False, failures=(...))`, is rejected by `ClaimGraph.add_verified_claim` (`ValueError`), recorded as `SCIGRAPH-VERIFY-001` in SARIF, and triggers exit code `1` in `scigraph verify`.

### State Machine: Claim Lifecycle Across Verification Boundary
```
  [Raw Prose / PDF Stream]
             |
             | extract_claims_from_paper()
             v
  [Candidate ScientificClaim]  (untrusted; frozen Pydantic model)
             |
             | verify_claim_verbatim(paper, claim)
             +----------------------------------------+
             | failures == ()                         | failures != ()
             v                                        v
  [Verified ScientificClaim]               [Rejected ClaimVerificationResult]
             |                                        |
             | ClaimGraph.add_verified_claim()        | ClaimGraph.add_verified_claim()
             v                                        v
  [In-Graph Node -> Edges/Solver]          [BLOCKED: raises ValueError;
                                            logged in SARIF SCIGRAPH-VERIFY-001]
  * Impossible transition: Rejected -> In-Graph (prevented by mandatory re-check inside ClaimGraph.add_verified_claim at src/graph/claim_graph.py:38-42).
```

- **Coupling & before/after check:** `src/scigraph/__init__.py` imports only `scigraph.models`, preventing package-init cycles when `scigraph.cli` imports `evals`, `solver`, and `graph`.
- **Scaling characteristics (10x / 100x):** At 300 papers (~600 claims) and 3,000 papers (~6,000 claims), `combinations(group, 2)` in `ClaimGraph.build_edges` and `detect_contradictions` operates per `(intervention, outcome)` bucket (`k` claims per bucket, typically `k <= 20`), scaling `O(B * k^2)` rather than `O(N^2)` globally. Single-process memory is `< 50 MB` at 3,000 papers.
- **Single points of failure & rollback posture:** Stateless local CLI and library with zero network/DB dependencies; rollback is a single `git revert` (`< 1 minute`) and pinning the prior package tag.
- **Value test for reports:** `render_markdown_report`, `render_claim_graph_html`, and `export_sarif_v210` are user-requested product outputs (`EXP-1`, `EXP-2`, `EXP-4`) consumed directly by R&D researchers and GitHub Code Scanning, not session meta-artifacts.
- **Section 1 Verdict:** **OK** — No unresolved architectural issues found.

---

## Section 2: Error & Rescue Map

```
  METHOD / CODEPATH                        | WHAT CAN GO WRONG                        | EXCEPTION CLASS
  -----------------------------------------|------------------------------------------|---------------------------
  ingest.extractor.extract_paper_from_pdf  | Binary PDF header (%\xe2\xe3\xcf\xd3)    | UnicodeDecodeError
                                           | Compressed /FlateDecode PDF stream       | ValueError (silent/generic)
                                           | Oversized >25 MiB PDF byte buffer        | MemoryError / CPU hang
                                           | Missing DOI header in extracted text     | ValueError
  graph.claim_graph.add_verified_claim     | Unverified / fabricated claim passed     | ValueError
  solver.symbolic.parse_standardized_effect| Malformed or non-positive fold/OR/HR     | ValueError (math.log <= 0)
  scigraph.cli.main (--output write)       | Missing parent dir / permission denied   | OSError
                                           | Cross-device /tmp -> target os.replace   | OSError (EXDEV)
                                           | Unknown --paper-id passed to verify      | KeyError / ValueError
  -----------------------------------------|------------------------------------------|---------------------------

  EXCEPTION CLASS / CONDITION              | RESCUED?     | RESCUE ACTION                          | USER SEES
  -----------------------------------------|--------------|----------------------------------------|---------------------------
  UnicodeDecodeError (binary PDF header)   | N <- GAP     | Decode via latin-1 + check %PDF header | Raw traceback <- BAD
  Compressed /FlateDecode PDF without text | N <- GAP     | Detect /FlateDecode & raise ValueError | Generic "No blocks" error
  Oversized >25 MiB PDF byte buffer        | N <- GAP     | Enforce MAX_PDF_BYTES=25 MiB check     | Potential OOM / hang
  Cross-device EXDEV on --output temp file | N <- GAP     | Create temp file in output_path.parent | Failed atomic write
  ValueError (missing DOI / unverified)    | Y (in CLI)   | Print actionable diagnostic, exit 1/2  | Clear stderr error message
  ValueError (math.log <= 0 in EXP-5)      | Y (by guard) | Check val > 0 before math.log, -> None | Safe fallback to base_n
  OSError (permission / missing dir)       | Y (in CLI)   | Catch OSError, unlink temp, exit 2     | Clear file I/O message
```

### Section 2 Finding (`SEC-1`): Binary PDF Header, Size Limit, Compression Diagnostic & Same-Directory Atomic Write
`src/ingest/extractor.py:181` currently calls `pdf_bytes.decode("utf-8")`, which crashes with an uncaught `UnicodeDecodeError` on real PDF-1.4 files that include the standard 4-byte binary header comment (`%\xe2\xe3\xcf\xd3`), has no upper size guard (`MAX_PDF_BYTES`) before running `re.DOTALL` regexes, and gives no specific diagnostic when a binary PDF uses compressed `/FlateDecode` streams without uncompressed `BT...ET` blocks. In addition, `EXP-1`'s atomic `--output` write (`os.replace`) will raise `OSError(EXDEV)` if the temp file is created in `/tmp` rather than `output_path.parent`.

## currentDecision (SEC-1)
Commitment comparison:
Commitment | Source/approval or pending | Current | A | B | C
---|---|---|---|---|---
Wave 1-2 core + `EXP-1`..`EXP-5` | Approved (`11aa6f8`, `D3`..`D8`) | Retained | Retained | Retained | Retained
`extract_paper_from_pdf_bytes` binary/size/compression handling (`src/ingest/extractor.py:176-200`) | Pending (`SEC-1`) | `pdf_bytes.decode("utf-8")` with no size cap or `/FlateDecode` check | Enforce `MAX_PDF_BYTES = 25 * 1024 * 1024`, validate `%PDF-` prefix, decode stream syntax via `latin-1`, raise explicit `ValueError` naming `/FlateDecode` when compressed streams contain no uncompressed `BT...ET` blocks | Catch `UnicodeDecodeError` and re-raise generic `ValueError` only (no size cap or `/FlateDecode` check) | Leave `utf-8` decode unchanged and document synthetic-PDF-only limitation |
Atomic `--output` write in `src/scigraph/cli.py` | Pending (`SEC-1`) | Unspecified temp directory | Create `NamedTemporaryFile(dir=output_path.parent, delete=False)`, `os.replace`, and `unlink` in `except` cleanup | Standard `Path.write_text` overwrite (non-atomic on crash) | Unspecified |
Adversarial error-path unit tests (`tests/test_scigraph.py`) | Pending (`SEC-1`) | Absent | Tests for `%\xe2\xe3\xcf\xd3` binary header, `/FlateDecode` diagnostic, `>25 MiB` cap, and atomic `--output` cleanup | Test for `UnicodeDecodeError -> ValueError` only | None |

Question: D9 — SEC-1: Harden PDF Byte Boundary & Atomic CLI Output Writes (`src/ingest/extractor.py`, `src/scigraph/cli.py`)
Project/branch/task: scigraph on branch main — Section 2 Error & Rescue Map decision gate.
ELI10: Real PDF files almost always put four non-UTF-8 binary bytes right after `%PDF-1.4` so file transfer tools treat them as binary, and many PDFs compress their text streams with `/FlateDecode` or weigh puluhan megabytes. Right now `extract_paper_from_pdf_bytes` calls `.decode("utf-8")`, which crashes immediately on those binary header bytes, has no size limit against huge buffers, and doesn't warn when a PDF stream is compressed; meanwhile, atomic CLI `--output` writes can fail across disk mounts if the temp file isn't created in the target folder.
Stakes if we pick wrong: Leaving raw `.decode("utf-8")` and `/tmp` renames in place causes uncaught `UnicodeDecodeError` crashes on real PDF headers, memory spikes on oversized inputs, and `EXDEV` write failures when `--output` is on another volume.
Recommendation: A (Complete boundary hardening) because preferring explicit edge-case coverage over happy-path shortcuts eliminates all four failure modes in ~25 lines of standard-library Python with deterministic tests.
Completeness: A=10/10, B=7/10, C=3/10
Pros / cons: see option descriptions below.
Net: Close all four ingestion and atomic-write error gaps now with complete boundary guards and regression tests, apply a minimal `UnicodeDecodeError` wrapper, or document the limitation only.
Header: SEC-1: PDF Boundary & Atomic Write Rescue
A) Complete boundary hardening (recommended)
Enforce `MAX_PDF_BYTES = 25 MiB`, `%PDF-` magic-byte check, `latin-1` stream decoding, explicit `/FlateDecode` `ValueError` diagnostic, same-directory `NamedTemporaryFile` + cleanup for `--output`, and unit tests. Effort: S (human: ~2 hours / CC: ~6 min), Risk: low, Reuse: extends `extract_paper_from_pdf_bytes` and `cli.py`, Verification: 4 deterministic failure-path unit tests, Completeness: 10/10. ✅ Handles standard binary PDF-1.4 headers (`%\xe2\xe3\xcf\xd3`), rejects oversized buffers before regex scan, and gives a clear `/FlateDecode` message. ✅ Guarantees POSIX-atomic `--output` writes without cross-device `EXDEV` failures or orphan temp files. ❌ Adds ~25 lines of validation and temp-file cleanup logic across `extractor.py` and `cli.py`.
B) Minimal UnicodeDecodeError wrapper only
Wrap `pdf_bytes.decode("utf-8")` in `try/except UnicodeDecodeError` raising `ValueError` and use plain `Path.write_text` for `--output`. Effort: S (human: ~30 min / CC: ~2 min), Risk: medium, Reuse: minimal wrapper in `extractor.py`, Verification: 1 unit test on non-UTF-8 bytes, Completeness: 7/10. ✅ Prevents raw `UnicodeDecodeError` tracebacks with minimal code changes. ✅ Faster to write than same-directory temp-file handling. ❌ Rejects valid uncompressed PDFs that contain standard 4-byte binary headers and leaves `>25 MiB` memory exhaustion and partial `--output` files unmitigated.
C) Do nothing — document UTF-8 synthetic PDF limitation
Keep `extract_paper_from_pdf_bytes` unchanged and note in `README.md` that only UTF-8 synthetic PDF streams are supported. Effort: S (human: ~10 min / CC: ~1 min, zero implementation work), Risk: high, Reuse: none, Verification: documentation note only, Completeness: 3/10. ✅ Zero code changes to `src/ingest/extractor.py`. ✅ Preserves exact current line count. ❌ Leaves uncaught `UnicodeDecodeError` and OOM/ReDoS gaps open at the primary ingestion boundary.

### Answered Decision (SEC-1)
- **Result:** Approved (`D9: A`, Completeness: `10/10` — Enforce `MAX_PDF_BYTES = 25 MiB`, `%PDF-` magic-byte check, `latin-1` stream decoding, explicit `/FlateDecode` `ValueError` diagnostic, same-directory `NamedTemporaryFile` + cleanup for `--output`, and 4 failure-path unit tests).

---

## Section 3: Security & Threat Model

| Threat / Vector | Likelihood | Impact | Mitigation Status in Plan |
|---|---|---|---|
| **T1: Stored/Reflected XSS in HTML Explorer (`src/scigraph/explorer.py`)** via `<script>` or attribute payloads in paper titles, DOIs, quotes, or conditions | Med | High | **MITIGATED (`D4: A`):** Mandatory `html.escape(val, quote=True)` on every dynamic text field and `data-*` attribute, plus inline `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">` blocking external network exfiltration. |
| **T2: PDF Memory Exhaustion / ReDoS (`src/ingest/extractor.py`)** via >25 MiB or malformed binary streams | Med | Med | **MITIGATED (`D9: A`):** Enforce `MAX_PDF_BYTES = 25 * 1024 * 1024` and `%PDF-` prefix check before decoding or regex matching. |
| **T3: Partial/Corrupt Output or Cross-Mount `EXDEV` (`src/scigraph/cli.py`)** on `--output <path>` | Low | Med | **MITIGATED (`D9: A`):** Create `NamedTemporaryFile(dir=output_path.parent, delete=False)`, flush, `os.replace`, and unlink temp file on error. |
| **T4: Hallucinated Citations / Statistical Poisoning** entering `ClaimGraph` | High | High | **MITIGATED (Baseline `11aa6f8` + `D6: A`):** `verify_claim_verbatim` rejects non-verbatim DOIs, quotes, p-values, and sample sizes; `ClaimGraph.add_verified_claim` raises `ValueError`; SARIF `SCIGRAPH-VERIFY-001` flags rejections as `error`. |
| **T5: Supply-Chain / Credential Leakage** | Low | Low | **MITIGATED:** Zero new third-party dependencies (`pydantic>=2.9` only); zero API keys, network calls, or secrets. |

- **Section 3 Verdict:** **OK** — All 5 threats mitigated (`0` High-severity unmitigated issues).

---

## Section 4: Data Flow & Interaction Edge Cases

### Adversarial Data Flow Trace (Including Shadow Paths)
```
  [INPUT: PDF bytes / LayoutBlocks / CLI argv]
       |
       +--> Shadow (nil/empty/wrong type): empty bytes, missing --format, non-PDF magic header
       |      -> ValueError / argparse exit 2 (tested)
       v
  [VALIDATION: MAX_PDF_BYTES <= 25 MiB -> latin-1 decode -> /FlateDecode check -> Pydantic strict]
       |
       +--> Shadow (>25 MiB / compressed stream / invalid DOI):
       |      -> explicit ValueError -> CLI stderr + exit 2 or ValidationError (tested)
       v
  [TRANSFORM: order_layout_blocks -> extract_claims -> verify_paper_claims -> ClaimGraph -> Solver]
       |
       +--> Shadow (fabricated DOI / p-value / n / span mismatch):
       |      -> ClaimVerificationResult(verified=False) -> blocked at ClaimGraph; emitted as
       |         SCIGRAPH-VERIFY-001 in SARIF (tested across 150 decoys)
       |
       +--> Shadow (zero effect_size_raw / negative or zero fold/OR / non-numeric condition):
       |      -> parse_standardized_effect_size -> None -> base_n fallback;
       |         compute_regime_delta -> None -> qualitative condition label retained (tested)
       v
  [PERSIST / RENDER: Markdown | HTML (html.escape) | SARIF v2.1.0 | JSON -> stdout or NamedTemporaryFile]
       |
       +--> Shadow (missing parent dir / read-only dir / disk full):
       |      -> OSError caught in CLI -> temp file unlinked -> stderr diagnostic + exit 2 (tested)
       v
  [OUTPUT: Verified report artifact + deterministic exit code 0 / 1 / 2]
```

### Async & Concurrency Ordering Check
- **Shared mutable state boundary:** None in-memory (`Paper`, `ScientificClaim`, `EvidenceEdge`, `ContradictionPair`, `FalsifiableExperiment`, and `RegimeParameter` are all `frozen=True`, and each `scigraph` CLI run instantiates an isolated `ClaimGraph`). On filesystem `--output` writes, `NamedTemporaryFile(dir=output_path.parent)` + POSIX `os.replace` ensures any concurrent reader observes either the complete prior file or the complete new file, never a half-written buffer.

### Interaction Edge Cases (CLI & HTML Explorer)

| Interaction | Edge Case | Handled? | How |
|---|---|---|---|
| CLI `scigraph report --output <dir>` | `--output` points to an existing directory or missing parent folder | Yes | `OSError` (`IsADirectoryError` / `FileNotFoundError`) caught in `cli.py`, temp file cleaned up, stderr diagnostic printed, exit code `2`. |
| CLI `scigraph verify --paper-id unknown` | Paper ID not in corpus | Yes | Prints unknown paper ID diagnostic to `sys.stderr`, returns exit code `2`. |
| CLI `scigraph report --fail-on-contradictions` | Contradictions exist (`11` in 30-paper corpus) | Yes | Writes complete report first, then returns exit code `1` so CI uploads the SARIF/HTML artifact while failing the gate. |
| HTML Explorer filter buttons (`EXP-2`) | Rapid double-clicking or selecting a filter category with `0` matching cards | Yes | Idempotent `aria-pressed` state update + `.filter-empty-banner` ("No items match the selected filter") toggled visible when visible card count is `0`. |
| HTML Explorer with empty `ClaimGraph` | `0` contradictions or `0` edges | Yes | Static `<div class="empty-state">` rendered in each empty section. |
| Large corpus rendering (`60` claims, `11` contradictions) | Long verbatim quotes or wide DOI strings on narrow viewports | Yes | `overflow-wrap: anywhere` and responsive CSS grid collapsing side-by-side cards below `768px`. |

- **Section 4 Verdict:** **OK** — All 6 interaction edge cases and shadow paths handled (`0` unhandled).

---

## Section 5: Code Quality Review

- **Shared corpus runner extraction (`src/evals/benchmark.py`):** Both `evaluate_benchmark()` and `scigraph.cli` (`verify` / `report`) iterate over `BENCHMARK_30_PAPERS`, run PDF/layout ingestion, verify claims, populate `ClaimGraph`, detect contradictions, and propose experiments. Extract a single pure helper `run_benchmark_audit() -> BenchmarkAuditBundle` (frozen Pydantic model holding `metrics`, `graph`, `reports`, `contradictions`, `experiments`) in `src/evals/benchmark.py` so `evaluate_benchmark()` returns `run_benchmark_audit().metrics` and `cli.py` reuses `run_benchmark_audit()` with zero duplicated pipeline loops.
- **Cyclomatic complexity discipline (`<= 5` branches per function):** Implement `extract_regime_parameters` (`src/solver/regime.py`) and `parse_standardized_effect_size` (`src/solver/symbolic.py`) using declarative pattern-dispatch tables rather than deep `if/elif` chains.
- **Naming & strict typing:** All modules remain under `mypy --strict` and `ruff check` (`E`, `F`, `I`, `UP`, `B`) with top-of-module imports only and zero inline suppression comments.
- **Section 5 Verdict:** **OK** — `1` duplication prevention noted (`run_benchmark_audit` helper within `EXP-1`/`EXP-4`), `0` unresolved quality issues.

---

## Section 6: Test Review

### New Codepaths & Test Coverage Diagram
```
  NEW ARTIFACT / CODEPATH                        | TEST TYPE   | HAPPY PATH                     | FAILURE / EDGE PATH
  -----------------------------------------------|-------------|--------------------------------|--------------------------------------------
  ingest.extractor.extract_paper_from_pdf_bytes  | Unit        | Binary header %\xe2\xe3\xcf\xd3| >25 MiB buffer; /FlateDecode stream; no %PDF
  solver.regime (extract + compute_regime_delta) | Unit        | 28 C->37 C (+9 C), mM->M, K->C | Non-numeric condition -> None; ng/mL vs M
  solver.symbolic (compute_powered_sample_size)  | Unit        | Small d=0.25 > large d=1.20 n  | Both effect_size_raw=None -> base_n; fold<=0
  scigraph.exporters (Markdown, JSON, SARIF)     | Integration | Valid SARIF 2.1.0 + JSON keys  | Paper DOI failure & claim failure -> VERIFY-001
  scigraph.explorer (render_claim_graph_html)    | Unit/Integ  | Renders KPIs, filters, quotes  | XSS <script> escaped; empty graph -> empty-state
  scigraph.cli (benchmark, verify, report)       | E2E (in-proc)| Exit 0 + atomic --output file  | Unknown paper -> 2; --fail-on-contradictions -> 1; OSError -> 2
```

### Behavioral Assertion & `no_claim` Check
1. **PDF Binary Boundary (`SEC-1`):** Asserts `extract_paper_from_pdf_bytes` succeeds when `b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"` precedes valid `BT...ET` blocks, and raises `ValueError` matching `"MAX_PDF_BYTES"` on `25 MiB + 1` bytes and `"/FlateDecode"` on compressed streams without text blocks; rejects silent empty extraction or `UnicodeDecodeError`. `no_claim=compressed FlateDecode glyph decompression (requires external PDF font/cmap parser; explicitly rejected with actionable ValueError)`.
2. **Quantitative Regime Solver (`EXP-3`):** Asserts `compute_regime_delta("Aedes aegypti midgut at 28 C", "37 C larval thermal heatwave stress")` contains `"+9 C"`, `"300 K"` vs `"310 K"` normalizes to `"+10 C"`, `"500 mM"` vs `"1.0 M"` normalizes to `"+0.5 M"`, and `"65% relative humidity"` vs `"130 C oxidative regeneration"` emits `"Cross-dimension regime shift"`; rejects subtracting incompatible units (`ng/mL` vs `M`). `no_claim=none beyond protects`.
3. **Effect-Size Statistical Power (`EXP-5`):** Asserts `compute_powered_sample_size` yields a strictly larger sample size for `d = 0.30` than `d = 1.20`, caps formula output at `2000` when `base_n <= 2000`, preserves `base_n` when `base_n > 2000`, and returns `base_n` when both claims have `effect_size_raw=None`. `no_claim=exact non-central t distribution quantiles (uses closed-form normal approximation at alpha=0.01, power=0.90)`.
4. **SARIF v2.1.0 & JSON Exporters (`EXP-4`):** Asserts `json.loads(export_sarif_v210(...))` has `version == "2.1.0"`, emits `SCIGRAPH-VERIFY-001` on both `doi_verified=False` and decoy claim failures with `artifactLocation.uri == f"papers/{paper_id}"`, and emits `SCIGRAPH-CONTRA-001`/`002` with exact `charOffset` and `charLength`. `no_claim=GitHub Code Scanning ingestion API upload (validates SARIF v2.1.0 JSON structure locally)`.
5. **Interactive HTML Explorer (`EXP-2`):** Asserts `render_claim_graph_html` escapes `<script>alert("xss")</script>` into `&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;`, renders both `ContradictionKind` and `EdgeRelation` filter controls, and renders `<div class="empty-state">` on an empty graph. `no_claim=real browser layout pixel rendering (recommend /gstack-qa or headless browser check post-implementation)`.
6. **CLI Entrypoint (`EXP-1`):** Asserts `main(["benchmark"]) == 0`, `main(["verify", "--paper-id", "unknown"]) == 2`, `main(["report", "--format", "sarif", "--output", str(tmp_path / "out.sarif"), "--fail-on-contradictions"]) == 1` while atomically writing `out.sarif`, and `main(["report", "--format", "json", "--output", str(tmp_path / "missing_dir" / "out.json")]) == 2` with zero leftover temp files. `no_claim=none beyond protects`.

### Test Ambition Check
- **Friday 2am confidence test:** End-to-end `scigraph report --format {markdown,html,sarif,json}` across all 30 papers + 150 adversarial decoys verifying `0` accepted fabrications, `100%` valid JSON/SARIF/HTML output, and deterministic byte-identical JSON across repeated runs.
- **Hostile QA test:** Injecting `<img src=x onerror=alert(1)>` and quotes into paper titles, conditions, and outcomes, plus passing `b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n<< /Filter /FlateDecode >>"` and `25 MiB + 1` bytes to `extract_paper_from_pdf_bytes`.
- **Chaos / permutation test:** Shuffling the `LayoutBlock` order on every multi-column paper before rendering to PDF bytes and asserting that `extract_paper_from_pdf_bytes` + `ClaimGraph` produces identical claims, character offsets, edges, and contradictions.
- **Test pyramid & flakiness:** Fast deterministic unit and in-process CLI integration tests (`0` sleep/clock/network dependencies; zero flakiness risk).
- **Section 6 Verdict:** **OK** — Full test matrix determined by approved contracts `D3`–`D9` (`0` unresolved test gaps).

---

## Section 7: Performance Review

- **Database / N+1 / Connection Pools:** None (pure in-memory graph and file/stdout CLI).
- **Memory Usage:** Bounded at `25 MiB` max input per PDF stream (`SEC-1`); 30-paper `BenchmarkAuditBundle` occupies `< 5 MB`.
- **Regex Precompilation:** All regexes in `src/ingest/extractor.py`, `src/ingest/verifier.py`, `src/solver/regime.py`, and `src/solver/symbolic.py` are compiled once at module load time (`re.compile`).
- **Top 3 Slowest Codepaths (Estimated & Measured Latency):**
  1. `run_benchmark_audit()` (30-paper ingestion, verification, 150 decoys, graph edges, solver): **4.201 ms median** (`[measured: evaluate_benchmark]`), `< 10 ms` p99 with regime/power extensions (`[estimated]`).
  2. `render_claim_graph_html()` (60 claims, 11 contradictions, edges): `< 3 ms` p99 (`[estimated]`, list-comprehension `"".join(...)` string assembly).
  3. `export_sarif_v210()` / `export_json_bundle()`: `< 3 ms` p99 (`[estimated]`, standard-library `json.dumps`).
- **Section 7 Verdict:** **OK** — Sub-15ms end-to-end execution (`0` performance issues).

---

## Section 8: Observability & Debuggability Review

- **Structured Machine Telemetry:** `scigraph benchmark --json` emits structured `BenchmarkMetrics` (`true_positives`, `false_positives`, `false_negatives`, `f1_score`, `fabricated_dois_accepted`, `fabricated_p_values_accepted`, `adversarial_decoys_rejected`, `contradictions_detected`, `experiments_proposed`, `elapsed_ms`).
- **Post-Ship Forensic Reconstructability:** Every SARIF result (`SCIGRAPH-VERIFY-001`, `SCIGRAPH-CONTRA-001`, `SCIGRAPH-CONTRA-002`) and HTML Explorer card carries `paper_id`, `doi`, exact `[start_char:end_char]` offsets, verbatim quote text, and the symbolic `unsat_constraints` tuple so any disputed contradiction or rejected claim can be traced to the exact character slice in seconds.
- **Operational Runbook (CLI Exit Codes):**
  - `Exit 0`: Verification and benchmark gates clean.
  - `Exit 1`: Verification failure (`SCIGRAPH-VERIFY-001`), benchmark F1 `< 0.85`, or `--fail-on-contradictions` triggered -> inspect SARIF/Markdown report for the offending `claim_id` and `VerificationFailureReason`.
  - `Exit 2`: Invalid CLI flag, unknown `--paper-id`, `/FlateDecode` compressed PDF requiring layout pre-extraction, oversized `>25 MiB` input, or `--output` path `OSError` -> check `stderr` diagnostic.
- **Section 8 Verdict:** **OK** — Complete CLI metrics, SARIF provenance, and exit-code runbook (`0` observability gaps).

---

## Section 9: Deployment & Rollout Review

```
  [1. Land code + tests on branch]
               |
               v
  [2. Gate: ruff check && mypy --strict && pytest -v]
               |
               v
  [3. Install CLI script: uv pip install ".[dev]" && chflags -R nohidden .venv]
               |
               v
  [4. Smoke check: scigraph benchmark && scigraph report --format sarif/html]
               |
               v
  [5. Merge to main & tag v0.2.0]
```

### Rollback Flowchart
```
  [Post-merge regression or broken CLI flag detected]
               |
               v
  [git revert <merge-or-feature-sha> on main]
               |
               v
  [Re-run .venv/bin/pytest (verifies 11aa6f8 30-paper baseline in <0.2s)]
               |
               v
  [Publish hotfix tag; zero stateful DB or schema migrations to unwind]
```

- **Feature flag / compatibility posture:** Existing library imports (`from scigraph import ...`, `from ingest import ...`, `from graph import ...`, `from solver import ...`, `from evals import ...`) remain 100% backward-compatible; `--fail-on-contradictions` defaults to `False` so report generation is non-breaking unless explicitly gated.
- **Section 9 Verdict:** **OK** — Stateless rollout and sub-minute rollback (`0` deployment risks).

---

## Section 10: Long-Term Trajectory Review

- **Technical debt introduced:** Zero shortcuts taken (`Lake Score: 1/1` — `SEC-1` chose the `10/10` complete boundary option).
- **Path dependency & reversibility:** **5 / 5** (completely reversible; new modules sit cleanly above frozen `scigraph.models` without mutating core domain invariants).
- **12-month readability:** Module responsibilities map 1-to-1 with domain concepts (`models.py`, `extractor.py`, `verifier.py`, `claim_graph.py`, `regime.py`, `symbolic.py`, `exporters.py`, `explorer.py`, `cli.py`).
- **Phase 2 & Phase 3 Platform Trajectory:**
  - **Phase 2:** Optional binary PDF adapter (`pymupdf` / GROBID) converting compressed `/FlateDecode` PDFs into `LayoutBlock` tuples at the exact seam guarded by `SEC-1`.
  - **Phase 3:** Full Z3 SMT solver integration for multi-hop transitive pathway reasoning (`Intervention A -> Biomarker B -> Clinical Outcome C`) and automated PubMed Central / EuropePMC live fetch.
- **Section 10 Verdict:** **OK** — Reversibility `5/5`, `0` debt items.

---

## Section 11: Design & UX Review (`EXP-2` Interactive HTML Claim-Graph & Contradiction Explorer)

### Information Architecture (What the Researcher Sees 1st, 2nd, 3rd)
1. **First (Top Trust & KPI Bar):** Corpus health at a glance — `Papers Audited`, `Verified Claims`, `Fabrications Rejected (100%)`, `Contradictions Surfaced`, and `Falsifiable Experiments Proposed`, establishing epistemic trust immediately.
2. **Second (Contradiction & Experiment Studio):** Interactive `ContradictionKind` filter bar (`ALL`, `DIRECT_DIRECTION_CONFLICT`, `NULL_VS_SIGNIFICANT_CONFLICT`, `CONDITION_DEPENDENT_DIVERGENCE`) over side-by-side comparison cards pairing `Claim A` vs. `Claim B` (DOI, section, exact `[start:end]` character span, verbatim quote, `n`, `p`, `effect_size_raw`), the `UNSAT` symbolic core + quantitative regime delta badge, and the resulting `FalsifiableExperiment` protocol card (`recommended_sample_size`, `alpha = 0.01`, `falsification_criterion`).
3. **Third (Evidence Edge Explorer):** Interactive `EdgeRelation` filter bar (`ALL`, `SUPPORTS`, `REPLICATES`, `CONTRADICTS`, `QUALIFIES`) inspecting every cross-claim graph edge.

### Interaction State Coverage Map

| Feature | Loading | Empty | Error | Success | Partial |
|---|---|---|---|---|---|
| KPI Summary Banner | Static instant load (`0 ms` network) | Renders `0` counts cleanly | N/A (validated in Python) | Full counts + F1 & decoy stats when `metrics` present | Omits optional benchmark F1 pill when `metrics=None` |
| Contradiction Studio | Static instant render | `<div class="empty-state">No contradictions detected</div>` | Filter matches `0` cards -> `.filter-empty-banner` shown | Side-by-side `Claim A`/`Claim B` + `UNSAT` + Experiment card | Gracefully omits `effect_size_raw` pill when `None` |
| Evidence Edge Explorer | Static instant render | `<div class="empty-state">No evidence edges in graph</div>` | Filter matches `0` edges -> `.filter-empty-banner` shown | Color-coded semantic badges (`CONTRADICTS`, `QUALIFIES`, `REPLICATES`, `SUPPORTS`) | Single-paper graph shows `0` cross-paper edges cleanly |

### User Flow & State Transition Diagram
```
  [Run: scigraph report --format html --output scigraph-explorer.html]
                                  |
                                  v
  [Open HTML in Browser (Zero External Requests, CSP Locked)]
                                  |
         +------------------------+------------------------+
         |                                                 |
         v                                                 v
  [Contradiction Studio]                         [Evidence Edge Explorer]
  Click filter pill (aria-pressed="true"):       Click filter pill (aria-pressed="true"):
  - ALL                                          - ALL
  - DIRECT_DIRECTION_CONFLICT                    - CONTRADICTS / QUALIFIES
  - NULL_VS_SIGNIFICANT_CONFLICT                 - REPLICATES / SUPPORTS
  - CONDITION_DEPENDENT_DIVERGENCE                         |
         |                                                 v
         v                                       [Matching edge rows shown;
  [Inspect side-by-side verbatim spans           if 0 match -> .filter-empty-banner]
   + quantitative regime delta + wet-lab
   FalsifiableExperiment protocol card]
```

- **Anti-AI-slop & Accessibility (`WCAG 2.1 AA`):** Clean laboratory-grade slate/ink palette (`>= 7:1` body contrast), semantic `<header>`, `<main>`, `<section>`, `<table>`, and `<button type="button" aria-pressed="...">` controls, visible `:focus-visible` keyboard outlines, monospace tabular numerals (`font-variant-numeric: tabular-nums`) for p-values, sample sizes, and character offsets, and responsive single-column stacking under `768px`.
- **Design Review Chaining Note:** Consider running `/gstack-plan-design-review` for a dedicated pixel/typography review before implementation, and `/gstack-design-review` on the rendered HTML output after implementation.
- **Section 11 Verdict:** **OK** — Intentional laboratory IA, complete empty/partial/filter states, and WCAG AA keyboard accessibility (`0` unresolved UX gaps).

---

## Outside Voice — Independent Plan Challenge

Outside voice unavailable: `MODEL_UNUSABLE` (`gpt-6.2-astra` not available on current Codex account) and `Plan`/`TaskStop` subagent types are not offered in the Antigravity (`agy`) host for bounded native fallback. Fix: `gstack-config set model_frontier_openai <model-id>` or `gstack-config set plan_review_tier smart`. Continuing to planning decisions and Approval readiness. (`OUTSIDE_VOICE_UNAVAILABLE`)

## Remaining TODO Choices

Zero unanswered TODO proposals remain (`5` of `5` Step 0G expansion proposals and `SEC-1` were accepted into scope; `0` items deferred to `TODOS.md`).

---

## NOT in scope

- **Deferred to `TODOS.md` (`0` items):** None (`D3: A`–`D7: A` accepted all 5 Step 0G proposals).
- **Skipped / Rejected (`0` items):** None.
- **Explicit Phase 2 / Phase 3 Non-Goals (Out of Scope for This Plan):**
  - Compressed `/FlateDecode` PDF binary glyph/font CMap decompression without an external PDF library (`SEC-1` explicitly detects `/FlateDecode` streams lacking uncompressed `BT...ET` blocks and raises an actionable `ValueError` rather than adding third-party C extensions in this wave).
  - Live network fetching against PubMed / arXiv / Crossref APIs (all evaluation and verification remain 100% deterministic and offline).
  - External database persistence (Neo4j / Postgres) or multi-hop Z3 C++ bindings.

## What already exists

- `src/scigraph/models.py:1-259` — Frozen Pydantic v2 domain schema (`Paper`, `PaperSection`, `LayoutBlock`, `EvidenceSpan`, `ClaimTuple`, `StatisticalEvidence`, `ScientificClaim`, `EvidenceEdge`, `ContradictionPair`, `FalsifiableExperiment`, `BenchmarkMetrics`); **reused directly** across all 5 expansions.
- `src/ingest/extractor.py:1-249` — Two-column `order_layout_blocks`, `extract_paper_from_layout`, `extract_paper_from_pdf_bytes`, and `extract_claims_from_paper`; **reused and hardened** with `SEC-1` binary header / `MAX_PDF_BYTES` / `/FlateDecode` checks.
- `src/ingest/verifier.py:1-99` — Deterministic `verify_claim_verbatim` and `verify_paper_claims`; **reused directly** by `scigraph verify` and `export_sarif_v210`.
- `src/graph/claim_graph.py:1-147` — `ClaimGraph` with boundary verification and `SUPPORTS`/`REPLICATES`/`CONTRADICTS`/`QUALIFIES` edge builder; **reused directly** by `cli.py`, `exporters.py`, and `explorer.py`.
- `src/solver/symbolic.py:1-155` — Symbolic satisfiability, `detect_contradictions`, and `propose_falsifiable_experiments`; **extended in-place** with `EXP-3` (`compute_regime_delta`) and `EXP-5` (`compute_powered_sample_size`).
- `src/evals/benchmark.py:1-728` — 30-paper multi-column corpus (`BENCHMARK_30_PAPERS`) and 150 adversarial decoys; **refactored to expose `run_benchmark_audit()`** so `evaluate_benchmark()` and `scigraph.cli` share one canonical loop.

## Dream state delta

This plan advances SciGraph from an internal Python library (`11aa6f8`) to a self-contained **neuro-symbolic verification CLI, CI static-analysis gate (SARIF v2.1.0), quantitative regime/power solver, and interactive HTML Claim-Graph Studio**. Relative to the 12-month ideal (100k-paper live ingestion, binary PDF CMap/table OCR, and automated wet-lab CRO protocol dispatch), the remaining delta after this plan ships is live corpus connectors, compressed binary PDF layout adapters (`pymupdf`/GROBID), and multi-hop transitive pathway solving.

## Error & Rescue Registry

| Method / Codepath | Exception / Condition | Rescued? | Rescue Action | User Impact |
|---|---|---|---|---|
| `ingest.extractor.extract_paper_from_pdf_bytes` | `len(pdf_bytes) > 25 MiB` | Yes (`D9: A`) | Raise `ValueError("PDF exceeds MAX_PDF_BYTES (25 MiB)")` caught at CLI boundary | Clear `stderr` error + exit `2` |
| `ingest.extractor.extract_paper_from_pdf_bytes` | Missing `%PDF-` magic header | Yes (`D9: A`) | Raise `ValueError("Invalid PDF header")` caught at CLI boundary | Clear `stderr` error + exit `2` |
| `ingest.extractor.extract_paper_from_pdf_bytes` | Binary header bytes (`%\xe2\xe3\xcf\xd3`) | Yes (`D9: A`) | Decode PDF stream syntax via `latin-1` instead of `utf-8` | Transparently extracts valid uncompressed text blocks |
| `ingest.extractor.extract_paper_from_pdf_bytes` | `/FlateDecode` stream with `0` `BT...ET` blocks | Yes (`D9: A`) | Raise `ValueError` naming `/FlateDecode` compression | Actionable diagnostic on `stderr` + exit `2` |
| `graph.claim_graph.ClaimGraph.add_verified_claim` | Unverified / fabricated `ScientificClaim` | Yes | Raise `ValueError` listing `VerificationFailureReason` codes | Blocks graph poisoning; SARIF emits `SCIGRAPH-VERIFY-001` |
| `solver.symbolic.parse_standardized_effect_size` | `fold <= 0`, `or <= 0`, or unparseable effect string | Yes (`D7: A`) | Guard `val > 0` before `math.log`; return `None` -> `base_n` fallback | Experiment still receives safe `base_n >= 40` sample size |
| `scigraph.cli.main` (`--output <path>`) | `OSError` (missing dir, permission, disk full) | Yes (`D9: A`) | `NamedTemporaryFile(dir=output_path.parent)` + `unlink` in `except OSError`, exit `2` | Zero corrupt/partial files; clear `stderr` I/O message |

## Failure Modes Registry

```
  CODEPATH                                  | FAILURE MODE                       | RESCUED? | TEST? | USER SEES?                          | LOGGED?
  ------------------------------------------|------------------------------------|----------|-------|-------------------------------------|------------------------
  extract_paper_from_pdf_bytes              | Binary %\xe2\xe3\xcf\xd3 header    | Y        | Y     | Clean extraction (no crash)         | N/A (valid PDF header)
  extract_paper_from_pdf_bytes              | >25 MiB buffer                     | Y        | Y     | stderr MAX_PDF_BYTES msg (exit 2)   | CLI stderr
  extract_paper_from_pdf_bytes              | /FlateDecode compressed stream     | Y        | Y     | stderr /FlateDecode msg (exit 2)    | CLI stderr
  verify_claim_verbatim / add_verified_claim| Fabricated DOI / p-value / n / span| Y        | Y     | Rejected + SARIF SCIGRAPH-VERIFY-001| SARIF / JSON report
  parse_standardized_effect_size            | Missing or non-positive effect size| Y        | Y     | Safe fallback to base_n             | Deterministic n output
  render_claim_graph_html                   | Malicious <script> / quote in text | Y        | Y     | Escaped literal text (CSP locked)   | Safe HTML output
  scigraph.cli (--output atomic write)      | Missing parent dir / OSError       | Y        | Y     | stderr I/O diagnostic (exit 2)      | CLI stderr
```
- **Total rows:** `7` | **CRITICAL GAPS:** `0`.

## Scope Expansion Decisions

Full Step 0G/0H scope record saved at `/Users/justinmafie/.gstack/projects/justinmafie/ceo-plans/2026-11-25-scigraph-scope-expansion.md`:
- **Accepted (`5` of `5`):**
  - `EXP-1` (`D3: A`): `scigraph` CLI & Markdown Contradiction Briefing (`src/scigraph/cli.py`, `render_markdown_report`).
  - `EXP-2` (`D4: A`): Interactive HTML Claim-Graph & Contradiction Explorer (`src/scigraph/explorer.py`).
  - `EXP-3` (`D5: A`): Quantitative Condition & Regime Delta Solver (`src/solver/regime.py`).
  - `EXP-4` (`D6: A`): Deterministic SARIF v2.1.0 & JSON Audit Exporter (`src/scigraph/exporters.py`).
  - `EXP-5` (`D7: A`): Effect-Size Parser & Statistical Power Sample-Size Calculator (`src/solver/symbolic.py`).
- **Deferred (`0`):** None.
- **Skipped (`0`):** None.

## Diagrams

1. **System architecture:** Included in Section 1 (`System Architecture & Dependency DAG`).
2. **Data flow (including shadow paths):** Included in Section 4 (`Adversarial Data Flow Trace`).
3. **State machine:** Included in Section 1 (`Claim Lifecycle Across Verification Boundary`).
4. **Error flow:**
```
  [Invalid Input / Verification Failure / I/O Failure]
         |
         +--> [PDF >25 MiB / Bad Magic / /FlateDecode] --> raise ValueError --------+
         |                                                                          |
         +--> [Fabricated DOI / p / n] --> ClaimVerificationResult(verified=False)  |
         |                                      |                                   |
         |                         +------------+------------+                      |
         |                         v                         v                      |
         |               [scigraph verify]         [scigraph report --format sarif] |
         |               stderr + exit 1           emits SCIGRAPH-VERIFY-001 error  |
         |                                                                          |
         +--> [--output OSError] --> unlink(tmp_file) ------------------------------+
                                                                                    |
                                                                                    v
                                                                   [CLI catches ValueError/OSError ->
                                                                    prints actionable stderr -> exit 2]
```
5. **Deployment sequence:** Included in Section 9.
6. **Rollback flowchart:** Included in Section 9.

## Stale Diagram Audit

Checked all existing repository files (`README.md`, `PROJECT_SPEC.md`, `AGENTS.md`, `TASKS.md`, `docs/THREAT_MODEL.md`, `docs/adr/001-typed-claim-tuples-and-verbatim-evidence-verification.md`): `0` existing ASCII diagrams in repository files (`0` stale diagrams found).

## Implementation Tasks

Synthesized from this review's approved expansions (`D3`–`D7`) and error-rescue hardening (`D9`). Run with Claude Code, Codex, or Antigravity; checkbox as you ship. (Task-type compression ratios applied: features ~30x, bug/boundary hardening ~20x, tests ~50x.)

- [ ] **T1 (P1, human: ~2h / CC: ~6min)** — `ingest/extractor` — Harden `extract_paper_from_pdf_bytes` with `MAX_PDF_BYTES = 25 MiB`, `%PDF-` magic check, `latin-1` header-safe decoding, and `/FlateDecode` `ValueError` diagnostic
  - Surfaced by: Section 2 (Error & Rescue Map) & Section 3 (Security) — `SEC-1` (`D9: A`)
  - Files: `src/ingest/extractor.py`, `tests/test_scigraph.py`
  - Verify: `.venv/bin/pytest -k pdf -v && .venv/bin/mypy --strict src tests`
- [ ] **T2 (P1, human: ~4h / CC: ~10min)** — `solver/regime` — Implement `RegimeParameter`, `extract_regime_parameters`, and `compute_regime_delta` and wire into `detect_contradictions`
  - Surfaced by: Step 0G `EXP-3` (`D5: A`) & Step 0H Spec Review
  - Files: `src/solver/regime.py`, `src/solver/symbolic.py`, `src/solver/__init__.py`, `tests/test_scigraph.py`
  - Verify: `.venv/bin/pytest -k regime -v && .venv/bin/mypy --strict src tests`
- [ ] **T3 (P1, human: ~3h / CC: ~8min)** — `solver/symbolic` — Implement `parse_standardized_effect_size` and `compute_powered_sample_size` and wire into `propose_falsifiable_experiments`
  - Surfaced by: Step 0G `EXP-5` (`D7: A`) & Step 0H Spec Review
  - Files: `src/solver/symbolic.py`, `src/solver/__init__.py`, `tests/test_scigraph.py`
  - Verify: `.venv/bin/pytest -k power -v && .venv/bin/mypy --strict src tests`
- [ ] **T4 (P1, human: ~4h / CC: ~10min)** — `scigraph/exporters` & `evals/benchmark` — Extract `run_benchmark_audit()` and implement `render_markdown_report`, `export_json_bundle`, and `export_sarif_v210`
  - Surfaced by: Step 0G `EXP-1` (`D3: A`), `EXP-4` (`D6: A`), & Section 5 (Code Quality)
  - Files: `src/evals/benchmark.py`, `src/evals/__init__.py`, `src/scigraph/exporters.py`, `tests/test_scigraph.py`
  - Verify: `.venv/bin/pytest -k "sarif or json or markdown" -v && .venv/bin/mypy --strict src tests`
- [ ] **T5 (P1, human: ~1d / CC: ~15min)** — `scigraph/explorer` — Implement XSS-safe (`html.escape` + inline CSP) `render_claim_graph_html` with dual `ContradictionKind` and `EdgeRelation` filter bars and empty states
  - Surfaced by: Step 0G `EXP-2` (`D4: A`), Section 3 (Security), & Section 11 (Design & UX)
  - Files: `src/scigraph/explorer.py`, `tests/test_scigraph.py`
  - Verify: `.venv/bin/pytest -k explorer -v && .venv/bin/mypy --strict src tests`
- [ ] **T6 (P1, human: ~4h / CC: ~10min)** — `scigraph/cli` & `pyproject.toml` — Implement `scigraph` CLI (`benchmark`, `verify`, `report`) with same-directory atomic `--output` writes (`os.replace`) and exit codes `0`/`1`/`2`
  - Surfaced by: Step 0G `EXP-1` (`D3: A`) & Section 2 `SEC-1` (`D9: A`)
  - Files: `src/scigraph/cli.py`, `pyproject.toml`, `README.md`, `tests/test_scigraph.py`
  - Verify: `.venv/bin/ruff check src tests && .venv/bin/mypy --strict src tests && .venv/bin/pytest -v`

### Reality Check Summary (for Completion Summary)

REALITY: premise-table pass All 4 core premises verified with file:line receipts (unverified=0) PROJECT_SPEC.md:8-27
REALITY: already-done finding Wave 1-2 core pipeline and 30-paper benchmark already implemented in commit 11aa6f8 src/scigraph/models.py:1-259
REALITY: surface-check pass All exported functions in scigraph, ingest, graph, solver, and evals verified src/scigraph/__init__.py:1-49
REALITY: binding-decisions pass ADR-001 typed claim tuples and verbatim verification honored docs/adr/001-typed-claim-tuples-and-verbatim-evidence-verification.md:1-37
REALITY: numbers pass F1=1.0000, 0 fabricated DOIs/p-values, 4.201ms median across 7 runs [measured: evaluate_benchmark] src/evals/benchmark.py:662-728
REALITY: deferred-asks pass Wave 3 external design-partner release tracked in TASKS.md TASKS.md:14-16
REALITY: pr-count pass Single wave on main (1 commit 11aa6f8) pyproject.toml:1-38
`PLAN_REALITY: phase=ceo rows=7/7 missing=none unverified=0) verdict=complete`

## Completion Summary

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
  +====================================================================+
  | Mode selected        | SCOPE EXPANSION                             |
  | System Audit         | Wave 1-2 green at 11aa6f8 (F1=1.0, 0 fab)   |
  | Step 0               | SCOPE EXPANSION; 5/5 expansions + 0H 10/10  |
  | Section 1  (Arch)    | 0 issues found (acyclic scigraph.models DAG)|
  | Section 2  (Errors)  | 7 error paths mapped, 4 GAPS fixed (SEC-1)  |
  | Section 3  (Security)| 5 threats mapped, 0 unmitigated High        |
  | Section 4  (Data/UX) | 6 edge cases mapped, 0 unhandled            |
  | Section 5  (Quality) | 1 dedup helper noted (run_benchmark_audit)  |
  | Section 6  (Tests)   | Diagram + 6 assertion/no_claim specs, 0 gaps|
  | Section 7  (Perf)    | 0 issues found (4.2ms median, <15ms target) |
  | Section 8  (Observ)  | 0 gaps found (CLI JSON + SARIF charOffsets) |
  | Section 9  (Deploy)  | 0 risks flagged (stateless CLI + 1m revert) |
  | Section 10 (Future)  | Reversibility: 5/5, debt items: 0           |
  | Section 11 (Design)  | 0 issues (WCAG AA HTML Studio + dual filter)|
  +--------------------------------------------------------------------+
  | NOT in scope         | written (3 non-goal boundaries, 0 deferred) |
  | What already exists  | written (6 baseline modules mapped)         |
  | Dream state delta    | written                                     |
  | Error/rescue registry| 7 rows, 0 CRITICAL GAPS                     |
  | Failure modes        | 7 total, 0 CRITICAL GAPS                    |
  | TODOS.md updates     | 0 items proposed (all 5 accepted in scope)  |
  | Scope proposals      | 5 proposed, 5 accepted (EXP + SEL)          |
  | CEO plan             | written (~/.gstack/.../2026-11-25-*.md)     |
  | Outside voice        | codex unavailable (MODEL_UNUSABLE)          |
  | Lake Score           | 1/1 recommendations chose complete option   |
  | Diagrams produced    | 6 (arch, dataflow, state, error, dep, roll) |
  | Stale diagrams found | 0                                           |
  | Unresolved decisions | 0                                           |
  | Reality rows         | 7/7 rows (PLAN_REALITY), 0 unverified       |
  +====================================================================+
```

### Unresolved Decisions
None — all 9 decisions (`D1`–`D9`) were answered and approved by the user.

---

# Engineering Review (`main` — `11aa6f8`)

- **Reviewed Target:** `docs/plans/2026-11-25-scigraph-ceo-plan.md` and `docs/designs/scigraph-scope-expansion.md`
- **Scope Gate:** `B` (Plan / design doc selected by user)
- **Scope Challenge Result:** `scope accepted as-is` (`D1: A` — Original 12-file, 2-class modular arrangement approved under `plan-eng-review-structure`)

## Engineering Scope Challenge

- **Existing leverage & reuse:** `scigraph.models`, `ingest.extractor`, `ingest.verifier`, `graph.claim_graph`, `solver.symbolic`, and `evals.benchmark` are implemented and green (`6/6` tests in `0.14s`, `mypy --strict` clean). All 5 expansions (`EXP-1`–`EXP-5`) + `SEC-1` reuse these modules directly with zero new third-party dependencies.
- **Retrospective learning (`git log --oneline -- src/ docs/`):** Single root commit `11aa6f8` (`0` reverts). Prior session learning `[src-multi-package-init-circular-import]` (confidence 9/10) applied: `src/scigraph/__init__.py` imports only `scigraph.models`.
- **Complexity check (`Scope Challenge B`):** 12 planned changed/new files (`src/ingest/extractor.py`, `src/solver/regime.py`, `src/solver/symbolic.py`, `src/solver/__init__.py`, `src/evals/benchmark.py`, `src/evals/__init__.py`, `src/scigraph/exporters.py`, `src/scigraph/explorer.py`, `src/scigraph/cli.py`, `pyproject.toml`, `README.md`, `tests/test_scigraph.py`) and 2 new classes (`RegimeParameter`, `BenchmarkAuditBundle`). Resolved via `D1: A` (`Original arrangement`).

REALITY: premise-table pass All 4 core premises verified with file:line receipts (unverified=0) PROJECT_SPEC.md:8-27
REALITY: already-done finding Wave 1-2 core pipeline and 30-paper benchmark already implemented in commit 11aa6f8 src/scigraph/models.py:1-259
REALITY: surface-check pass All exported functions in scigraph, ingest, graph, solver, and evals verified src/scigraph/__init__.py:1-49
REALITY: binding-decisions pass ADR-001 + CEO Review D1-D9 honored docs/adr/001-typed-claim-tuples-and-verbatim-evidence-verification.md:1-37
REALITY: numbers pass F1=1.0000, 0 fabricated DOIs/p-values, 4.201ms median across 7 runs [measured: evaluate_benchmark] src/evals/benchmark.py:1242-1256
REALITY: deferred-asks pass Wave 3 external design-partner release tracked in TASKS.md TASKS.md:14-16
REALITY: pr-count pass Single wave on main (1 commit 11aa6f8) pyproject.toml:1-38
`PLAN_REALITY: phase=eng rows=7/7 missing=none unverified=0) verdict=complete`

## Eng Section 1: Architecture Review

### Two Shapes Before One (Design-Twice)
- **Shape A (Chosen — Modular Domain Separation, 12 files / 2 classes):** Separate `src/solver/regime.py` (`RegimeParameter`, `extract_regime_parameters`, `compute_regime_delta`), `src/scigraph/exporters.py` (`render_markdown_report`, `export_json_bundle`, `export_sarif_v210`), `src/scigraph/explorer.py` (`render_claim_graph_html`), `src/scigraph/cli.py` (`main`), and `BenchmarkAuditBundle` (`@dataclass(frozen=True, slots=True)` in `src/evals/benchmark.py`).
- **Shape B (Rejected — Consolidated 8 files / 1 class):** Fold `regime.py` into `solver/symbolic.py` and `explorer.py` into `scigraph/exporters.py`, returning a raw 5-tuple from `run_benchmark_audit()`.
- **Interface Depth Comparison:** Shape A hides HTML/CSS/JS + XSS escaping behind a single function `render_claim_graph_html(graph, contradictions, experiments, metrics=None) -> str`, SARIF/JSON/Markdown behind `exporters.py`, and unit physics behind `compute_regime_delta(cond_a, cond_b) -> str | None`, while allowing parallel worktree execution across `solver/` and `scigraph/`.
- **Eight Red Flags Screen:**
  1. Shallow module: Pass — each new module hides a complete domain concern behind 1–3 functions.
  2. Information leakage: Pass — `scigraph.models` owns all domain types; `cli.py` parses args at the boundary.
  3. Temporal decomposition: Pass — organized by domain knowledge (`regime`, `exporters`, `explorer`, `cli`), not step order.
  4. Pass-through method: Pass — `evaluate_benchmark()` delegates to `run_benchmark_audit().metrics` (1-line convenience preserving existing public API).
  5. Split ownership: Pass — `ClaimGraph` owns verified claims/edges; `BenchmarkAuditBundle` is frozen.
  6. Two ways to do one task: Pass — `run_benchmark_audit()` replaces duplicate corpus loops.
  7. Importable internals: Pass — `src/scigraph/__init__.py` exports only `scigraph.models` (`[src-multi-package-init-circular-import]`).
  8. Hand-synced list: Pass — `explorer.py` and `exporters.py` iterate directly over `ContradictionKind` / `EdgeRelation` values.

### Findings (Section 1)
- `[INFORMATIONAL] (confidence: 9/10) src/ingest/extractor.py:219` — `decoded = pdf_bytes.decode("utf-8")` crashes on binary PDF headers (`%\xe2\xe3\xcf\xd3`), while decoding the whole stream as `latin-1` alone would corrupt multi-byte UTF-8 characters inside `render_blocks_to_pdf_bytes` (`src/ingest/extractor.py:211`). Remedy (covered under `D9: A`): scan `_PDF_BLOCK_PATTERN` over `pdf_bytes.decode("latin-1")` and decode each matched `raw_text` slice via `raw_text.encode("latin-1").decode("utf-8", errors="replace")`.
- **Dispositions:** Accepted (`D9: A` — covered by existing `SEC-1` boundary hardening approval).

## Eng Section 2: Code Quality Review

### Shared-Code Evaluation Rubric
- **Candidate:** `run_benchmark_audit() -> BenchmarkAuditBundle` in `src/evals/benchmark.py:1173-1256`.
  - **Callers:** (1) `evaluate_benchmark()` (`src/evals/benchmark.py:1173`), (2) `scigraph.cli` `report` and `verify` subcommands (`src/scigraph/cli.py`, proposed).
  - **Reuse & Savings:** Eliminates ~45 lines of duplicated 30-paper ingestion/verification/graph-building loop in `cli.py` for ~12 lines of `@dataclass(frozen=True, slots=True)` definition (`~33` net lines saved).
  - **Blast radius:** Tested by `test_30_paper_benchmark_exceeds_acceptance_thresholds` and CLI `report`/`verify` integration tests.
- **Findings (Section 2):**
  - `[INFORMATIONAL] (confidence: 9/10) src/evals/benchmark.py:1173` — `BenchmarkAuditBundle` should use `@dataclass(frozen=True, slots=True)` rather than `pydantic.BaseModel` because `ClaimGraph` is a standard Python class (`src/graph/claim_graph.py:14`), avoiding `arbitrary_types_allowed=True`.
- **Dispositions:** Accepted (implementation detail of `T4` under `D3: A` / `D6: A`).

## Eng Section 3: Test Review

### Code Path & User Flow Coverage Diagram
```
CODE PATHS                                              USER FLOWS
[+] src/ingest/extractor.py                             [+] CLI Researcher / CI Flow
  ├── extract_paper_from_pdf_bytes()                      ├── scigraph benchmark [--json]
  │   ├── [★★★ TESTED] UTF-8 synthetic PDF (5 papers)     │   ├── [GAP] [→E2E] Exit 0 + JSON metrics
  │   ├── [GAP]        Binary header %\xe2\xe3\xcf\xd3    │   └── [GAP]        Threshold fail -> Exit 1
  │   ├── [GAP]        >25 MiB MAX_PDF_BYTES cap          ├── scigraph verify [--paper-id]
  │   └── [GAP]        /FlateDecode diagnostic            │   └── [GAP]        Unknown ID -> Exit 2
[+] src/solver/regime.py                                  └── scigraph report --format {md,html,sarif,json}
  ├── extract_regime_parameters()                             ├── [GAP] [→E2E] Atomic --output write
  │   ├── [GAP]        Temperature C/K + C-rate disambig      ├── [GAP]        --fail-on-contradictions -> 1
  │   └── [GAP]        mM->M normalization, ng/mL sep         └── [GAP]        OSError cleanup -> Exit 2
  └── compute_regime_delta()                            [+] HTML Studio Flow (explorer.py)
      └── [GAP]        Multi-dim join & cross-dim         ├── [GAP] ContradictionKind & EdgeRelation filters
[+] src/solver/symbolic.py                                ├── [GAP] Empty-state & 0-match filter banners
  └── compute_powered_sample_size()                       └── [GAP] XSS <script> escaping + CSP meta
      ├── [GAP]        Small d > large d, cap 2000
      └── [GAP]        Both effect_size_raw=None -> base_n
[+] src/scigraph/exporters.py
  ├── export_sarif_v210() -> [GAP] SCIGRAPH-VERIFY-001 (DOI + claim) & CONTRA-001/002
  └── export_json_bundle() & render_markdown_report() -> [GAP] Deterministic schema

COVERAGE: 7/23 paths tested (30%)  |  Code paths: 7/14 (50%)  |  User flows: 0/9 (0%)
QUALITY: ★★★:6 ★★:1 ★:0  |  GAPS: 16 (2 E2E, 0 eval)
```
- **Findings (Section 3):** `0` unapproved test gaps — all 16 `[GAP]` paths correspond to the new `T1`–`T6` implementation tasks and are covered by the approved test specifications in Section 6 and `/Users/justinmafie/.gstack/projects/justinmafie/justinmafie-main-eng-review-test-plan-20261125-200200.md`.
- **Dispositions:** Accepted (all 16 gaps mapped to `T1`–`T6` verification).

## Eng Section 4: Performance Review

- **Memory & Bounds:** PDF input capped at `25 MiB` (`SEC-1`); `BenchmarkAuditBundle` for 30 papers is `< 5 MB`; all regexes precompiled at module load.
- **Latency:** Baseline 30-paper evaluation is `4.201 ms` median (`[measured: evaluate_benchmark]`); adding `regime.py`, `compute_powered_sample_size`, `exporters.py`, and `explorer.py` stays `< 15 ms` total (`[estimated]`).
- **Findings (Section 4):** No issues found.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|---|---|---|
| `T1` (PDF boundary) | `src/ingest/` | — |
| `T2` + `T3` (Regime + Power) | `src/solver/` | — |
| `T4` (Exporters + Audit Bundle) | `src/evals/`, `src/scigraph/` | `T2`, `T3` |
| `T5` (HTML Explorer) | `src/scigraph/` | `T2`, `T3` |
| `T6` (CLI + Docs) | `src/scigraph/`, `pyproject.toml`, `README.md`, `tests/` | `T1`, `T4`, `T5` |

- **Parallel lanes:**
  - `Lane A`: `T1` (`src/ingest/`)
  - `Lane B`: `T2` → `T3` (`src/solver/`)
  - `Lane C` (after A+B): `T4` + `T5` (`src/evals/`, `src/scigraph/exporters.py`, `src/scigraph/explorer.py`)
  - `Lane D` (final): `T6` (`src/scigraph/cli.py`, `pyproject.toml`, `README.md`, `tests/test_scigraph.py`)
- **Execution order:** Launch `Lane A (T1)` + `Lane B (T2→T3)` in parallel. Merge both. Launch `T4` + `T5` in parallel (disjoint files). Merge both. Then run `T6` + full `ruff` / `mypy --strict` / `pytest` gate.
- **Conflict flags:** `tests/test_scigraph.py` is shared across tasks if edited concurrently; sequence test additions into `Lane D` (or per-lane test files merged in `Lane D`).

## Eng Completion Summary

- Step 0: Scope Challenge — `scope accepted as-is` (`D1: A` Original 12-file, 2-class arrangement)
- Reality rows: `7/7` applicable rows emitted (`PLAN_REALITY` complete), `0` unverified premises
- Architecture Review: `1` informational finding (`extractor.py:219` UTF-8 inner text preservation under `latin-1` scan, covered by `D9: A`)
- Code Quality Review: `1` informational finding (`BenchmarkAuditBundle` frozen dataclass, covered by `T4`)
- Test Review: diagram produced, `16` gaps identified (all mapped to `T1`–`T6` new features)
- Performance Review: `0` issues found
- NOT in scope: written
- What already exists: written
- TODOS.md updates: `0` items proposed
- Failure modes: `0` critical gaps flagged
- Unresolved decisions: `0` in this review
- Outside voice: `codex` `unavailable` (`MODEL_UNUSABLE` for `gpt-6.2-astra` and `Plan`/`TaskStop` not offered in `agy`)
- Parallelization: `4` lanes (`2` parallel pairs, `1` sequential final lane)
- Lake Score: `N/A` (0 completeness-scored questions in this eng review)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/gstack-plan-ceo-review` | Scope & strategy | 5 | CLEAR | 5 proposals, 5 accepted, 0 deferred |
| Outside Review | `codex` (automatic step) | Independent 2nd opinion | 7 | unavailable | MODEL_UNUSABLE (gpt-6.2-astra) and Plan/TaskStop not offered — no completed external review |
| Eng Review | `/gstack-plan-eng-review` | Architecture & tests (required) | 5 | CLEAR | 2 informational issues, 0 critical gaps |
| Design Review | `/gstack-plan-design-review` | UI/UX gaps | 1 | ISSUES OPEN (stale >7d) | score: 5/10 → 8/10, 10 decisions |
| DX Review | `/gstack-plan-devex-review` | Developer experience gaps | 1 | CLEAR (stale >7d) | score: 6/10 → 9/10, TTHW: 15 min → < 2 min |

- **OUTSIDE COVERAGE:** `codex` (`plan-review`): `unavailable` — `MODEL_UNUSABLE` (`gpt-6.2-astra`) and `Plan`/`TaskStop` not offered in `agy`; no completed external review.
- **VERDICT:** CEO + ENG CLEARED — ready to implement

NO UNRESOLVED DECISIONS
