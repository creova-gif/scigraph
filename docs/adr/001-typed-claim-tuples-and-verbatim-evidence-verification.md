# ADR-001: Represent Scientific Findings as Typed Claim Tuples with Deterministic Verbatim Span Verification

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context

Scientific literature synthesis pipelines that chunk PDFs into flat text vectors lose structural relationships between interventions, experimental conditions, and measured outcomes. Worse, LLM-based extractors frequently hallucinate DOIs, round or fabricate p-values (such as reporting `p < 0.01` when the source states `p = 0.042`), or invent sample sizes (`n`), corrupting downstream meta-analyses and contradiction detection.

SciGraph must satisfy four engineering requirements from `PROJECT_SPEC.md`:
1. Represent findings as typed `(Intervention, Condition, Outcome)` claim tuples linked by `EvidenceEdge` relations (`SUPPORTS`, `CONTRADICTS`, `REPLICATES`, `QUALIFIES`).
2. Extract structured sections and claims from multi-column academic PDFs and layout blocks without merging adjacent columns out of reading order.
3. Enforce a deterministic verifier confirming that every extracted DOI, verbatim evidence quote, p-value, and sample size `n` exists verbatim in the source paper text (`0` fabricated DOIs or p-values).
4. Achieve `>= 0.85` F1 on structured claim-tuple extraction across a 30-paper benchmark and resolve cross-paper contradictions into falsifiable experimental proposals via symbolic constraint solving.

## Decision

1. **Frozen Pydantic v2 Domain Models (`src/scigraph/models.py`):** All domain objects (`Paper`, `PaperSection`, `EvidenceSpan`, `ClaimTuple`, `StatisticalEvidence`, `ScientificClaim`, `EvidenceEdge`, `ContradictionPair`, `FalsifiableExperiment`) use `ConfigDict(strict=True, frozen=True, extra="forbid")`. Semantic primitives (DOI format, `[0.0, 1.0]` p-value bounds, positive sample size `n`, character offsets `start_char < end_char`) are validated at model construction.
2. **Column-Aware PDF & Layout Ingestion (`src/ingest/`):** PDF and layout block ingestion orders text blocks by page, column bucket (left column before right column for two-column academic layouts, with full-width spanning headers/abstracts ordered first), and vertical coordinate before extracting structured sections and candidate `ScientificClaim` records.
3. **Deterministic Verbatim Evidence Verifier (`src/ingest/verifier.py`):** Before any `ScientificClaim` enters the knowledge graph, `verify_claim_verbatim(paper, claim)` checks four hard predicates against the source `Paper`:
   - The paper's DOI matches the strict Crossref DOI pattern (`^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$`) and appears verbatim in the source document metadata/header.
   - `claim.evidence_span.verbatim_text` matches `paper.full_text[start_char:end_char]` exactly.
   - `claim.statistics.p_value_raw` appears verbatim inside `claim.evidence_span.verbatim_text` and parses numerically to `claim.statistics.p_value`.
   - `claim.statistics.sample_size_raw` appears verbatim inside `claim.evidence_span.verbatim_text` and parses to `claim.statistics.sample_size`.
   Any claim failing any of these checks is rejected and flagged with specific `VerificationFailureReason` codes, guaranteeing zero fabricated DOIs or p-values in verified graphs.
4. **Symbolic Constraint Solver for Contradictions & Experiments (`src/solver/`):** `ClaimGraph` groups verified claims by normalized `(intervention, outcome)` keys. The solver encodes claim assertions over discrete effect directions (`INCREASES`, `DECREASES`, `NO_EFFECT`) and condition predicates into a symbolic constraint system, detects unsatisfiable cores across papers (direct contradictions vs. condition-stratified divergences), and synthesizes minimal `FalsifiableExperiment` designs specifying the discriminating condition, required sample size, and falsification criteria.

## Alternatives Considered

- **Flat RAG vector chunking with cosine similarity:** Rejected. Embedding similarity conflates opposing claims (`Intervention A increases Outcome Y` vs. `Intervention A decreases Outcome Y` have nearly identical embeddings) and cannot prove whether a p-value was fabricated.
- **LLM-as-a-judge for p-value and DOI verification:** Rejected. Probabilistic verification cannot guarantee `0` fabricated DOIs or p-values and adds network latency and cost where exact substring and numeric token parsing is deterministic and sub-millisecond.
- **Untyped NetworkX dictionaries without boundary schemas:** Rejected. Scatters key-existence checks across graph and solver modules and violates `mypy --strict` type safety.

## Consequences & Failure Modes

- **Positive:** By construction, `0` fabricated DOIs, p-values, or sample sizes can pass `verify_claim_verbatim` into `ClaimGraph`.
- **Positive:** Symbolic contradiction detection distinguishes true conflicting findings (same condition, opposite effect direction) from conditional effect modification (different dosage, genotype, or temperature regime).
- **Negative:** Strict verbatim substring matching rejects claims when OCR or PDF glyph extraction corrupts mathematical operators (such as ligature or private-use Unicode glyphs for `≤` or `=`).
- **Mitigation:** The layout extractor normalizes typographic ligatures and Unicode minus/comparison glyphs during page text assembly before recording character offsets.
