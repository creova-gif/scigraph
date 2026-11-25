from itertools import combinations

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
        intervention: str | None = None,
        condition: str | None = None,
        outcome: str | None = None,
        direction: EffectDirection | None = None,
    ) -> tuple[ScientificClaim, ...]:
        matched: list[ScientificClaim] = []
        norm_i = _normalize_entity(intervention) if intervention else None
        norm_c = _normalize_entity(condition) if condition else None
        norm_o = _normalize_entity(outcome) if outcome else None

        for claim in self._claims.values():
            ct = claim.claim_tuple
            if norm_i and _normalize_entity(ct.intervention) != norm_i:
                continue
            if norm_c and _normalize_entity(ct.condition) != norm_c:
                continue
            if norm_o and _normalize_entity(ct.outcome) != norm_o:
                continue
            if direction is not None and ct.direction != direction:
                continue
            matched.append(claim)

        return tuple(matched)

    def edges_for_claim(self, claim_id: str) -> tuple[EvidenceEdge, ...]:
        return tuple(
            edge
            for edge in self._edges.values()
            if edge.source_claim_id == claim_id or edge.target_claim_id == claim_id
        )
