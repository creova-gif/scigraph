from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field

from graph.claim_graph import ClaimGraph
from graph.scoring import score_claim_evidence
from scigraph.models import (
    ContradictionKind,
    ContradictionPair,
    FalsifiableExperiment,
)

CostTier = Literal["LOW", "MEDIUM", "HIGH"]


class PrioritizedExperiment(BaseModel):
    """Ranked falsifiable experiment with deterministic ROI and cost tiering."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    rank: int = Field(ge=1)
    experiment_id: str = Field(min_length=1)
    contradiction_id: str = Field(min_length=1)
    priority_score: float = Field(ge=0.0, le=1.0)
    cost_tier: CostTier
    estimated_participants: int = Field(ge=1)
    reason: str = Field(min_length=1)


def _kind_weight(kind: ContradictionKind) -> float:
    match kind:
        case ContradictionKind.DIRECT_DIRECTION_CONFLICT:
            return 0.45
        case ContradictionKind.NULL_VS_SIGNIFICANT_CONFLICT:
            return 0.35
        case ContradictionKind.CONDITION_DEPENDENT_DIVERGENCE:
            return 0.25
        case _ as unreachable:
            assert_never(unreachable)


def _cost_tier_and_bonus(sample_size: int) -> tuple[CostTier, float]:
    if sample_size <= 80:
        return ("LOW", 0.20)
    if sample_size <= 300:
        return ("MEDIUM", 0.10)
    return ("HIGH", 0.02)


def prioritize_experiments(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair],
    experiments: Sequence[FalsifiableExperiment],
) -> tuple[PrioritizedExperiment, ...]:
    """Rank falsifiable experiments by severity, evidence strength, and feasibility."""
    if not experiments:
        return ()

    scores = score_claim_evidence(graph)
    contra_by_id: dict[str, ContradictionPair] = {
        pair.contradiction_id: pair for pair in contradictions
    }

    scored_items: list[tuple[float, int, str, PrioritizedExperiment]] = []
    for exp in experiments:
        pair = contra_by_id.get(exp.contradiction_id)
        if pair is None:
            raise ValueError(
                f"Experiment {exp.experiment_id!r} references unknown contradiction_id "
                f"{exp.contradiction_id!r}"
            )

        kind_weight = _kind_weight(pair.kind)
        strength_a = (
            scores[pair.claim_a.claim_id].evidence_strength
            if pair.claim_a.claim_id in scores
            else 0.0
        )
        strength_b = (
            scores[pair.claim_b.claim_id].evidence_strength
            if pair.claim_b.claim_id in scores
            else 0.0
        )
        avg_evidence = (strength_a + strength_b) / 2.0

        n = exp.recommended_sample_size
        cost_tier, feasibility_bonus = _cost_tier_and_bonus(n)
        priority_score = round(kind_weight + avg_evidence * 0.35 + feasibility_bonus, 4)

        reason = (
            f"kind={pair.kind.value} (weight={kind_weight:.2f}), "
            f"avg_evidence={avg_evidence:.4f}, n={n} ({cost_tier} cost)"
        )

        candidate = PrioritizedExperiment(
            rank=1,
            experiment_id=exp.experiment_id,
            contradiction_id=exp.contradiction_id,
            priority_score=priority_score,
            cost_tier=cost_tier,
            estimated_participants=n,
            reason=reason,
        )
        scored_items.append((priority_score, -n, exp.experiment_id, candidate))

    scored_items.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    return tuple(
        item[3].model_copy(update={"rank": idx})
        for idx, item in enumerate(scored_items, start=1)
    )
