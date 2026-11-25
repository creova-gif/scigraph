import pytest
from pydantic import ValidationError

from evals import (
    BENCHMARK_30_PAPERS,
    build_adversarial_decoy_claims,
    evaluate_benchmark,
)
from graph import ClaimGraph
from ingest import (
    OPEN_ACCESS_5_PDF_LAYOUTS,
    extract_claims_from_paper,
    extract_paper_from_layout,
    extract_paper_from_pdf_bytes,
    render_blocks_to_pdf_bytes,
    verify_claim_verbatim,
    verify_paper_claims,
)
from scigraph.models import (
    ContradictionKind,
    EdgeRelation,
    EvidenceEdge,
    EvidenceSpan,
    Paper,
    SectionKind,
    VerificationFailureReason,
)
from solver import (
    check_claim_set_satisfiability,
    detect_contradictions,
    propose_falsifiable_experiments,
)


def test_pydantic_models_reject_invalid_states() -> None:
    with pytest.raises(ValidationError):
        Paper(
            paper_id="p1",
            doi="not-a-valid-doi",
            title="Invalid DOI Paper",
            authors=("Alice",),
            publication_year=2024,
            venue="arXiv",
            full_text="Title: Invalid DOI Paper",
        )

    with pytest.raises(ValidationError):
        EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=10,
            end_char=15,
            verbatim_text="length mismatch",
        )

    with pytest.raises(ValidationError):
        EvidenceEdge(
            edge_id="e1",
            source_claim_id="c1",
            target_claim_id="c1",
            relation=EdgeRelation.SUPPORTS,
            rationale="Self-loop should fail",
            shared_intervention="metformin",
            shared_outcome="gluconeogenesis",
        )


def test_layout_aware_pdf_extraction_on_5_open_access_papers() -> None:
    assert len(OPEN_ACCESS_5_PDF_LAYOUTS) == 5

    for paper_id, blocks in OPEN_ACCESS_5_PDF_LAYOUTS.items():
        pdf_bytes = render_blocks_to_pdf_bytes(blocks)
        paper = extract_paper_from_pdf_bytes(paper_id, pdf_bytes)

        section_kinds = [s.kind for s in paper.sections]
        assert section_kinds == [
            SectionKind.ABSTRACT,
            SectionKind.METHODS,
            SectionKind.RESULTS,
        ]

        claims = extract_claims_from_paper(paper)
        assert len(claims) == 2

        report = verify_paper_claims(paper, claims)
        assert report.doi_verified is True
        assert len(report.verified_claims) == 2
        assert len(report.rejected_claim_ids) == 0


def test_deterministic_verifier_rejects_fabricated_doi_p_value_and_sample_size() -> None:
    blocks = OPEN_ACCESS_5_PDF_LAYOUTS["arxiv-2401.10101"]
    paper = extract_paper_from_layout("arxiv-2401.10101", blocks)
    decoys = build_adversarial_decoy_claims(paper)

    res_doi = verify_claim_verbatim(paper, decoys[0])
    assert res_doi.verified is False
    assert VerificationFailureReason.DOI_NOT_VERBATIM_IN_SOURCE in res_doi.failures

    res_p_missing = verify_claim_verbatim(paper, decoys[1])
    assert res_p_missing.verified is False
    assert VerificationFailureReason.P_VALUE_NOT_VERBATIM in res_p_missing.failures

    res_p_lie = verify_claim_verbatim(paper, decoys[2])
    assert res_p_lie.verified is False
    assert VerificationFailureReason.P_VALUE_NUMERIC_MISMATCH in res_p_lie.failures

    res_n_missing = verify_claim_verbatim(paper, decoys[3])
    assert res_n_missing.verified is False
    assert VerificationFailureReason.SAMPLE_SIZE_NOT_VERBATIM in res_n_missing.failures

    res_span = verify_claim_verbatim(paper, decoys[4])
    assert res_span.verified is False
    assert VerificationFailureReason.SPAN_TEXT_MISMATCH in res_span.failures

    graph = ClaimGraph()
    with pytest.raises(ValueError, match="failed verbatim verification"):
        graph.add_verified_claim(paper, decoys[1])


def test_claim_graph_contradiction_solver_and_experiment_synthesis() -> None:
    graph = ClaimGraph()
    for spec in BENCHMARK_30_PAPERS[:10]:
        paper = extract_paper_from_layout(spec.paper_id, spec.blocks)
        for claim in extract_claims_from_paper(paper):
            graph.add_verified_claim(paper, claim)

    edges = graph.build_edges()
    relations = {e.relation for e in edges}
    assert EdgeRelation.CONTRADICTS in relations
    assert EdgeRelation.QUALIFIES in relations

    is_sat, unsat_core = check_claim_set_satisfiability(graph.claims)
    assert is_sat is False
    assert len(unsat_core) >= 2

    contradictions = detect_contradictions(graph)
    kinds = {c.kind for c in contradictions}
    assert ContradictionKind.DIRECT_DIRECTION_CONFLICT in kinds
    assert ContradictionKind.NULL_VS_SIGNIFICANT_CONFLICT in kinds
    assert ContradictionKind.CONDITION_DEPENDENT_DIVERGENCE in kinds

    experiments = propose_falsifiable_experiments(contradictions)
    assert len(experiments) == len(contradictions)
    for exp in experiments:
        assert exp.recommended_sample_size >= 40
        assert exp.alpha_threshold == 0.01
        assert "Falsified if" in exp.falsification_criterion


def test_30_paper_benchmark_exceeds_acceptance_thresholds() -> None:
    metrics = evaluate_benchmark()
    assert metrics.total_papers == 30
    assert metrics.f1_score >= 0.85
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.fabricated_dois_accepted == 0
    assert metrics.fabricated_p_values_accepted == 0
    assert metrics.adversarial_decoys_rejected == 150
    assert metrics.contradictions_detected >= 6
    assert metrics.experiments_proposed == metrics.contradictions_detected
