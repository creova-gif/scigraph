from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph.claim_graph import ClaimGraph
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    ContradictionKind,
    ContradictionPair,
    EffectDirection,
    EvidenceSpan,
    FalsifiableExperiment,
    Paper,
    PaperSection,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)
from solver import (
    CostTier,
    PrioritizedExperiment,
    prioritize_experiments,
)


def _make_paper_and_claim(
    *,
    paper_id: str,
    doi: str,
    claim_id: str,
    intervention: str = "CompoundX",
    condition: str = "Normoxia",
    outcome: str = "Viability",
    direction: EffectDirection = EffectDirection.INCREASES,
    p_value_raw: str = "p = 0.02",
    p_value: float = 0.02,
    sample_size_raw: str = "n = 100",
    sample_size: int = 100,
    effect_size_raw: str | None = "d = 0.50",
) -> tuple[Paper, ScientificClaim]:
    statement = (
        f"Under {condition}, {intervention} affects {outcome} "
        f"({p_value_raw}, {sample_size_raw})."
    )
    full_text = f"DOI: {doi}\nResults: {statement}"
    start_char = full_text.index(statement)
    end_char = start_char + len(statement)
    results_start = full_text.index("Results:")

    paper = Paper(
        paper_id=paper_id,
        doi=doi,
        title=f"Study {paper_id}",
        authors=("Alice Smith",),
        publication_year=2025,
        venue="Journal of Testing",
        full_text=full_text,
        sections=(
            PaperSection(
                kind=SectionKind.RESULTS,
                heading="Results",
                text=full_text[results_start:],
                start_char=results_start,
                end_char=len(full_text),
            ),
        ),
    )
    claim = ScientificClaim(
        claim_id=claim_id,
        paper_id=paper_id,
        doi=doi,
        claim_tuple=ClaimTuple(
            intervention=intervention,
            condition=condition,
            outcome=outcome,
            direction=direction,
        ),
        statistics=StatisticalEvidence(
            p_operator=ComparisonOperator.EQ,
            p_value=p_value,
            p_value_raw=p_value_raw,
            sample_size=sample_size,
            sample_size_raw=sample_size_raw,
            effect_size_raw=effect_size_raw,
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=start_char,
            end_char=end_char,
            verbatim_text=statement,
        ),
    )
    return paper, claim


def _make_contradiction(
    *,
    contradiction_id: str,
    claim_a: ScientificClaim,
    claim_b: ScientificClaim,
    kind: ContradictionKind,
) -> ContradictionPair:
    return ContradictionPair(
        contradiction_id=contradiction_id,
        claim_a=claim_a,
        claim_b=claim_b,
        kind=kind,
        unsat_constraints=(f"conflict({claim_a.claim_id}, {claim_b.claim_id})",),
        discriminating_factor="Test conflict",
    )


def _make_experiment(
    *,
    experiment_id: str,
    contradiction_id: str,
    recommended_sample_size: int,
) -> FalsifiableExperiment:
    return FalsifiableExperiment(
        experiment_id=experiment_id,
        contradiction_id=contradiction_id,
        hypothesis=f"Test hypothesis for {contradiction_id}",
        intervention="CompoundX",
        stratified_conditions=("Arm A", "Arm B"),
        primary_outcome="Viability",
        recommended_sample_size=recommended_sample_size,
        alpha_threshold=0.01,
        falsification_criterion="p >= 0.01",
    )


def test_empty_inputs_return_empty_tuple() -> None:
    graph = ClaimGraph()
    assert prioritize_experiments(graph, (), ()) == ()

    p1, c1 = _make_paper_and_claim(paper_id="p1", doi="10.1000/a.1", claim_id="c1")
    p2, c2 = _make_paper_and_claim(
        paper_id="p2",
        doi="10.1000/a.2",
        claim_id="c2",
        direction=EffectDirection.DECREASES,
    )
    graph.add_verified_claim(p1, c1)
    graph.add_verified_claim(p2, c2)
    contra = _make_contradiction(
        contradiction_id="contra-0001",
        claim_a=c1,
        claim_b=c2,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
    )
    assert prioritize_experiments(graph, (contra,), ()) == ()


def test_ranking_order_across_contradiction_kinds() -> None:
    graph = ClaimGraph()
    # Identical statistics across all claims -> identical evidence_strength:
    # n=100 (0.035) + p=0.02 (0.15) + effect_size (0.15) = 0.335
    pairs: list[ContradictionPair] = []
    exps: list[FalsifiableExperiment] = []

    kinds = (
        ("cond", ContradictionKind.CONDITION_DEPENDENT_DIVERGENCE),
        ("null", ContradictionKind.NULL_VS_SIGNIFICANT_CONFLICT),
        ("direct", ContradictionKind.DIRECT_DIRECTION_CONFLICT),
    )
    for idx, (label, kind) in enumerate(kinds, start=1):
        pa, ca = _make_paper_and_claim(
            paper_id=f"pa-{idx}",
            doi=f"10.1000/k.{idx}a",
            claim_id=f"ca-{idx}",
            direction=EffectDirection.INCREASES,
        )
        pb, cb = _make_paper_and_claim(
            paper_id=f"pb-{idx}",
            doi=f"10.1000/k.{idx}b",
            claim_id=f"cb-{idx}",
            direction=EffectDirection.DECREASES,
        )
        graph.add_verified_claim(pa, ca)
        graph.add_verified_claim(pb, cb)
        contra_id = f"contra-{label}"
        pairs.append(
            _make_contradiction(
                contradiction_id=contra_id,
                claim_a=ca,
                claim_b=cb,
                kind=kind,
            )
        )
        exps.append(
            _make_experiment(
                experiment_id=f"exp-{label}",
                contradiction_id=contra_id,
                recommended_sample_size=60,
            )
        )

    ranked = prioritize_experiments(graph, pairs, exps)
    assert [item.experiment_id for item in ranked] == [
        "exp-direct",
        "exp-null",
        "exp-cond",
    ]
    assert [item.rank for item in ranked] == [1, 2, 3]
    # avg_evidence = 0.335 -> 0.335 * 0.35 = 0.11725; feasibility (n=60 <= 80) = 0.20
    assert ranked[0].priority_score == round(0.45 + 0.335 * 0.35 + 0.20, 4)
    assert ranked[1].priority_score == round(0.35 + 0.335 * 0.35 + 0.20, 4)
    assert ranked[2].priority_score == round(0.25 + 0.335 * 0.35 + 0.20, 4)


def test_cost_tiers_and_boundaries() -> None:
    graph = ClaimGraph()
    pa, ca = _make_paper_and_claim(paper_id="pa", doi="10.1000/ct.1", claim_id="ca")
    pb, cb = _make_paper_and_claim(
        paper_id="pb",
        doi="10.1000/ct.2",
        claim_id="cb",
        direction=EffectDirection.DECREASES,
    )
    graph.add_verified_claim(pa, ca)
    graph.add_verified_claim(pb, cb)
    contra = _make_contradiction(
        contradiction_id="contra-1",
        claim_a=ca,
        claim_b=cb,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
    )

    sample_sizes_and_tiers: list[tuple[int, CostTier]] = [
        (80, "LOW"),
        (81, "MEDIUM"),
        (300, "MEDIUM"),
        (301, "HIGH"),
    ]
    exps = [
        _make_experiment(
            experiment_id=f"exp-{n}",
            contradiction_id="contra-1",
            recommended_sample_size=n,
        )
        for n, _ in sample_sizes_and_tiers
    ]

    ranked = prioritize_experiments(graph, (contra,), exps)
    by_id = {item.experiment_id: item for item in ranked}
    for n, expected_tier in sample_sizes_and_tiers:
        item = by_id[f"exp-{n}"]
        assert item.cost_tier == expected_tier
        assert item.estimated_participants == n

    # Check ordering: n=80 (LOW, +0.20), then n=81 (MEDIUM, +0.10),
    # then n=300 (MEDIUM, +0.10, tie-broken by smaller n), then n=301 (HIGH, +0.02)
    assert [item.experiment_id for item in ranked] == [
        "exp-80",
        "exp-81",
        "exp-300",
        "exp-301",
    ]


def test_evidence_strength_weighting_determines_rank() -> None:
    graph = ClaimGraph()

    # Strong pair: n=1000 (0.35) + p=0.001 (0.25) + effect_size (0.15) + 1 support (0.10) = 0.85
    p_s1, c_s1 = _make_paper_and_claim(
        paper_id="ps1",
        doi="10.1000/s.1",
        claim_id="cs1",
        p_value_raw="p = 0.001",
        p_value=0.001,
        sample_size_raw="n = 1000",
        sample_size=1000,
    )
    p_s2, c_s2 = _make_paper_and_claim(
        paper_id="ps2",
        doi="10.1000/s.2",
        claim_id="cs2",
        direction=EffectDirection.DECREASES,
        p_value_raw="p = 0.001",
        p_value=0.001,
        sample_size_raw="n = 1000",
        sample_size=1000,
    )
    p_rep, c_rep = _make_paper_and_claim(
        paper_id="prep",
        doi="10.1000/s.3",
        claim_id="crep",
        p_value_raw="p = 0.001",
        p_value=0.001,
        sample_size_raw="n = 1000",
        sample_size=1000,
    )
    graph.add_verified_claim(p_s1, c_s1)
    graph.add_verified_claim(p_s2, c_s2)
    graph.add_verified_claim(p_rep, c_rep)

    # Weak pair: n=20 (0.007) + p=0.20 (0.0) + no effect_size (0.0) = 0.007
    p_w1, c_w1 = _make_paper_and_claim(
        paper_id="pw1",
        doi="10.1000/w.1",
        claim_id="cw1",
        p_value_raw="p = 0.20",
        p_value=0.20,
        sample_size_raw="n = 20",
        sample_size=20,
        effect_size_raw=None,
    )
    p_w2, c_w2 = _make_paper_and_claim(
        paper_id="pw2",
        doi="10.1000/w.2",
        claim_id="cw2",
        direction=EffectDirection.DECREASES,
        p_value_raw="p = 0.20",
        p_value=0.20,
        sample_size_raw="n = 20",
        sample_size=20,
        effect_size_raw=None,
    )
    graph.add_verified_claim(p_w1, c_w1)
    graph.add_verified_claim(p_w2, c_w2)

    contra_strong = _make_contradiction(
        contradiction_id="contra-strong",
        claim_a=c_s1,
        claim_b=c_s2,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
    )
    contra_weak = _make_contradiction(
        contradiction_id="contra-weak",
        claim_a=c_w1,
        claim_b=c_w2,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
    )

    exp_weak = _make_experiment(
        experiment_id="exp-weak",
        contradiction_id="contra-weak",
        recommended_sample_size=120,
    )
    exp_strong = _make_experiment(
        experiment_id="exp-strong",
        contradiction_id="contra-strong",
        recommended_sample_size=120,
    )

    ranked = prioritize_experiments(
        graph,
        (contra_weak, contra_strong),
        (exp_weak, exp_strong),
    )
    assert [item.experiment_id for item in ranked] == ["exp-strong", "exp-weak"]
    assert ranked[0].priority_score > ranked[1].priority_score


def test_unknown_contradiction_id_raises_and_model_is_frozen() -> None:
    graph = ClaimGraph()
    exp = _make_experiment(
        experiment_id="exp-missing",
        contradiction_id="contra-does-not-exist",
        recommended_sample_size=50,
    )
    with pytest.raises(ValueError, match="unknown contradiction_id"):
        prioritize_experiments(graph, (), (exp,))

    model = PrioritizedExperiment(
        rank=1,
        experiment_id="exp-1",
        contradiction_id="contra-1",
        priority_score=0.75,
        cost_tier="LOW",
        estimated_participants=50,
        reason="test",
    )
    with pytest.raises(ValidationError):
        model.rank = 2
