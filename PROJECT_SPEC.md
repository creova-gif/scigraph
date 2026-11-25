# SciGraph: Neuro-Symbolic Scientific Discovery & Reasoning Engine

- **Model:** Open-Source MIT Core + Team R&D Workspace ($99-$499/seat/mo)
- **Thesis Alignment:** #67 Discovery Engines for Science, #68 AI Reasoning Systems, #07 AI-Native Discovery Engines
- **Full Google Doc Spec:** [SciGraph: Neuro-Symbolic Scientific Discovery & Reasoning Engine](https://docs.google.com/document/d/19a1Bk0TOTjHZRyQtQwKP8O--Cq8Vs4Ke2eob2Gc389M/edit?usp=drivesdk&ouid=110227624285917376281)
- **Portfolio Strategy:** [00 - Startup & Open-Source Cross-Project Strategy](https://docs.google.com/document/d/12Wpg5mMGnjnl2uhMBTOR0QqRzQj8kwfzTLpvLoRuB5Q/edit?usp=drivesdk&ouid=110227624285917376281)

## 1. Goal & Problem
Ingest scientific PDFs, build typed (Intervention, Condition, Outcome) claim graphs, detect cross-paper contradictions, and propose falsifiable experiments.

## 2. Target Customer (ICP) & Monetization
Biotech/pharma R&D literature teams, university labs, materials & climate researchers.

## 3. Tech Stack
Python 3.12, PyMuPDF/GROBID, NetworkX/Neo4j/Postgres, Z3 SMT solver, Anthropic Claude/NIM, Pydantic v2.

## 4. Evaluation & Acceptance Thresholds
>= 0.85 F1 on structured claim-tuple extraction; 0 fabricated DOIs or p-values across 30-paper benchmark.

## 5. Key Architectural Decision (ADR-001)
Represent findings as typed graph tuples with verbatim evidence spans rather than flat vector chunks.

## 6. Day 1–5 Quickstart
- [ ] Set up ingest/, graph/, solver/, and evals/ directories
- [ ] Define Pydantic models for Paper, ScientificClaim, and EvidenceEdge
- [ ] Test layout-aware PDF extraction on 5 open-access arXiv/PubMed papers
- [ ] Build deterministic verifier confirming extracted p-values/sample sizes exist verbatim
