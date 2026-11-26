# ADR-002: /FlateDecode PDF Ingestion, Custom Corpus Loader, Persistent Graph Store, and Extended Regime Dimensions

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

ADR-001 established SciGraph's core neuro-symbolic pipeline over in-memory `LayoutBlock` fixtures and uncompressed PDF streams. To support local, offline workflows on real-world corpora without introducing heavyweight third-party PDF or database dependencies, SciGraph needed four capabilities:

1. **Compressed PDF Stream Decoding & Text Operators:** Real-world academic PDFs compress content streams with `/FlateDecode` (zlib) and emit kerning-adjusted text arrays via `TJ` operators rather than only literal `Tj` strings.
2. **Custom Corpus Ingestion:** Users need a single entry point to load `.pdf` files, `.json` paper bundles, or directories of mixed files from disk.
3. **Persistent ClaimGraph Storage & Querying:** Ingested graphs must persist deterministically between CLI invocations in either atomic JSON bundles or a zero-dependency SQLite database, and support structured claim filtering.
4. **Expanded Physical/Chemical Regime Coverage:** Cross-paper contradiction resolution in chemistry, biology, and pharmacology requires normalizing `ph`, `pressure`, and `dosage` alongside existing temperature, humidity, and electrochemical dimensions.

## Decision

1. **`/FlateDecode` Decompression with Bomb Guard & `TJ` Support (`src/ingest/extractor.py`):**
   - `_validate_pdf_bytes` enforces `MAX_PDF_BYTES = 25 * 1024 * 1024` (25 MiB), checks the `%PDF-` header, and rejects `/Encrypt` PDFs.
   - `_decode_pdf_streams` inspects stream dictionaries via `_extract_stream_filters`, rejecting unsupported filters and routing `/FlateDecode` streams through `_decompress_flate`.
   - `_decompress_flate` uses `zlib.decompressobj().decompress(data, MAX_DECOMPRESSED_BYTES + 1)` with `MAX_DECOMPRESSED_BYTES = 50 * 1024 * 1024` (50 MiB) to guard against decompression bombs, raising `ValueError` if output or unconsumed tail exceeds the limit.
   - `extract_text_from_pdf_bytes` and `_decode_tj_array` decode both `(string) Tj` and `[...] TJ` array operators, inserting spaces when negative kerning adjustments are `<= -150.0` and normalizing ligatures and math glyphs via `normalize_pdf_text`.

2. **Zero-Dependency Custom Corpus Loader (`src/ingest/corpus_loader.py`):**
   - `load_papers_from_path(path)` accepts a `.json` file, a `.pdf` file, or a directory (iterating top-level entries via `sorted(path.iterdir())`).
   - JSON corpora accept either a list of paper objects or `{"papers": [...]}` and validate each entry with `Paper.model_validate_json`.
   - PDF files are decoded via `extract_text_from_pdf_bytes`, extracting a Crossref DOI if present in the text or assigning a deterministic `10.0000/local.<stem>` fallback DOI.

3. **Persistent Graph Store & Claim Query Engine (`src/graph/store.py`, `src/graph/claim_graph.py`):**
   - `ClaimGraph.query_claims` filters verified claims by case-insensitive substrings (`intervention`, `condition`, `outcome`) and exact `effect_direction` or `paper_id` matches.
   - `save_graph_json` writes deterministic sorted JSON atomically using `tempfile.NamedTemporaryFile`, `os.fsync`, and `os.replace`; `load_graph_json` reloads and validates via `ClaimGraph.from_dict`.
   - `GraphSQLiteStore` provides zero-dependency `sqlite3` persistence over `papers`, `claims` (indexed on `claim_id`, `paper_id`, `intervention`, `outcome`), and `edges` tables with `save_graph` and `load_graph`.

4. **Extended Regime Dimensions (`src/solver/regime.py`):**
   - `_PATTERN_SPECS` adds `ph` (canonical unit `pH`), `pressure` (`MPa`, `kPa`, `Pa`, `bar`, `atm` normalized to `kPa` via `_normalize_pressure`), and `dosage` (`mg/kg`, `ug/kg`, `g/kg` normalized to `mg/kg` via `_normalize_dosage`) for `extract_regime_parameters` and `compute_regime_delta`.

## Alternatives Considered

- **External PDF libraries (`pypdf`, `pdfplumber`, `pymupdf`):** Rejected for the core ingestion path to keep SciGraph zero-dependency beyond Pydantic v2 and Python 3.12's stdlib (`zlib`, `sqlite3`, `json`, `re`).
- **In-place `Path.write_text` for JSON store persistence:** Rejected because partial writes on crash or interruption can corrupt persisted graph bundles; `NamedTemporaryFile` + `os.fsync` + `os.replace` guarantees atomic replacement.
- **ORM layer (e.g., SQLAlchemy) for graph persistence:** Rejected as unnecessary overhead for three schema tables where `sqlite3` + Pydantic `model_dump_json` / `ClaimGraph.from_dict` preserves strict boundary validation.

## Consequences & Failure Modes

- **Positive:** SciGraph can ingest local `/FlateDecode` PDFs and JSON corpora, persist verified `ClaimGraph` state to SQLite or atomic JSON, and query claims directly from the CLI with zero new runtime dependencies.
- **Positive:** The 50 MiB `MAX_DECOMPRESSED_BYTES` bound prevents memory exhaustion from malformed or malicious `/FlateDecode` streams.
- **Negative:** PDFs using `/ASCII85Decode`, `/LZWDecode`, `/DCTDecode`, or `/Encrypt` encryption are explicitly rejected with `ValueError` rather than partially decoded.
- **Mitigation:** Callers can convert unsupported PDFs to JSON `Paper` bundles or uncompressed/`/FlateDecode` streams before passing them to `load_papers_from_path`.
