import json
from collections.abc import Sequence
from typing import Any

from graph.claim_graph import ClaimGraph
from scigraph.models import (
    BenchmarkMetrics,
    ContradictionKind,
    ContradictionPair,
    FalsifiableExperiment,
    PaperVerificationReport,
    ScientificClaim,
)

_SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def render_markdown_report(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair],
    experiments: Sequence[FalsifiableExperiment],
    metrics: BenchmarkMetrics | None = None,
) -> str:
    lines: list[str] = [
        "# SciGraph Contradiction & Experiment Briefing",
        "",
        "## Corpus & Verification Summary",
        "",
        f"- **Papers indexed:** {len(graph.papers)}",
        f"- **Verified claims:** {len(graph.claims)}",
        f"- **Evidence edges:** {len(graph.edges)}",
        f"- **Contradictions detected:** {len(contradictions)}",
        f"- **Falsifiable experiments proposed:** {len(experiments)}",
    ]
    if metrics is not None:
        lines.extend(
            [
                f"- **Precision / Recall / F1:** {metrics.precision:.4f} / "
                f"{metrics.recall:.4f} / {metrics.f1_score:.4f}",
                f"- **Fabricated DOIs accepted:** {metrics.fabricated_dois_accepted}",
                f"- **Fabricated p-values accepted:** {metrics.fabricated_p_values_accepted}",
                f"- **Adversarial decoys rejected:** {metrics.adversarial_decoys_rejected}",
            ]
        )

    lines.extend(["", "## Detected Contradictions & Regime Shifts", ""])
    if not contradictions:
        lines.append("_No contradictions detected across verified claims._")
    else:
        lines.extend(
            [
                "| ID | Kind | Claim A | Claim B | UNSAT Constraints | Discriminating Factor |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for pair in contradictions:
            ca = pair.claim_a
            cb = pair.claim_b
            a_desc = (
                f"`{ca.paper_id}` (`{ca.doi}`): {ca.claim_tuple.direction.value} "
                f"({ca.statistics.sample_size_raw}, {ca.statistics.p_value_raw})"
            )
            b_desc = (
                f"`{cb.paper_id}` (`{cb.doi}`): {cb.claim_tuple.direction.value} "
                f"({cb.statistics.sample_size_raw}, {cb.statistics.p_value_raw})"
            )
            unsat_str = "; ".join(f"`{u}`" for u in pair.unsat_constraints)
            lines.append(
                f"| `{pair.contradiction_id}` | `{pair.kind.value}` | {a_desc} | "
                f"{b_desc} | {unsat_str} | {pair.discriminating_factor} |"
            )

    lines.extend(["", "## Proposed Falsifiable Experiments", ""])
    if not experiments:
        lines.append("_No falsifiable experiments proposed._")
    else:
        lines.extend(
            [
                "| ID | Contradiction | Intervention | Primary Outcome | Recommended n | Alpha |",
                "| --- | --- | --- | --- | ---: | ---: |",
            ]
        )
        for exp in experiments:
            lines.append(
                f"| `{exp.experiment_id}` | `{exp.contradiction_id}` | "
                f"{exp.intervention} | {exp.primary_outcome} | "
                f"{exp.recommended_sample_size} | {exp.alpha_threshold:.2f} |"
            )
        lines.append("")
        for exp in experiments:
            arms = " vs ".join(exp.stratified_conditions)
            lines.extend(
                [
                    f"### `{exp.experiment_id}` ({exp.contradiction_id})",
                    f"- **Hypothesis:** {exp.hypothesis}",
                    f"- **Stratified conditions:** {arms}",
                    f"- **Sample size & threshold:** `n = {exp.recommended_sample_size}`, "
                    f"`alpha = {exp.alpha_threshold:.2f}`",
                    f"- **Falsification criterion:** {exp.falsification_criterion}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def export_json_bundle(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair],
    experiments: Sequence[FalsifiableExperiment],
    metrics: BenchmarkMetrics | None = None,
) -> str:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "metrics": metrics.model_dump(mode="json") if metrics is not None else None,
        "papers": [p.model_dump(mode="json") for p in graph.papers],
        "claims": [c.model_dump(mode="json") for c in graph.claims],
        "edges": [e.model_dump(mode="json") for e in graph.edges],
        "contradictions": [c.model_dump(mode="json") for c in contradictions],
        "experiments": [e.model_dump(mode="json") for e in experiments],
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _claim_location(claim: ScientificClaim) -> dict[str, Any]:
    span = claim.evidence_span
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": f"papers/{claim.paper_id}"},
            "region": {
                "charOffset": span.start_char,
                "charLength": span.end_char - span.start_char,
            },
        }
    }


def export_sarif_v210(
    contradictions: Sequence[ContradictionPair],
    reports: Sequence[PaperVerificationReport] = (),
) -> str:
    results: list[dict[str, Any]] = []

    for report in reports:
        claims_by_id = {c.claim_id: c for c in report.verified_claims}
        if not report.doi_verified:
            results.append(
                {
                    "ruleId": "SCIGRAPH-VERIFY-001",
                    "level": "error",
                    "message": {"text": f"Paper DOI verification failed: {report.doi}"},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": f"papers/{report.paper_id}"},
                                "region": {"charOffset": 0, "charLength": 1},
                            }
                        }
                    ],
                }
            )
        for claim_res in report.claim_results:
            if claim_res.verified:
                continue
            reasons = ", ".join(r.value for r in claim_res.failures)
            claim_obj = claims_by_id.get(claim_res.claim_id)
            loc = (
                _claim_location(claim_obj)
                if claim_obj is not None
                else {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f"papers/{report.paper_id}"},
                        "region": {"charOffset": 0, "charLength": 1},
                    }
                }
            )
            results.append(
                {
                    "ruleId": "SCIGRAPH-VERIFY-001",
                    "level": "error",
                    "message": {
                        "text": (
                            f"Claim {claim_res.claim_id} failed verbatim verification: {reasons}"
                        )
                    },
                    "locations": [loc],
                }
            )

    for pair in contradictions:
        if pair.kind == ContradictionKind.DIRECT_DIRECTION_CONFLICT:
            rule_id = "SCIGRAPH-CONTRA-001"
            level = "warning"
        else:
            rule_id = "SCIGRAPH-CONTRA-002"
            level = "note"
        results.append(
            {
                "ruleId": rule_id,
                "level": level,
                "message": {
                    "text": (
                        f"{pair.contradiction_id} ({pair.kind.value}): {pair.discriminating_factor}"
                    )
                },
                "locations": [_claim_location(pair.claim_a)],
                "relatedLocations": [_claim_location(pair.claim_b)],
                "properties": {
                    "unsat_constraints": list(pair.unsat_constraints),
                },
            }
        )

    sarif_doc: dict[str, Any] = {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "SciGraph",
                        "informationUri": "https://github.com/scigraph/scigraph",
                        "rules": [
                            {
                                "id": "SCIGRAPH-VERIFY-001",
                                "name": "VerbatimVerificationFailure",
                                "shortDescription": {
                                    "text": (
                                        "DOI, span, p-value, or sample size "
                                        "failed verbatim verification."
                                    )
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                            {
                                "id": "SCIGRAPH-CONTRA-001",
                                "name": "DirectDirectionConflict",
                                "shortDescription": {
                                    "text": (
                                        "Direct opposing claim directions "
                                        "under identical conditions."
                                    )
                                },
                                "defaultConfiguration": {"level": "warning"},
                            },
                            {
                                "id": "SCIGRAPH-CONTRA-002",
                                "name": "ConditionOrPowerDivergence",
                                "shortDescription": {
                                    "text": (
                                        "Null-vs-significant or condition-dependent "
                                        "divergence across claims."
                                    )
                                },
                                "defaultConfiguration": {"level": "note"},
                            },
                        ],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif_doc, sort_keys=True, indent=2) + "\n"
