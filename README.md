# SciGraph: Neuro-Symbolic Scientific Discovery and Reasoning Engine

SciGraph ingests multi-column scientific PDFs and layout blocks, extracts typed `(Intervention, Condition, Outcome)` claim tuples with verbatim evidence spans, verifies that every DOI, quote, p-value, and sample size exists verbatim in the source text, and resolves cross-paper contradictions into falsifiable experiments through a symbolic constraint solver.

- **Spec and GTM doc:** [SciGraph: Neuro-Symbolic Scientific Discovery & Reasoning Engine](https://docs.google.com/document/d/19a1Bk0TOTjHZRyQtQwKP8O--Cq8Vs4Ke2eob2Gc389M/edit?usp=drivesdk&ouid=110227624285917376281)
- **Portfolio strategy:** [Startup & Open-Source Cross-Project Strategy](https://docs.google.com/document/d/12Wpg5mMGnjnl2uhMBTOR0QqRzQj8kwfzTLpvLoRuB5Q/edit?usp=drivesdk&ouid=110227624285917376281)
- **Architecture and threat model:** See `AGENTS.md`, `docs/adr/001-typed-claim-tuples-and-verbatim-evidence-verification.md`, and `docs/THREAT_MODEL.md`.

## Architecture

1. **Domain models (`src/scigraph/models.py`)**: Defines frozen Pydantic v2 models (`strict=True`, `frozen=True`, `extra="forbid"`) for `Paper`, `PaperSection`, `LayoutBlock`, `EvidenceSpan`, `ClaimTuple`, `StatisticalEvidence`, `ScientificClaim`, `EvidenceEdge`, `ContradictionPair`, and `FalsifiableExperiment`.
2. **Layout-aware ingestion and verbatim verifier (`src/ingest/`)**: Orders two-column PDF layout blocks in reading order (`order_layout_blocks`, `extract_paper_from_pdf_bytes`), extracts typed claim tuples (`extract_claims_from_paper`), and runs `verify_claim_verbatim` to reject any claim whose DOI, quote slice, p-value string, or sample size `n` does not match the source text verbatim.
3. **Claim graph (`src/graph/claim_graph.py`)**: Stores verified papers and claims, rejects unverified claims at the boundary, and builds `SUPPORTS`, `REPLICATES`, `CONTRADICTS`, and `QUALIFIES` edges across papers sharing normalized `(intervention, outcome)` pairs.
4. **Symbolic contradiction solver (`src/solver/symbolic.py`, `src/solver/regime.py`)**: Maps claim effect directions into discrete constraints (`{-1, 0, +1}`), isolates unsatisfiable cores (`check_claim_set_satisfiability`, `detect_contradictions`), computes quantitative physical/chemical regime deltas (`compute_regime_delta`), and generates effect-size-calibrated `FalsifiableExperiment` designs (`propose_falsifiable_experiments`).
5. **CLI, Exporters, and HTML Studio (`src/scigraph/cli.py`, `src/scigraph/exporters.py`, `src/scigraph/explorer.py`)**: Provides `benchmark`, `verify`, and `report --format {markdown,html,sarif,json}` subcommands with atomic `--output` writes, OASIS SARIF v2.1.0 CI diagnostics, and an XSS-safe interactive HTML Claim-Graph Explorer.

## Quickstart

Run the linter, strict type checker, and test suite in Python 3.12:

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy --strict src tests
.venv/bin/pytest -v
PYTHONPATH=src .venv/bin/python -m scigraph.cli benchmark
PYTHONPATH=src .venv/bin/python -m scigraph.cli report --format html --output scigraph-studio.html
PYTHONPATH=src .venv/bin/python -m scigraph.cli report --format sarif --output scigraph.sarif
```

## Reproducible benchmark numbers

Measured on Python 3.12.12 (`pydantic 2.14.4`) across the 30-paper benchmark corpus (`src/evals/benchmark.py`), including 5 open-access arXiv and PubMed two-column PDF streams (`src/ingest/open_access_corpus.py`) and 150 adversarial decoy claims containing fabricated DOIs, p-values, sample sizes, and quote spans:

| Metric | Target threshold | Measured result | Evidence |
| --- | --- | --- | --- |
| Structured claim-tuple extraction F1 | >= 0.85 | **1.0000** (60 TP, 0 FP, 0 FN) | `test_30_paper_benchmark_exceeds_acceptance_thresholds` |
| Fabricated DOIs accepted | 0 | **0** (30 / 30 fabricated DOI decoys rejected) | `test_deterministic_verifier_rejects_fabricated_doi_p_value_and_sample_size` |
| Fabricated p-values accepted | 0 | **0** (120 / 120 fabricated p-value, sample-size, and span decoys rejected) | `test_30_paper_benchmark_exceeds_acceptance_thresholds` |
| End-to-end 30-paper pipeline latency (median) | Deterministic local run | **2.671 ms** (range 2.403 to 2.961 ms across 7 runs) | Bound by regex tokenization and Pydantic v2 validation on 1 core |

Regenerate the benchmark numbers with:

```bash
PYTHONPATH=src .venv/bin/python -c "
import statistics
from evals import evaluate_benchmark

evaluate_benchmark()
runs = [evaluate_benchmark() for _ in range(7)]
med = statistics.median(r.elapsed_ms for r in runs)
lo = min(r.elapsed_ms for r in runs)
hi = max(r.elapsed_ms for r in runs)
r = runs[0]
print(f'Papers: {r.total_papers} | F1: {r.f1_score:.4f} | Fab DOIs: {r.fabricated_dois_accepted} | Fab p-values: {r.fabricated_p_values_accepted} | Decoys rejected: {r.adversarial_decoys_rejected} | Contradictions: {r.contradictions_detected} | Median: {med:.3f}ms ({lo:.3f}..{hi:.3f}ms)')
"
```
