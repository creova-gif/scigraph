from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph import (
    ClaimEvidenceScore,
    ClaimGraph,
    TopicConsensus,
    compute_topic_consensus,
    score_claim_evidence,
)
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    Paper,
    PaperSection,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)


def _make_paper_and_claim(
    *,
    paper_id: str,
    doi: str,
    claim_id: str,
    intervention: str,
    condition: str,
    outcome: str,
    direction: EffectDirection,
    p_value_raw: str,
    p_value: float,
    sample_size_raw: str,
    sample_size: int,
    effect_size_raw: str | None = "d = 0.50",
) -> tuple[Paper, ScientificClaim]:
    statement = (
        f"Under {condition}, {intervention} affects {outcome} ({p_value_raw}, {sample_size_raw})."
    )
    full_text = f"DOI: {doi}\nResults: {statement}"
    start_char = full_text.index(statement)
    end_char = start_char + len(statement)
    results_start = full_text.index("Results:")

    paper = Paper(
        paper_id=paper_id,
        doi=doi,
        title=f"Study {paper_id}",
        authors=("Alice Smith", "Bob Jones"),
        publication_year=2025,
        venue="Journal of Reproducible Science",
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


def test_score_claim_evidence_tiers_and_replication_cap() -> None:
    graph = ClaimGraph()

    # HIGH: n=1000 (0.35) + p<0.01 (0.25) + effect_size (0.15) = 0.75,
    # plus 3 replications (capped at +0.25) = 1.00
    for idx in range(1, 5):
        p, c = _make_paper_and_claim(
            paper_id=f"p-high-{idx}",
            doi=f"10.1000/high.{idx}",
            claim_id=f"c-high-{idx}",
            intervention="Metformin",
            condition="Type 2 Diabetes",
            outcome="HbA1c",
            direction=EffectDirection.DECREASES,
            p_value_raw="p = 0.002",
            p_value=0.002,
            sample_size_raw="n = 1000",
            sample_size=1000,
            effect_size_raw="d = 0.65",
        )
        graph.add_verified_claim(p, c)

    # MODERATE: n=400 (0.14) + p<0.05 (0.15) + effect_size (0.15) = 0.44
    p_mod, c_mod = _make_paper_and_claim(
        paper_id="p-mod-1",
        doi="10.1000/mod.1",
        claim_id="c-mod-1",
        intervention="Caffeine",
        condition="Healthy Adults",
        outcome="Alertness",
        direction=EffectDirection.INCREASES,
        p_value_raw="p = 0.030",
        p_value=0.030,
        sample_size_raw="n = 400",
        sample_size=400,
        effect_size_raw="d = 0.30",
    )
    graph.add_verified_claim(p_mod, c_mod)

    # PRELIMINARY: n=20 (0.007) + p>=0.05 (0.0) + no effect_size (0.0) = 0.007
    p_pre, c_pre = _make_paper_and_claim(
        paper_id="p-pre-1",
        doi="10.1000/pre.1",
        claim_id="c-pre-1",
        intervention="Zinc",
        condition="Common Cold",
        outcome="Symptom Duration",
        direction=EffectDirection.NO_EFFECT,
        p_value_raw="p = 0.240",
        p_value=0.240,
        sample_size_raw="n = 20",
        sample_size=20,
        effect_size_raw=None,
    )
    graph.add_verified_claim(p_pre, c_pre)

    graph.build_edges()
    scores = score_claim_evidence(graph)

    high_score = scores["c-high-1"]
    assert isinstance(high_score, ClaimEvidenceScore)
    assert high_score.replication_count == 3
    assert high_score.contradiction_count == 0
    assert high_score.evidence_strength == 1.0
    assert high_score.tier == "HIGH"
    assert high_score.has_effect_size is True

    mod_score = scores["c-mod-1"]
    assert mod_score.evidence_strength == 0.44
    assert mod_score.tier == "MODERATE"

    pre_score = scores["c-pre-1"]
    assert pre_score.evidence_strength == 0.007
    assert pre_score.tier == "PRELIMINARY"
    assert pre_score.has_effect_size is False

    # Determinism check
    assert score_claim_evidence(graph) == scores


def test_score_claim_evidence_contradiction_penalty_and_clamping() -> None:
    graph = ClaimGraph()

    # Claim A: n=500 (0.175) + p<0.01 (0.25) + effect_size (0.15) = 0.575 base
    p1, c1 = _make_paper_and_claim(
        paper_id="p-1",
        doi="10.1000/contra.1",
        claim_id="c-1",
        intervention="Vitamin D",
        condition="Elderly",
        outcome="Bone Density",
        direction=EffectDirection.INCREASES,
        p_value_raw="p = 0.005",
        p_value=0.005,
        sample_size_raw="n = 500",
        sample_size=500,
    )
    graph.add_verified_claim(p1, c1)

    # 2 contradicting claims under identical condition -> -0.30 penalty to c-1 -> 0.275
    for idx in (2, 3):
        p_opp, c_opp = _make_paper_and_claim(
            paper_id=f"p-{idx}",
            doi=f"10.1000/contra.{idx}",
            claim_id=f"c-{idx}",
            intervention="Vitamin D",
            condition="Elderly",
            outcome="Bone Density",
            direction=EffectDirection.DECREASES,
            p_value_raw="p = 0.080",
            p_value=0.080,
            sample_size_raw="n = 40",
            sample_size=40,
            effect_size_raw=None,
        )
        graph.add_verified_claim(p_opp, c_opp)

    graph.build_edges()
    scores = score_claim_evidence(graph)

    c1_score = scores["c-1"]
    assert c1_score.contradiction_count == 2
    assert c1_score.replication_count == 0
    assert c1_score.evidence_strength == 0.275
    assert c1_score.tier == "PRELIMINARY"

    # c-2 has base 0.014 + 0.10 (1 replication) - 0.15 (1 contradiction) -> clamped to 0.0
    c2_score = scores["c-2"]
    assert c2_score.contradiction_count == 1
    assert c2_score.replication_count == 1
    assert c2_score.evidence_strength == 0.0
    assert c2_score.tier == "PRELIMINARY"


def test_compute_topic_consensus_uncontested_contested_and_tie() -> None:
    graph = ClaimGraph()

    # Topic 1 (uncontested INCREASES, mixed casing/whitespace)
    for idx, intervention in enumerate((" Omega-3 ", "omega-3"), start=1):
        p, c = _make_paper_and_claim(
            paper_id=f"p-t1-{idx}",
            doi=f"10.1000/t1.{idx}",
            claim_id=f"c-t1-{idx}",
            intervention=intervention,
            condition="Adults",
            outcome="HDL Cholesterol",
            direction=EffectDirection.INCREASES,
            p_value_raw="p = 0.003",
            p_value=0.003,
            sample_size_raw="n = 300",
            sample_size=300,
        )
        graph.add_verified_claim(p, c)

    # Topic 2 (contested with majority DECREASES: 2 DECREASES vs 1 INCREASES)
    for idx in (1, 2):
        p, c = _make_paper_and_claim(
            paper_id=f"p-t2-dec-{idx}",
            doi=f"10.1000/t2.dec.{idx}",
            claim_id=f"c-t2-dec-{idx}",
            intervention="Statin",
            condition="Hyperlipidemia",
            outcome="LDL Cholesterol",
            direction=EffectDirection.DECREASES,
            p_value_raw="p = 0.001",
            p_value=0.001,
            sample_size_raw="n = 800",
            sample_size=800,
        )
        graph.add_verified_claim(p, c)

    p_inc, c_inc = _make_paper_and_claim(
        paper_id="p-t2-inc-1",
        doi="10.1000/t2.inc.1",
        claim_id="c-t2-inc-1",
        intervention="Statin",
        condition="Hyperlipidemia",
        outcome="LDL Cholesterol",
        direction=EffectDirection.INCREASES,
        p_value_raw="p = 0.040",
        p_value=0.040,
        sample_size_raw="n = 100",
        sample_size=100,
    )
    graph.add_verified_claim(p_inc, c_inc)

    # Topic 3 (contested tie: 1 INCREASES vs 1 DECREASES)
    for idx, direction in enumerate(
        (EffectDirection.INCREASES, EffectDirection.DECREASES), start=1
    ):
        p, c = _make_paper_and_claim(
            paper_id=f"p-t3-{idx}",
            doi=f"10.1000/t3.{idx}",
            claim_id=f"c-t3-{idx}",
            intervention="Aspirin",
            condition="Primary Prevention",
            outcome="Cardiovascular Events",
            direction=direction,
            p_value_raw="p = 0.020",
            p_value=0.020,
            sample_size_raw="n = 250",
            sample_size=250,
        )
        graph.add_verified_claim(p, c)

    graph.build_edges()
    consensus_tuple = compute_topic_consensus(graph)
    by_topic = {(t.intervention, t.outcome): t for t in consensus_tuple}

    t1 = by_topic[("omega-3", "hdl cholesterol")]
    assert isinstance(t1, TopicConsensus)
    assert t1.supporting_claims == 2
    assert t1.contradicting_claims == 0
    assert t1.neutral_claims == 0
    assert t1.consensus_direction == EffectDirection.INCREASES
    assert t1.consensus_score == 1.0
    assert t1.contested is False

    t2 = by_topic[("statin", "ldl cholesterol")]
    assert t2.supporting_claims == 2
    assert t2.contradicting_claims == 1
    assert t2.neutral_claims == 0
    assert t2.consensus_direction == EffectDirection.DECREASES
    assert 0.5 < t2.consensus_score < 1.0
    assert t2.contested is True

    t3 = by_topic[("aspirin", "cardiovascular events")]
    assert t3.supporting_claims == 1
    assert t3.contradicting_claims == 1
    assert t3.neutral_claims == 0
    assert t3.consensus_direction is None
    assert t3.consensus_score == 0.0
    assert t3.contested is True


def test_models_are_strict_and_frozen() -> None:
    score = ClaimEvidenceScore(
        claim_id="c-1",
        paper_id="p-1",
        sample_size_n=100,
        p_value=0.01,
        has_effect_size=True,
        replication_count=1,
        contradiction_count=0,
        evidence_strength=0.6,
        tier="MODERATE",
    )
    with pytest.raises(ValidationError):
        score.evidence_strength = 0.9

    with pytest.raises(ValidationError):
        TopicConsensus(
            intervention="x",
            outcome="y",
            supporting_claims=1,
            contradicting_claims=0,
            neutral_claims=0,
            consensus_direction=EffectDirection.INCREASES,
            consensus_score=1.5,
            contested=False,
        )
