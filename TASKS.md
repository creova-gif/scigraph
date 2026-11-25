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
- [ ] Run first external design-partner or open-source release
