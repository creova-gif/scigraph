from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from graph.claim_graph import ClaimGraph
from scigraph.models import EdgeRelation, EffectDirection, ScientificClaim

EvidenceTier = Literal["HIGH", "MODERATE", "PRELIMINARY"]


class ClaimEvidenceScore(BaseModel):
    """Deterministic evidence quality score for a single verified scientific claim."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    claim_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    sample_size_n: int | None
    p_value: float | None
    has_effect_size: bool
    replication_count: int = Field(ge=0)
    contradiction_count: int = Field(ge=0)
    evidence_strength: float = Field(ge=0.0, le=1.0)
    tier: EvidenceTier


class TopicConsensus(BaseModel):
    """Aggregated directional consensus for an (intervention, outcome) topic."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    intervention: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    supporting_claims: int = Field(ge=0)
    contradicting_claims: int = Field(ge=0)
    neutral_claims: int = Field(ge=0)
    consensus_direction: EffectDirection | None
    consensus_score: float = Field(ge=0.0, le=1.0)
    contested: bool


def _tier_for_strength(strength: float) -> EvidenceTier:
    if strength >= 0.70:
        return "HIGH"
    if strength >= 0.40:
        return "MODERATE"
    return "PRELIMINARY"


def score_claim_evidence(graph: ClaimGraph) -> dict[str, ClaimEvidenceScore]:
    """Deterministically score each claim in a ClaimGraph by statistical & graph evidence."""
    scores: dict[str, ClaimEvidenceScore] = {}

    for claim in sorted(graph.claims, key=lambda c: c.claim_id):
        stats = claim.statistics
        sample_size_n: int | None = stats.sample_size
        p_value: float | None = stats.p_value
        has_effect_size = stats.effect_size_raw is not None

        weight = 0.0
        if sample_size_n is not None:
            weight += min(0.35, sample_size_n / 1000.0 * 0.35)

        if p_value is not None:
            if p_value < 0.01:
                weight += 0.25
            elif p_value < 0.05:
                weight += 0.15

        if has_effect_size:
            weight += 0.15

        edges = graph.edges_for_claim(claim.claim_id)
        replication_count = sum(
            1
            for edge in edges
            if edge.relation in (EdgeRelation.SUPPORTS, EdgeRelation.REPLICATES)
        )
        contradiction_count = sum(
            1 for edge in edges if edge.relation == EdgeRelation.CONTRADICTS
        )

        weight += min(0.25, replication_count * 0.10)
        weight -= contradiction_count * 0.15

        evidence_strength = round(max(0.0, min(1.0, weight)), 4)
        tier = _tier_for_strength(evidence_strength)

        scores[claim.claim_id] = ClaimEvidenceScore(
            claim_id=claim.claim_id,
            paper_id=claim.paper_id,
            sample_size_n=sample_size_n,
            p_value=p_value,
            has_effect_size=has_effect_size,
            replication_count=replication_count,
            contradiction_count=contradiction_count,
            evidence_strength=evidence_strength,
            tier=tier,
        )

    return scores


def compute_topic_consensus(graph: ClaimGraph) -> tuple[TopicConsensus, ...]:
    """Compute directional consensus per normalized (intervention, outcome) topic."""
    claim_scores = score_claim_evidence(graph)
    groups: dict[tuple[str, str], list[ScientificClaim]] = {}

    for claim in graph.claims:
        key = (
            claim.claim_tuple.intervention.strip().casefold(),
            claim.claim_tuple.outcome.strip().casefold(),
        )
        groups.setdefault(key, []).append(claim)

    results: list[TopicConsensus] = []
    for (norm_intervention, norm_outcome), claims in sorted(groups.items()):
        inc_claims = [
            c for c in claims if c.claim_tuple.direction == EffectDirection.INCREASES
        ]
        dec_claims = [
            c for c in claims if c.claim_tuple.direction == EffectDirection.DECREASES
        ]
        neutral_claims_list = [
            c for c in claims if c.claim_tuple.direction == EffectDirection.NO_EFFECT
        ]

        inc_count = len(inc_claims)
        dec_count = len(dec_claims)
        neutral_count = len(neutral_claims_list)

        if inc_count > dec_count and inc_count >= neutral_count:
            consensus_direction: EffectDirection | None = EffectDirection.INCREASES
            supporting_claims = inc_count
            contradicting_claims = dec_count
            majority_claims = inc_claims
        elif dec_count > inc_count and dec_count >= neutral_count:
            consensus_direction = EffectDirection.DECREASES
            supporting_claims = dec_count
            contradicting_claims = inc_count
            majority_claims = dec_claims
        elif neutral_count > inc_count and neutral_count > dec_count:
            consensus_direction = EffectDirection.NO_EFFECT
            supporting_claims = inc_count
            contradicting_claims = dec_count
            majority_claims = neutral_claims_list
        else:
            consensus_direction = None
            supporting_claims = inc_count
            contradicting_claims = dec_count
            majority_claims = []

        if consensus_direction is None:
            consensus_score = 0.0
        else:
            claim_weights = {
                c.claim_id: max(claim_scores[c.claim_id].evidence_strength, 0.01)
                for c in claims
            }
            total_weight = sum(claim_weights.values())
            majority_weight = sum(claim_weights[c.claim_id] for c in majority_claims)
            consensus_score = (
                round(max(0.0, min(1.0, majority_weight / total_weight)), 4)
                if total_weight > 0.0
                else 0.0
            )

        contested = inc_count > 0 and dec_count > 0

        results.append(
            TopicConsensus(
                intervention=norm_intervention,
                outcome=norm_outcome,
                supporting_claims=supporting_claims,
                contradicting_claims=contradicting_claims,
                neutral_claims=neutral_count,
                consensus_direction=consensus_direction,
                consensus_score=consensus_score,
                contested=contested,
            )
        )

    return tuple(results)
