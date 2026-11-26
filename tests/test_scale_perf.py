"""Scalability and concurrency regression tests for SciGraph."""

import concurrent.futures
import time
from pathlib import Path

from evals.benchmark import BENCHMARK_30_PAPERS
from graph.claim_graph import ClaimGraph
from ingest import extract_paper_from_layout
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    Paper,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)
from scigraph.workspace import WorkspaceManager
from solver.prioritizer import prioritize_experiments
from solver.symbolic import detect_contradictions, propose_falsifiable_experiments


def _build_500_claim_graph() -> ClaimGraph:
    """Construct a deterministic 500-claim graph spanning 50 topics with contradictions."""
    graph = ClaimGraph()
    for idx in range(500):
        topic_idx = idx // 10
        direction = EffectDirection.INCREASES if idx % 2 == 0 else EffectDirection.DECREASES
        paper_id = f"scale-paper-{idx:03d}"
        doi = f"10.1234/scale.{idx:04d}"
        verbatim = (
            f"Compound-{topic_idx:02d} {direction.value} Biomarker-{topic_idx:02d} "
            "(p = 0.004, n = 120)."
        )
        full_text = f"DOI: {doi}. Results: {verbatim}"
        start_char = full_text.index(verbatim)
        end_char = start_char + len(verbatim)

        paper = Paper(
            paper_id=paper_id,
            doi=doi,
            title=f"Scale Study {idx:03d}",
            authors=("A. Researcher",),
            publication_year=2025,
            venue="Journal of Scale Tests",
            full_text=full_text,
        )
        claim = ScientificClaim(
            claim_id=f"scale-claim-{idx:03d}",
            paper_id=paper_id,
            doi=doi,
            claim_tuple=ClaimTuple(
                intervention=f"Compound-{topic_idx:02d}",
                condition="adult cohort",
                outcome=f"Biomarker-{topic_idx:02d}",
                direction=direction,
                comparator="placebo",
            ),
            statistics=StatisticalEvidence(
                p_operator=ComparisonOperator.EQ,
                p_value=0.004,
                p_value_raw="p = 0.004",
                sample_size=120,
                sample_size_raw="n = 120",
            ),
            evidence_span=EvidenceSpan(
                section=SectionKind.RESULTS,
                start_char=start_char,
                end_char=end_char,
                verbatim_text=verbatim,
            ),
        )
        graph.add_verified_claim(paper, claim)
    return graph


def test_500_claim_graph_scale_and_determinism() -> None:
    graph = _build_500_claim_graph()
    assert len(graph.claims) == 500

    start = time.perf_counter()
    edges_first = graph.build_edges()
    contradictions_first = detect_contradictions(graph)
    experiments_first = propose_falsifiable_experiments(contradictions_first)
    prioritized_first = prioritize_experiments(
        graph, contradictions_first, experiments_first
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"500-claim pipeline took {elapsed:.3f}s (expected < 2.0s)"
    assert len(edges_first) > 0
    assert len(contradictions_first) > 0
    assert len(prioritized_first) > 0

    edges_second = graph.build_edges()
    contradictions_second = detect_contradictions(graph)
    experiments_second = propose_falsifiable_experiments(contradictions_second)
    prioritized_second = prioritize_experiments(
        graph, contradictions_second, experiments_second
    )

    assert edges_first == edges_second
    assert contradictions_first == contradictions_second
    assert prioritized_first == prioritized_second


def test_concurrent_workspace_ingest_threads(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace(
        org_id="org-scale",
        workspace_id="ws-concurrent",
        name="Concurrent Scale Workspace",
    )

    papers = [
        extract_paper_from_layout(spec.paper_id, spec.blocks)
        for spec in BENCHMARK_30_PAPERS[:4]
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                manager.ingest_papers,
                "org-scale",
                "ws-concurrent",
                [paper],
            )
            for paper in papers
        ]
        results = [future.result() for future in futures]

    assert len(results) == 4

    final_graph = manager.load_graph("org-scale", "ws-concurrent")
    persisted_paper_ids = {paper.paper_id for paper in final_graph.papers}
    expected_paper_ids = {paper.paper_id for paper in papers}
    assert persisted_paper_ids == expected_paper_ids

    events = manager.read_audit_log("org-scale", "ws-concurrent")
    ingest_events = [event for event in events if event.action == "ingest"]
    assert len(ingest_events) == 4
    assert all(event.paper_count == 1 for event in ingest_events)
