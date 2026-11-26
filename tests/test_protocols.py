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
    ExperimentProtocol,
    ProtocolPhase,
    ProtocolStep,
    generate_experiment_protocols,
    render_protocols_markdown,
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
            effect_size_raw="d = 0.50",
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
        unsat_constraints=(
            f"Dir(a)=={claim_a.claim_id}",
            f"Dir(b)=={claim_b.claim_id}",
        ),
        discriminating_factor="Test conflict",
    )


def _make_experiment(
    *,
    experiment_id: str,
    contradiction_id: str,
    intervention: str = "CompoundX",
    arms: tuple[str, ...] = ("Normoxia", "Hypoxia"),
    outcome: str = "Viability",
    sample_size: int = 80,
    alpha_threshold: float = 0.01,
) -> FalsifiableExperiment:
    return FalsifiableExperiment(
        experiment_id=experiment_id,
        contradiction_id=contradiction_id,
        hypothesis=f"{intervention} alters {outcome} across arms",
        intervention=intervention,
        stratified_conditions=arms,
        primary_outcome=outcome,
        recommended_sample_size=sample_size,
        alpha_threshold=alpha_threshold,
        falsification_criterion=f"Falsified if p >= {alpha_threshold}",
    )


def test_empty_experiments_returns_empty_tuple() -> None:
    graph = ClaimGraph()
    protocols = generate_experiment_protocols(graph, (), ())
    assert protocols == ()


def test_render_protocols_markdown_empty_state() -> None:
    rendered = render_protocols_markdown(())
    assert "# Experiment Protocols" in rendered
    assert "No experiment protocols" in rendered


def test_generate_experiment_protocols_ordering_and_fields() -> None:
    p1, c1 = _make_paper_and_claim(
        paper_id="p1",
        doi="10.1000/p1",
        claim_id="c1",
        intervention="DrugA",
        condition="Normoxia",
        outcome="Apoptosis",
        direction=EffectDirection.INCREASES,
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="p2",
        doi="10.1000/p2",
        claim_id="c2",
        intervention="DrugA",
        condition="Normoxia",
        outcome="Apoptosis",
        direction=EffectDirection.DECREASES,
    )
    p3, c3 = _make_paper_and_claim(
        paper_id="p3",
        doi="10.1000/p3",
        claim_id="c3",
        intervention="DrugB",
        condition="Hypoxia",
        outcome="Proliferation",
        direction=EffectDirection.NO_EFFECT,
    )
    p4, c4 = _make_paper_and_claim(
        paper_id="p4",
        doi="10.1000/p4",
        claim_id="c4",
        intervention="DrugB",
        condition="Normoxia",
        outcome="Proliferation",
        direction=EffectDirection.INCREASES,
    )

    graph = ClaimGraph()
    for paper, claim in ((p1, c1), (p2, c2), (p3, c3), (p4, c4)):
        graph.add_verified_claim(paper, claim)

    contra_direct = _make_contradiction(
        contradiction_id="contra-0001",
        claim_a=c1,
        claim_b=c2,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
    )
    contra_cond = _make_contradiction(
        contradiction_id="contra-0002",
        claim_a=c3,
        claim_b=c4,
        kind=ContradictionKind.CONDITION_DEPENDENT_DIVERGENCE,
    )

    exp_low_priority = _make_experiment(
        experiment_id="exp-0002",
        contradiction_id="contra-0002",
        intervention="DrugB",
        arms=("Hypoxia", "Normoxia"),
        outcome="Proliferation",
        sample_size=400,
        alpha_threshold=0.01,
    )
    exp_high_priority = _make_experiment(
        experiment_id="exp-0001",
        contradiction_id="contra-0001",
        intervention="DrugA",
        arms=("Normoxia vs control", "Normoxia vs vehicle"),
        outcome="Apoptosis",
        sample_size=60,
        alpha_threshold=0.01,
    )

    protocols = generate_experiment_protocols(
        graph,
        (contra_cond, contra_direct),
        (exp_low_priority, exp_high_priority),
    )

    assert len(protocols) == 2
    first, second = protocols

    assert first.protocol_id == "proto-exp-0001"
    assert first.experiment_id == "exp-0001"
    assert first.contradiction_id == "contra-0001"
    assert first.priority_rank == 1
    assert first.cost_tier == "LOW"
    assert first.sample_size_total == 60
    assert first.alpha_threshold == 0.01
    assert first.power_target == 0.90
    assert first.arms == ("Normoxia vs control", "Normoxia vs vehicle")

    assert second.protocol_id == "proto-exp-0002"
    assert second.priority_rank == 2
    assert second.cost_tier == "HIGH"
    assert second.sample_size_total == 400


def test_protocol_steps_phases_and_references() -> None:
    p1, c1 = _make_paper_and_claim(
        paper_id="p1",
        doi="10.1000/p1",
        claim_id="c1",
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="p2",
        doi="10.1000/p2",
        claim_id="c2",
        direction=EffectDirection.DECREASES,
    )
    graph = ClaimGraph()
    graph.add_verified_claim(p1, c1)
    graph.add_verified_claim(p2, c2)

    contra = _make_contradiction(
        contradiction_id="contra-0001",
        claim_a=c1,
        claim_b=c2,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
    )
    exp = _make_experiment(
        experiment_id="exp-0001",
        contradiction_id="contra-0001",
        intervention="Metformin",
        arms=("Low Glucose", "High Glucose"),
        outcome="ATP_Level",
        sample_size=120,
        alpha_threshold=0.005,
    )

    (proto,) = generate_experiment_protocols(graph, (contra,), (exp,))

    expected_phases: tuple[ProtocolPhase, ...] = (
        "PRE_REGISTRATION",
        "RANDOMIZATION",
        "MEASUREMENT",
        "STATISTICAL_ANALYSIS",
    )
    assert tuple(step.phase for step in proto.steps) == expected_phases
    assert tuple(step.step_number for step in proto.steps) == (1, 2, 3, 4)

    all_instructions = " ".join(step.instruction for step in proto.steps)
    assert "Metformin" in all_instructions
    assert "Low Glucose" in all_instructions
    assert "High Glucose" in all_instructions
    assert "ATP_Level" in all_instructions
    assert "120" in all_instructions
    assert "0.005" in all_instructions


def test_render_protocols_markdown_populated() -> None:
    step = ProtocolStep(
        step_number=1,
        phase="PRE_REGISTRATION",
        instruction="Pre-register primary outcome Viability at alpha=0.01.",
    )
    proto = ExperimentProtocol(
        protocol_id="proto-exp-0001",
        experiment_id="exp-0001",
        contradiction_id="contra-0001",
        title="Protocol for CompoundX -> Viability (contra-0001)",
        priority_rank=1,
        cost_tier="LOW",
        arms=("Normoxia", "Hypoxia"),
        sample_size_total=80,
        alpha_threshold=0.01,
        power_target=0.90,
        steps=(step,),
        falsification_criterion="Falsified if p >= 0.01",
    )

    md = render_protocols_markdown((proto,))
    assert "# Experiment Protocols" in md
    assert "## proto-exp-0001: Protocol for CompoundX -> Viability (contra-0001)" in md
    assert "**Experiment ID:** `exp-0001`" in md
    assert "**Contradiction ID:** `contra-0001`" in md
    assert "**Priority Rank:** 1" in md
    assert "**Cost Tier:** LOW" in md
    assert "**Arms:** Normoxia, Hypoxia" in md
    assert "**Total Sample Size:** 80" in md
    assert "**Alpha Threshold:** 0.01" in md
    assert "**Power Target:** 0.90" in md
    assert "1. **[PRE_REGISTRATION]** Pre-register primary outcome Viability at alpha=0.01." in md


def test_protocol_models_are_strict_and_frozen() -> None:
    step = ProtocolStep(
        step_number=1,
        phase="PRE_REGISTRATION",
        instruction="Register protocol.",
    )
    with pytest.raises(ValidationError):
        step.step_number = 2

    with pytest.raises(ValidationError):
        ProtocolStep(
            step_number="1",  # type: ignore[arg-type]
            phase="PRE_REGISTRATION",
            instruction="Register protocol.",
        )

    with pytest.raises(ValidationError):
        ProtocolStep(
            step_number=1,
            phase="INVALID_PHASE",  # type: ignore[arg-type]
            instruction="Register protocol.",
        )

    with pytest.raises(ValidationError):
        ProtocolStep(
            step_number=1,
            phase="PRE_REGISTRATION",
            instruction="Register protocol.",
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_generate_experiment_protocols_unknown_contradiction_raises() -> None:
    graph = ClaimGraph()
    exp = _make_experiment(
        experiment_id="exp-9999",
        contradiction_id="contra-missing",
    )
    with pytest.raises(ValueError, match="unknown contradiction_id"):
        generate_experiment_protocols(graph, (), (exp,))
