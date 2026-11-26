import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals import (
    BENCHMARK_30_PAPERS,
    build_adversarial_decoy_claims,
    evaluate_benchmark,
    run_benchmark_audit,
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
from ingest.extractor import MAX_PDF_BYTES
from scigraph.cli import main
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import export_sarif_v210
from scigraph.models import (
    ClaimTuple,
    ClaimVerificationResult,
    ComparisonOperator,
    ContradictionKind,
    EdgeRelation,
    EffectDirection,
    EvidenceEdge,
    EvidenceSpan,
    Paper,
    PaperVerificationReport,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
    VerificationFailureReason,
)
from solver import (
    check_claim_set_satisfiability,
    compute_powered_sample_size,
    compute_regime_delta,
    detect_contradictions,
    extract_regime_parameters,
    parse_standardized_effect_size,
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


def test_pdf_binary_header_size_limit_and_flatedecode_errors() -> None:
    blocks = OPEN_ACCESS_5_PDF_LAYOUTS["arxiv-2401.10101"]
    base_pdf = render_blocks_to_pdf_bytes(blocks)
    binary_pdf = base_pdf.replace(b"%PDF-1.4\n", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n", 1)
    paper = extract_paper_from_pdf_bytes("arxiv-2401.10101", binary_pdf)
    assert paper.doi == "10.48550/arXiv.2401.10101"

    with pytest.raises(ValueError, match="MAX_PDF_BYTES"):
        extract_paper_from_pdf_bytes("oversized", b"%PDF-1.4\n" + b"0" * MAX_PDF_BYTES)

    with pytest.raises(ValueError, match="Invalid PDF header"):
        extract_paper_from_pdf_bytes("bad-magic", b"NOT-A-PDF")

    compressed_pdf = (
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        b"1 0 obj << /Filter /FlateDecode >> stream\nxyz\nendstream"
    )
    with pytest.raises(ValueError, match="/FlateDecode"):
        extract_paper_from_pdf_bytes("compressed", compressed_pdf)


def test_quantitative_regime_delta_and_power_calculator() -> None:
    temp_delta = compute_regime_delta(
        "Aedes aegypti midgut at 28 C",
        "37 C larval thermal heatwave stress",
    )
    assert temp_delta is not None
    assert "+9 C" in temp_delta

    kelvin_delta = compute_regime_delta("reaction at 300 K", "reaction at 310 K")
    assert kelvin_delta is not None
    assert "+10 C" in kelvin_delta

    molar_delta = compute_regime_delta("500 mM NaCl", "1.0 M NaCl")
    assert molar_delta is not None
    assert "+0.5 M" in molar_delta

    cross_delta = compute_regime_delta("65% relative humidity", "130 C oxidative regeneration")
    assert cross_delta is not None
    assert "Cross-dimension regime shift" in cross_delta

    c_rate_params = extract_regime_parameters("2C charge cycling")
    assert len(c_rate_params) == 1
    assert c_rate_params[0].dimension == "c_rate"

    assert parse_standardized_effect_size("d = -0.30") == pytest.approx(0.30)
    assert parse_standardized_effect_size("reduction = 58%") == pytest.approx(1.16)
    assert parse_standardized_effect_size("fold = -2.0x") is None

    def _make_claim(cid: str, n: int, eff: str | None) -> ScientificClaim:
        quote = f"Treatment with X under Y increased Z compared with C (n = {n}, p = 0.01)."
        return ScientificClaim(
            claim_id=cid,
            paper_id="p1",
            doi="10.48550/arXiv.2401.10101",
            claim_tuple=ClaimTuple(
                intervention="X",
                condition="Y",
                outcome="Z",
                direction=EffectDirection.INCREASES,
            ),
            statistics=StatisticalEvidence(
                p_operator=ComparisonOperator.EQ,
                p_value=0.01,
                p_value_raw="p = 0.01",
                sample_size=n,
                sample_size_raw=f"n = {n}",
                effect_size_raw=eff,
            ),
            evidence_span=EvidenceSpan(
                section=SectionKind.RESULTS,
                start_char=0,
                end_char=len(quote),
                verbatim_text=quote,
            ),
        )

    small_d_n = compute_powered_sample_size(
        _make_claim("c1", 20, "d = 0.30"),
        _make_claim("c2", 20, "d = 0.30"),
    )
    large_d_n = compute_powered_sample_size(
        _make_claim("c1", 20, "d = 1.20"),
        _make_claim("c2", 20, "d = 1.20"),
    )
    null_d_n = compute_powered_sample_size(
        _make_claim("c1", 25, None),
        _make_claim("c2", 30, None),
    )
    assert small_d_n > large_d_n
    assert null_d_n == 60


def test_exporters_html_explorer_and_cli_integration(tmp_path: Path) -> None:
    tmp_dir = tmp_path
    bundle = run_benchmark_audit()

    sarif_str = export_sarif_v210(
        bundle.contradictions,
        reports=(
            PaperVerificationReport(
                paper_id="bad-paper",
                doi="10.1000/bad",
                doi_verified=False,
                claim_results=(
                    ClaimVerificationResult(
                        claim_id="bad-c1",
                        paper_id="bad-paper",
                        verified=False,
                        failures=(VerificationFailureReason.DOI_NOT_VERBATIM_IN_SOURCE,),
                    ),
                ),
                verified_claims=(),
                rejected_claim_ids=("bad-c1",),
                elapsed_ms=0.1,
            ),
        ),
    )
    sarif = json.loads(sarif_str)
    assert sarif["version"] == "2.1.0"
    rule_ids = {r["ruleId"] for r in sarif["runs"][0]["results"]}
    assert {"SCIGRAPH-VERIFY-001", "SCIGRAPH-CONTRA-001", "SCIGRAPH-CONTRA-002"} <= rule_ids

    empty_html = render_claim_graph_html(ClaimGraph(), (), (), None)
    assert "empty-state" in empty_html

    xss_graph = ClaimGraph()
    xss_text_a = (
        'Title: <script>alert("xss")</script>\nDOI: 10.48550/arXiv.2401.99998\n'
        'Abstract: Treatment with <script>alert("xss")</script> under 28 C '
        "increased <img src=x> compared with control (n = 40, p = 0.01)."
    )
    xss_text_b = (
        'Title: <script>alert("xss")</script>\nDOI: 10.48550/arXiv.2401.99999\n'
        'Abstract: Treatment with <script>alert("xss")</script> under 28 C '
        "decreased <img src=x> compared with control (n = 40, p = 0.01)."
    )
    for pid, doi, txt in (
        ("xss-1", "10.48550/arXiv.2401.99998", xss_text_a),
        ("xss-2", "10.48550/arXiv.2401.99999", xss_text_b),
    ):
        xss_paper = Paper(
            paper_id=pid,
            doi=doi,
            title='<script>alert("xss")</script>',
            authors=("Alice",),
            publication_year=2024,
            venue="arXiv",
            full_text=txt,
        )
        for c in extract_claims_from_paper(xss_paper):
            xss_graph.add_verified_claim(xss_paper, c)
    xss_graph.build_edges()
    xss_contras = detect_contradictions(xss_graph)
    xss_exps = propose_falsifiable_experiments(xss_contras)
    xss_html = render_claim_graph_html(xss_graph, xss_contras, xss_exps, None)
    assert '<script>alert("xss")</script>' not in xss_html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in xss_html

    assert main(["benchmark"]) == 0
    assert main(["verify", "--paper-id", "unknown-id"]) == 2

    out_sarif = tmp_dir / "out.sarif"
    rc_report = main(
        [
            "report",
            "--format",
            "sarif",
            "--output",
            str(out_sarif),
            "--fail-on-contradictions",
        ]
    )
    assert rc_report == 1
    assert out_sarif.exists()

    out_html = tmp_dir / "studio.html"
    assert main(["report", "--format", "html", "--output", str(out_html)]) == 0
    assert "SciGraph Claim-Graph &amp; Contradiction Studio" in out_html.read_text(encoding="utf-8")

    missing_out = tmp_dir / "missing_dir" / "out.json"
    assert main(["report", "--format", "json", "--output", str(missing_out)]) == 2
