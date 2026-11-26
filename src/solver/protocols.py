from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from graph.claim_graph import ClaimGraph
from scigraph.models import ContradictionPair, FalsifiableExperiment
from solver.prioritizer import CostTier, prioritize_experiments

ProtocolPhase = Literal[
    "PRE_REGISTRATION",
    "RANDOMIZATION",
    "MEASUREMENT",
    "STATISTICAL_ANALYSIS",
]


class ProtocolStep(BaseModel):
    """Single ordered execution step in a falsifiable laboratory protocol."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    step_number: int = Field(ge=1)
    phase: ProtocolPhase
    instruction: str = Field(min_length=1)


class ExperimentProtocol(BaseModel):
    """Lab-ready, pre-registered protocol derived from a falsifiable experiment."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    protocol_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    contradiction_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    priority_rank: int | None = Field(default=None, ge=1)
    cost_tier: CostTier | None = None
    arms: tuple[str, ...] = Field(min_length=1)
    sample_size_total: int = Field(ge=1)
    alpha_threshold: float = Field(gt=0.0, lt=1.0)
    power_target: float = Field(default=0.90, gt=0.0, le=1.0)
    steps: tuple[ProtocolStep, ...] = Field(min_length=1)
    falsification_criterion: str = Field(min_length=1)


def _build_protocol_steps(experiment: FalsifiableExperiment) -> tuple[ProtocolStep, ...]:
    arms_summary = "; ".join(experiment.stratified_conditions)
    return (
        ProtocolStep(
            step_number=1,
            phase="PRE_REGISTRATION",
            instruction=(
                f"Pre-register hypothesis, primary outcome ({experiment.primary_outcome}), "
                f"target total sample size (N={experiment.recommended_sample_size}, power=0.90), "
                f"and significance threshold (alpha={experiment.alpha_threshold}) before data "
                f"collection. Hypothesis: {experiment.hypothesis}."
            ),
        ),
        ProtocolStep(
            step_number=2,
            phase="RANDOMIZATION",
            instruction=(
                f"Randomize N={experiment.recommended_sample_size} units across stratified "
                f"conditions ({arms_summary}) using blinded allocation for "
                f"{experiment.intervention}."
            ),
        ),
        ProtocolStep(
            step_number=3,
            phase="MEASUREMENT",
            instruction=(
                f"Administer {experiment.intervention} across arms ({arms_summary}) and "
                f"measure {experiment.primary_outcome} with outcome-blinded standardized assays."
            ),
        ),
        ProtocolStep(
            step_number=4,
            phase="STATISTICAL_ANALYSIS",
            instruction=(
                f"Analyze {experiment.primary_outcome} across {arms_summary} at "
                f"alpha={experiment.alpha_threshold}; evaluate falsification rule: "
                f"{experiment.falsification_criterion}."
            ),
        ),
    )


def generate_experiment_protocols(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair],
    experiments: Sequence[FalsifiableExperiment],
) -> tuple[ExperimentProtocol, ...]:
    """Generate prioritized, lab-ready experiment protocols for falsifiable experiments."""
    if not experiments:
        return ()

    ranked = prioritize_experiments(graph, contradictions, experiments)
    exp_by_id: dict[str, FalsifiableExperiment] = {
        exp.experiment_id: exp for exp in experiments
    }

    protocols: list[ExperimentProtocol] = []
    for item in ranked:
        exp = exp_by_id[item.experiment_id]
        protocols.append(
            ExperimentProtocol(
                protocol_id=f"proto-{exp.experiment_id}",
                experiment_id=exp.experiment_id,
                contradiction_id=exp.contradiction_id,
                title=(
                    f"Protocol for {exp.intervention} -> {exp.primary_outcome} "
                    f"({exp.contradiction_id})"
                ),
                priority_rank=item.rank,
                cost_tier=item.cost_tier,
                arms=exp.stratified_conditions,
                sample_size_total=exp.recommended_sample_size,
                alpha_threshold=exp.alpha_threshold,
                power_target=0.90,
                steps=_build_protocol_steps(exp),
                falsification_criterion=exp.falsification_criterion,
            )
        )

    return tuple(protocols)


def render_protocols_markdown(protocols: Sequence[ExperimentProtocol]) -> str:
    """Render experiment protocols as structured Markdown protocol sheets."""
    if not protocols:
        return "# Experiment Protocols\n\nNo experiment protocols available.\n"

    sections: list[str] = ["# Experiment Protocols", ""]
    for proto in protocols:
        rank_str = str(proto.priority_rank) if proto.priority_rank is not None else "N/A"
        cost_str = proto.cost_tier if proto.cost_tier is not None else "N/A"
        arms_str = ", ".join(proto.arms)
        sections.extend(
            [
                f"## {proto.protocol_id}: {proto.title}",
                "",
                f"- **Experiment ID:** `{proto.experiment_id}`",
                f"- **Contradiction ID:** `{proto.contradiction_id}`",
                f"- **Priority Rank:** {rank_str}",
                f"- **Cost Tier:** {cost_str}",
                f"- **Arms:** {arms_str}",
                f"- **Total Sample Size:** {proto.sample_size_total}",
                f"- **Alpha Threshold:** {proto.alpha_threshold}",
                f"- **Power Target:** {proto.power_target:.2f}",
                f"- **Falsification Criterion:** {proto.falsification_criterion}",
                "",
                "### Steps",
                "",
            ]
        )
        for step in proto.steps:
            sections.append(
                f"{step.step_number}. **[{step.phase}]** {step.instruction}"
            )
        sections.append("")

    return "\n".join(sections)
