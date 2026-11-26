"""Reproducible declarative batch pipeline runner for SciGraph."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field

from graph.claim_graph import ClaimGraph
from graph.scoring import compute_topic_consensus
from graph.store import GraphSQLiteStore, save_graph_json
from ingest.corpus_loader import load_papers_from_path
from ingest.extractor import extract_claims_from_paper
from ingest.verifier import verify_paper_claims
from scigraph.diff import export_bibtex, export_ris
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import (
    export_json_bundle,
    export_sarif_v210,
    render_markdown_report,
)
from scigraph.models import PaperVerificationReport
from solver.symbolic import detect_contradictions, propose_falsifiable_experiments

OutputFormat = Literal["markdown", "html", "sarif", "json", "bibtex", "ris"]

_SQLITE_SUFFIXES: frozenset[str] = frozenset({".db", ".sqlite", ".sqlite3"})
_SUPPORTED_STORE_SUFFIXES: frozenset[str] = frozenset({".json", *_SQLITE_SUFFIXES})

_OUTPUT_FILENAMES: dict[OutputFormat, str] = {
    "markdown": "report.md",
    "html": "report.html",
    "sarif": "report.sarif",
    "json": "report.json",
    "bibtex": "references.bib",
    "ris": "references.ris",
}


class PipelineConfig(BaseModel):
    """Declarative configuration for a deterministic SciGraph batch run."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    input_path: str = Field(min_length=1)
    store_path: str = Field(min_length=1)
    report_dir: str = Field(min_length=1)
    formats: tuple[OutputFormat, ...] = ("markdown", "sarif", "json")
    fail_on_contradictions: bool = False
    min_verified_papers: int = Field(default=1, ge=0)


class PipelineSummary(BaseModel):
    """Deterministic summary and pass/fail gate result of a pipeline run."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    papers_loaded: int = Field(ge=0)
    papers_verified: int = Field(ge=0)
    claims_verified: int = Field(ge=0)
    claims_rejected: int = Field(ge=0)
    contradictions_found: int = Field(ge=0)
    consensus_topics: int = Field(ge=0)
    outputs_written: tuple[str, ...]
    graph_sha256: str = Field(min_length=64, max_length=64)
    passed: bool


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write UTF-8 text to ``path`` via NamedTemporaryFile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise


def _compute_graph_sha256(graph: ClaimGraph) -> str:
    """Return a deterministic SHA-256 hex digest of the ClaimGraph payload."""
    canonical = json.dumps(
        graph.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _persist_graph(graph: ClaimGraph, store_path: Path) -> None:
    """Persist a ClaimGraph to JSON or SQLite based on ``store_path`` suffix."""
    suffix = store_path.suffix.lower()
    if suffix == ".json":
        save_graph_json(graph, store_path)
    elif suffix in _SQLITE_SUFFIXES:
        GraphSQLiteStore(store_path).save_graph(graph)
    else:
        raise ValueError(
            f"Unsupported store suffix {store_path.suffix!r} for {store_path}; "
            f"expected one of {sorted(_SUPPORTED_STORE_SUFFIXES)}"
        )


def run_pipeline(config: PipelineConfig) -> PipelineSummary:
    """Execute the end-to-end SciGraph ingestion, verification, solving, and export pipeline."""
    store_path = Path(config.store_path)
    if store_path.suffix.lower() not in _SUPPORTED_STORE_SUFFIXES:
        raise ValueError(
            f"Unsupported store suffix {store_path.suffix!r} for {store_path}; "
            f"expected one of {sorted(_SUPPORTED_STORE_SUFFIXES)}"
        )

    papers = load_papers_from_path(Path(config.input_path))
    graph = ClaimGraph()
    reports: list[PaperVerificationReport] = []

    papers_verified = 0
    claims_verified = 0
    claims_rejected = 0

    for paper in papers:
        extracted = extract_claims_from_paper(paper)
        report = verify_paper_claims(paper, extracted)
        reports.append(report)

        if report.doi_verified:
            papers_verified += 1
            graph.add_paper(paper)
            for claim in report.verified_claims:
                graph.add_verified_claim(paper, claim)

        claims_verified += len(report.verified_claims)
        claims_rejected += len(report.rejected_claim_ids)

    graph.build_edges()
    contradictions = detect_contradictions(graph)
    experiments = propose_falsifiable_experiments(contradictions)
    consensus = compute_topic_consensus(graph)

    _persist_graph(graph, store_path)

    report_dir = Path(config.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    outputs_written: list[str] = []
    for fmt in dict.fromkeys(config.formats):
        out_path = report_dir / _OUTPUT_FILENAMES[fmt]
        match fmt:
            case "markdown":
                content = render_markdown_report(graph, contradictions, experiments)
            case "html":
                content = render_claim_graph_html(graph, contradictions, experiments)
            case "sarif":
                content = export_sarif_v210(contradictions, reports)
            case "json":
                content = export_json_bundle(graph, contradictions, experiments)
            case "bibtex":
                content = export_bibtex(graph.papers)
            case "ris":
                content = export_ris(graph.papers)
            case _ as unreachable:
                assert_never(unreachable)
        _atomic_write_text(out_path, content)
        outputs_written.append(str(out_path))

    summary_path = report_dir / "summary.json"
    outputs_written.append(str(summary_path))

    contradictions_found = len(contradictions)
    passed = (
        papers_verified >= config.min_verified_papers
        and claims_rejected == 0
        and (not config.fail_on_contradictions or contradictions_found == 0)
    )

    summary = PipelineSummary(
        papers_loaded=len(papers),
        papers_verified=papers_verified,
        claims_verified=claims_verified,
        claims_rejected=claims_rejected,
        contradictions_found=contradictions_found,
        consensus_topics=len(consensus),
        outputs_written=tuple(outputs_written),
        graph_sha256=_compute_graph_sha256(graph),
        passed=passed,
    )
    _atomic_write_text(
        summary_path,
        json.dumps(summary.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
    )
    return summary
