from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import Any

from ingest.verifier import verify_claim_verbatim
from scigraph.models import (
    ClaimVerificationResult,
    EdgeRelation,
    EffectDirection,
    EvidenceEdge,
    Paper,
    ScientificClaim,
    _normalize_entity,
)


class ClaimGraph:
    def __init__(self) -> None:
        self._papers: dict[str, Paper] = {}
        self._claims: dict[str, ScientificClaim] = {}
        self._edges: dict[str, EvidenceEdge] = {}

    @property
    def papers(self) -> tuple[Paper, ...]:
        return tuple(self._papers.values())

    @property
    def claims(self) -> tuple[ScientificClaim, ...]:
        return tuple(self._claims.values())

    @property
    def edges(self) -> tuple[EvidenceEdge, ...]:
        return tuple(self._edges.values())

    def add_paper(self, paper: Paper) -> None:
        self._papers[paper.paper_id] = paper

    def add_verified_claim(
        self,
        paper: Paper,
        claim: ScientificClaim,
    ) -> ClaimVerificationResult:
        result = verify_claim_verbatim(paper, claim)
        if not result.verified:
            reasons = ", ".join(r.value for r in result.failures)
            raise ValueError(
                f"Claim {claim.claim_id} failed verbatim verification: {reasons}"
            )
        self._papers[paper.paper_id] = paper
        self._claims[claim.claim_id] = claim
        return result

    def replace_paper_claims(
        self,
        paper: Paper,
        claims: Sequence[ScientificClaim],
    ) -> list[ClaimVerificationResult]:
        """Validate all incoming claims, then atomically replace existing claims for paper."""
        results: list[ClaimVerificationResult] = []
        for claim in claims:
            result = verify_claim_verbatim(paper, claim)
            if not result.verified:
                reasons = ", ".join(r.value for r in result.failures)
                raise ValueError(
                    f"Claim {claim.claim_id} failed verbatim verification: {reasons}"
                )
            results.append(result)

        stale_ids = [
            claim_id
            for claim_id, existing in self._claims.items()
            if existing.paper_id == paper.paper_id
        ]
        for claim_id in stale_ids:
            del self._claims[claim_id]

        self._papers[paper.paper_id] = paper
        for claim in claims:
            self._claims[claim.claim_id] = claim
        return results

    def build_edges(self) -> tuple[EvidenceEdge, ...]:
        self._edges.clear()
        groups: dict[tuple[str, str], list[ScientificClaim]] = {}
        for claim in self._claims.values():
            key = claim.claim_tuple.intervention_outcome_key()
            groups.setdefault(key, []).append(claim)

        edge_counter = 1
        for (norm_intervention, norm_outcome), group in sorted(groups.items()):
            for claim_a, claim_b in combinations(group, 2):
                cond_a = _normalize_entity(claim_a.claim_tuple.condition)
                cond_b = _normalize_entity(claim_b.claim_tuple.condition)
                dir_a = claim_a.claim_tuple.direction
                dir_b = claim_b.claim_tuple.direction

                if cond_a == cond_b:
                    if dir_a == dir_b:
                        relation = (
                            EdgeRelation.REPLICATES
                            if claim_a.paper_id != claim_b.paper_id
                            else EdgeRelation.SUPPORTS
                        )
                        rationale = (
                            f"Matching direction ({dir_a.value}) under identical "
                            f"condition '{claim_a.claim_tuple.condition}'"
                        )
                    else:
                        relation = EdgeRelation.CONTRADICTS
                        rationale = (
                            f"Opposing directions ({dir_a.value} vs {dir_b.value}) "
                            f"under identical condition '{claim_a.claim_tuple.condition}'"
                        )
                else:
                    if dir_a == dir_b:
                        relation = EdgeRelation.SUPPORTS
                        rationale = (
                            f"Consistent direction ({dir_a.value}) across conditions "
                            f"'{claim_a.claim_tuple.condition}' and "
                            f"'{claim_b.claim_tuple.condition}'"
                        )
                    else:
                        relation = EdgeRelation.QUALIFIES
                        rationale = (
                            f"Condition-dependent divergence ({dir_a.value} under "
                            f"'{claim_a.claim_tuple.condition}' vs {dir_b.value} under "
                            f"'{claim_b.claim_tuple.condition}')"
                        )

                edge_id = f"edge-{edge_counter:04d}"
                edge_counter += 1
                self._edges[edge_id] = EvidenceEdge(
                    edge_id=edge_id,
                    source_claim_id=claim_a.claim_id,
                    target_claim_id=claim_b.claim_id,
                    relation=relation,
                    rationale=rationale,
                    shared_intervention=norm_intervention,
                    shared_outcome=norm_outcome,
                )

        return tuple(self._edges.values())

    def query_claims(
        self,
        *,
        intervention: str | None = None,
        condition: str | None = None,
        outcome: str | None = None,
        effect_direction: EffectDirection | None = None,
        paper_id: str | None = None,
    ) -> tuple[ScientificClaim, ...]:
        """Filter claims by case-insensitive substrings and exact direction/paper_id."""
        matched: list[ScientificClaim] = []
        needle_i = intervention.casefold() if intervention is not None else None
        needle_c = condition.casefold() if condition is not None else None
        needle_o = outcome.casefold() if outcome is not None else None

        for claim in self._claims.values():
            ct = claim.claim_tuple
            if needle_i is not None and needle_i not in ct.intervention.casefold():
                continue
            if needle_c is not None and needle_c not in ct.condition.casefold():
                continue
            if needle_o is not None and needle_o not in ct.outcome.casefold():
                continue
            if effect_direction is not None and ct.direction != effect_direction:
                continue
            if paper_id is not None and claim.paper_id != paper_id:
                continue
            matched.append(claim)

        return tuple(matched)

    def to_dict(self) -> dict[str, object]:
        """Serialize papers, claims, and edges into a JSON-compatible dictionary."""
        return {
            "papers": [paper.model_dump(mode="json") for paper in self._papers.values()],
            "claims": [claim.model_dump(mode="json") for claim in self._claims.values()],
            "edges": [edge.model_dump(mode="json") for edge in self._edges.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimGraph:
        """Reconstruct and validate a ClaimGraph from a serialized dictionary."""
        raw_papers = data.get("papers", [])
        raw_claims = data.get("claims", [])
        raw_edges = data.get("edges", [])
        if (
            not isinstance(raw_papers, list)
            or not isinstance(raw_claims, list)
            or not isinstance(raw_edges, list)
        ):
            raise ValueError(
                "ClaimGraph dictionary requires list values for 'papers', 'claims', and 'edges'"
            )

        graph = cls()
        for raw_paper in raw_papers:
            paper = Paper.model_validate(raw_paper, strict=False)
            graph._papers[paper.paper_id] = paper
        for raw_claim in raw_claims:
            claim = ScientificClaim.model_validate(raw_claim, strict=False)
            graph._claims[claim.claim_id] = claim
        for raw_edge in raw_edges:
            edge = EvidenceEdge.model_validate(raw_edge, strict=False)
            graph._edges[edge.edge_id] = edge

        for claim in graph._claims.values():
            if claim.paper_id not in graph._papers:
                raise ValueError(
                    f"Claim '{claim.claim_id}' references unknown paper_id '{claim.paper_id}'"
                )
        for edge in graph._edges.values():
            if edge.source_claim_id not in graph._claims:
                raise ValueError(
                    f"Edge '{edge.edge_id}' references unknown "
                    f"source_claim_id '{edge.source_claim_id}'"
                )
            if edge.target_claim_id not in graph._claims:
                raise ValueError(
                    f"Edge '{edge.edge_id}' references unknown "
                    f"target_claim_id '{edge.target_claim_id}'"
                )
        return graph

    def edges_for_claim(self, claim_id: str) -> tuple[EvidenceEdge, ...]:
        return tuple(
            edge
            for edge in self._edges.values()
            if edge.source_claim_id == claim_id or edge.target_claim_id == claim_id
        )
