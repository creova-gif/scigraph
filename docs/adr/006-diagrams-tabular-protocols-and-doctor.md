# ADR-006: Diagrams, Tabular & PubMed Ingest, Lab Protocols, and System Diagnostics

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

ADRs 001–005 established SciGraph's verbatim claim verification, persistent graph storage, multi-tenant workspaces, evidence scoring, literature connectors, provenance manifests, RBAC, entity canonicalization, ROI experiment prioritization, and webhook alerting. Operationalizing SciGraph across research teams and automated CI environments surfaces four remaining workflow gaps:

1. **Embeddable Graph Diagrams:** While SciGraph exports an interactive HTML explorer and OASIS SARIF diagnostics, teams also need lightweight, deterministic text diagrams (Mermaid flowcharts for Markdown/GitHub PRs and Graphviz DOT for publication-grade rendering).
2. **Tabular & PubMed XML Corpus Ingestion:** `load_papers_from_path` previously supported `.json` and `.pdf` inputs only. Research teams frequently curate screening tables in `.csv`/`.tsv` spreadsheets or export `<PubmedArticleSet>` XML from PubMed EFetch.
3. **Lab-Ready Experiment Protocols:** `propose_falsifiable_experiments` and `prioritize_experiments` produce ranked `FalsifiableExperiment` summaries, but wet-lab and clinical teams need structured, pre-registered, step-by-step execution protocols with explicit phases and falsification rules.
4. **Single-Command System Diagnostics:** Operators deploying SciGraph in new Python environments or CI runners need a deterministic self-check to verify Python version compatibility, `/FlateDecode` PDF extraction, benchmark acceptance gates, and workspace directory writability.

## Decision

1. **Mermaid & Graphviz DOT Diagram Exporters (`src/scigraph/diagrams.py`):**
   - `export_mermaid_flowchart(graph, contradictions=())` renders a deterministic `flowchart LR` diagram with sanitized node IDs (`_sanitize_id`), escaped claim labels (`_escape_label`, `_format_claim_label`), sorted `graph.claims` nodes, sorted `graph.edges` (`-->|"relation"|`), and dashed contradiction links (`-. "CONFLICT: kind" .->`).
   - `export_graphviz_dot(graph, contradictions=())` renders a deterministic `digraph SciGraph` (`rankdir=LR;`) grouping claims into `subgraph cluster_<paper_id>` clusters per paper, coloring `EvidenceEdge` relations (`darkgreen` for `SUPPORTS`/`REPLICATES`, `crimson` for `CONTRADICTS`, `darkorange` for `QUALIFIES`), and emitting dashed `crimson` `CONFLICT` edges for `ContradictionPair` entries.

2. **Tabular CSV/TSV & PubMed EFetch XML Ingestion (`src/ingest/tabular.py`, `src/ingest/corpus_loader.py`):**
   - `load_papers_from_csv(path, *, delimiter=None)` auto-detects `"\t"` for `.tsv` and `","` for `.csv`, requires `paper_id`, `title`, and `abstract` columns with at least one non-empty data row, validates DOIs against `DOI_PATTERN` (falling back to `10.0000/tabular.<sanitized_id>`), parses semicolon-delimited `authors`, `venue` (default `"tabular-import"`), and `publication_year` (`1900..2100`, default `2026`), and builds `Paper` records with an `ABSTRACT` `PaperSection`.
   - `parse_pubmed_efetch_xml(xml_bytes)` parses PubMed `<PubmedArticleSet>` XML via `xml.etree.ElementTree`, extracting `PMID` (`paper_id="pubmed-<pmid>"`), `ArticleTitle`, `AbstractText` segments, `ArticleId[@IdType="doi"]` (falling back to `10.0000/pubmed.<pmid>`), `AuthorList` (`LastName ForeName` or `CollectiveName`), `Journal/Title`, and `PubDate/Year`.
   - `load_papers_from_path` (`src/ingest/corpus_loader.py`) routes `.csv`/`.tsv` files to `load_papers_from_csv` and `.xml` files to `parse_pubmed_efetch_xml` for both single-file and top-level directory loads.

3. **Prioritized Lab Experiment Protocols (`src/solver/protocols.py`):**
   - `ProtocolStep` and `ExperimentProtocol` (frozen, strict Pydantic v2 models) encode ordered 4-phase execution sheets (`PRE_REGISTRATION`, `RANDOMIZATION`, `MEASUREMENT`, `STATISTICAL_ANALYSIS`) carrying `priority_rank`, `cost_tier`, `arms`, `sample_size_total`, `alpha_threshold`, `power_target=0.90`, and `falsification_criterion`.
   - `generate_experiment_protocols(graph, contradictions, experiments)` ranks `experiments` via `prioritize_experiments` and returns deterministic `proto-<experiment_id>` `ExperimentProtocol` tuples.
   - `render_protocols_markdown(protocols)` formats protocol tuples into structured Markdown protocol sheets.

4. **System Diagnostics (`src/scigraph/doctor.py`):**
   - `DiagnosticCheck` and `DoctorReport` (frozen, strict Pydantic v2 models) record `python_version`, `checks`, and `all_passed`.
   - `run_doctor(workspace_root=None)` executes `_check_python_version` (`>= 3.12`), `_check_flate_pdf_roundtrip` (`extract_text_from_pdf_bytes` on an in-memory `/FlateDecode` PDF), `_check_benchmark_gate` (`evaluate_benchmark()` with `f1_score >= 0.85` and `0` fabricated DOIs/p-values), and optional `_check_workspace_writable` (temporary file write/unlink check).

## Alternatives Considered

- **Adding third-party diagram or XML dependencies (`graphviz`, `lxml`, `pandas`):** Rejected to preserve SciGraph's minimal dependency footprint and avoid native binary requirements in CI and air-gapped environments.
- **Allowing partial/headerless CSV rows without `paper_id`, `title`, or `abstract`:** Rejected because downstream claim extraction and verbatim verification require stable paper identifiers and non-empty source text.
- **Unranked or free-form protocol prose:** Rejected in favor of typed `ExperimentProtocol` models ordered by `prioritize_experiments` so protocols remain machine-validatable and consistent with ROI rankings.

## Consequences & Failure Modes

- **Positive:** Teams can embed Mermaid/DOT claim graphs in docs, ingest `.csv`/`.tsv`/`.xml` corpora directly through `load_papers_from_path`, generate pre-registered lab protocols, and validate runtime health with `run_doctor`.
- **Negative:** `parse_pubmed_efetch_xml` skips `<PubmedArticle>` elements missing `PMID`, `ArticleTitle`, or `AbstractText`, and `load_papers_from_csv` constructs abstract-only `Paper` records (`SectionKind.ABSTRACT`).
- **Mitigation:** Raise explicit `ValueError` diagnostics on malformed XML, missing CSV headers, or empty required fields, and document `.csv`/`.tsv`/`.xml` abstract-level ingestion alongside full-text `.pdf`/`.json` support.
