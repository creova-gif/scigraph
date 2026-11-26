import json
import time

from graph.claim_graph import ClaimGraph
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import (
    export_json_bundle,
    export_sarif_v210,
    render_markdown_report,
)
from scigraph.models import (
    BenchmarkMetrics,
    ClaimTuple,
    ClaimVerificationResult,
    ComparisonOperator,
    ContradictionKind,
    ContradictionPair,
    EffectDirection,
    EvidenceSpan,
    FalsifiableExperiment,
    Paper,
    PaperVerificationReport,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
    VerificationFailureReason,
)


def _build_500_claim_fixture() -> tuple[
    ClaimGraph,
    tuple[ContradictionPair, ...],
    tuple[FalsifiableExperiment, ...],
    tuple[PaperVerificationReport, ...],
    BenchmarkMetrics,
]:
    graph = ClaimGraph()
    claims: list[ScientificClaim] = []
    reports: list[PaperVerificationReport] = []

    for idx in range(500):
        paper_id = f"paper-{idx:04d}"
        doi = f"10.48550/arXiv.2401.{10000 + idx}"
        pair_idx = idx // 2
        direction = (
            EffectDirection.INCREASES if idx % 2 == 0 else EffectDirection.DECREASES
        )
        condition = (
            '28 C <script>alert("xss")</script>' if idx == 0 else f"regime-{pair_idx % 10}"
        )
        quote = (
            f"Treatment with drug-{pair_idx} under {condition} "
            f"{direction.value} biomarker-{pair_idx} (n = 40, p = 0.01)."
        )
        full_text = f"Title: Paper {idx}\nDOI: {doi}\nResults: {quote}"
        start_char = full_text.index(quote)
        end_char = start_char + len(quote)

        paper = Paper(
            paper_id=paper_id,
            doi=doi,
            title=f"Paper {idx}",
            authors=("Alice",),
            publication_year=2024,
            venue="arXiv",
            full_text=full_text,
        )
        claim = ScientificClaim(
            claim_id=f"claim-{idx:04d}",
            paper_id=paper_id,
            doi=doi,
            claim_tuple=ClaimTuple(
                intervention=f"drug-{pair_idx}",
                condition=condition,
                outcome=f"biomarker-{pair_idx}",
                direction=direction,
            ),
            statistics=StatisticalEvidence(
                sample_size=40,
                sample_size_raw="n = 40",
                p_value=0.01,
                p_operator=ComparisonOperator.EQ,
                p_value_raw="p = 0.01",
                effect_size_raw="d = 0.50",
            ),
            evidence_span=EvidenceSpan(
                section=SectionKind.RESULTS,
                start_char=start_char,
                end_char=end_char,
                verbatim_text=quote,
            ),
        )
        res = graph.add_verified_claim(paper, claim)
        claims.append(claim)
        reports.append(
            PaperVerificationReport(
                paper_id=paper_id,
                doi=doi,
                doi_verified=True,
                claim_results=(res,),
                verified_claims=(claim,),
                rejected_claim_ids=(),
                elapsed_ms=0.1,
            )
        )

    # Add one failing report to exercise SARIF verification failure mapping as well.
    reports.append(
        PaperVerificationReport(
            paper_id="paper-fail",
            doi="10.48550/arXiv.2401.99999",
            doi_verified=False,
            claim_results=(
                ClaimVerificationResult(
                    claim_id="claim-fail",
                    paper_id="paper-fail",
                    verified=False,
                    failures=(VerificationFailureReason.DOI_NOT_VERBATIM_IN_SOURCE,),
                ),
            ),
            verified_claims=(),
            rejected_claim_ids=("claim-fail",),
            elapsed_ms=0.1,
        )
    )

    graph.build_edges()

    contradictions: list[ContradictionPair] = []
    experiments: list[FalsifiableExperiment] = []
    for pair_idx in range(250):
        ca = claims[pair_idx * 2]
        cb = claims[pair_idx * 2 + 1]
        contra_id = f"contra-{pair_idx:04d}"
        contradictions.append(
            ContradictionPair(
                contradiction_id=contra_id,
                kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
                claim_a=ca,
                claim_b=cb,
                unsat_constraints=(
                    f"dir({ca.claim_id})=INCREASES",
                    f"dir({cb.claim_id})=DECREASES",
                ),
                discriminating_factor=f"Opposing effects for drug-{pair_idx}",
            )
        )
        experiments.append(
            FalsifiableExperiment(
                experiment_id=f"exp-{pair_idx:04d}",
                contradiction_id=contra_id,
                hypothesis=f"Dose-dependent reversal for drug-{pair_idx}",
                intervention=f"drug-{pair_idx}",
                stratified_conditions=(
                    ca.claim_tuple.condition,
                    cb.claim_tuple.condition,
                ),
                primary_outcome=f"biomarker-{pair_idx}",
                recommended_sample_size=80,
                alpha_threshold=0.05,
                falsification_criterion="Null hypothesis rejected at p < 0.05",
            )
        )

    metrics = BenchmarkMetrics(
        total_papers=500,
        true_positives=500,
        false_positives=0,
        false_negatives=0,
        precision=1.0,
        recall=1.0,
        f1_score=1.0,
        fabricated_dois_accepted=0,
        fabricated_p_values_accepted=0,
        adversarial_decoys_rejected=0,
        contradictions_detected=250,
        experiments_proposed=250,
        elapsed_ms=10.0,
    )
    return graph, tuple(contradictions), tuple(experiments), tuple(reports), metrics


def test_exporters_and_explorer_500_claim_scale() -> None:
    graph, contradictions, experiments, reports, metrics = _build_500_claim_fixture()
    assert len(graph.papers) == 500
    assert len(graph.claims) == 500
    assert len(graph.edges) == 250

    t0 = time.perf_counter()
    html_out = render_claim_graph_html(graph, contradictions, experiments, metrics)
    html_elapsed = time.perf_counter() - t0
    assert html_elapsed < 2.0
    assert '<script>alert("xss")</script>' not in html_out
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html_out
    assert html_out.count('class="card contra-card"') == 250
    assert html_out.count('class="edge-row"') == 250
    assert (
        '<div class="kpi-val mono">500</div><div class="kpi-lbl">Papers Audited</div>'
        in html_out
    )
    assert (
        '<div class="kpi-val mono">500</div><div class="kpi-lbl">Verified Claims</div>'
        in html_out
    )
    assert (
        '<div class="kpi-val mono">250</div><div class="kpi-lbl">Evidence Edges</div>'
        in html_out
    )

    t1 = time.perf_counter()
    sarif_out = export_sarif_v210(contradictions, reports)
    sarif_elapsed = time.perf_counter() - t1
    assert sarif_elapsed < 2.0
    sarif_doc = json.loads(sarif_out)
    assert sarif_doc["version"] == "2.1.0"
    # 250 contradictions + 2 failures from paper-fail (DOI + claim-fail)
    assert len(sarif_doc["runs"][0]["results"]) == 252

    t2 = time.perf_counter()
    bundle_out = export_json_bundle(graph, contradictions, experiments, metrics)
    bundle_elapsed = time.perf_counter() - t2
    assert bundle_elapsed < 2.0
    bundle_doc = json.loads(bundle_out)
    assert len(bundle_doc["papers"]) == 500
    assert len(bundle_doc["claims"]) == 500
    assert len(bundle_doc["edges"]) == 250
    assert len(bundle_doc["contradictions"]) == 250
    assert len(bundle_doc["experiments"]) == 250

    t3 = time.perf_counter()
    md_out = render_markdown_report(graph, contradictions, experiments, metrics)
    md_elapsed = time.perf_counter() - t3
    assert md_elapsed < 2.0
    assert "- **Papers indexed:** 500" in md_out
    assert "- **Verified claims:** 500" in md_out
    assert "- **Evidence edges:** 250" in md_out
    assert "- **Contradictions detected:** 250" in md_out
    assert "- **Falsifiable experiments proposed:** 250" in md_out
