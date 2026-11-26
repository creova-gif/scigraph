from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from graph.claim_graph import ClaimGraph
from scigraph.models import ScientificClaim

EntityCategory = Literal["intervention", "outcome", "condition"]


def _normalize_lookup_key(text: str) -> str:
    """Collapse whitespace and casefold for exact alias table lookup."""
    return " ".join(text.split()).casefold()


class AliasRule(BaseModel):
    """Maps surface-form aliases in a domain category to a canonical entity name."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    canonical: str = Field(min_length=1)
    aliases: tuple[str, ...]
    category: EntityCategory


DEFAULT_SCIENTIFIC_ALIASES: tuple[AliasRule, ...] = (
    AliasRule(
        canonical="CRISPR-Cas9",
        aliases=("CRISPR/Cas9", "Cas9 gene editing", "CRISPR Cas9"),
        category="intervention",
    ),
    AliasRule(
        canonical="LiFePO4",
        aliases=("LFP", "lithium iron phosphate", "LiFePO4 cathode"),
        category="intervention",
    ),
    AliasRule(
        canonical="NMC811",
        aliases=("LiNi0.8Mn0.1Co0.1O2", "NMC-811"),
        category="intervention",
    ),
    AliasRule(
        canonical="metformin",
        aliases=("metformin hydrochloride", "glucophage"),
        category="intervention",
    ),
    AliasRule(
        canonical="HbA1c",
        aliases=("glycated hemoglobin", "A1c", "hemoglobin A1c"),
        category="outcome",
    ),
    AliasRule(
        canonical="IL-6",
        aliases=("interleukin-6", "interleukin 6"),
        category="outcome",
    ),
    AliasRule(
        canonical="capacity retention",
        aliases=("cycle retention", "discharge capacity retention"),
        category="outcome",
    ),
    AliasRule(
        canonical="type 2 diabetes",
        aliases=("T2DM", "type II diabetes", "type 2 diabetes mellitus"),
        category="condition",
    ),
    AliasRule(
        canonical="room temperature",
        aliases=("25 C", "25°C", "ambient temperature"),
        category="condition",
    ),
)


class EntityCanonicalizer:
    """Canonicalizes scientific claim entities using category-scoped alias rules."""

    def __init__(self, rules: Sequence[AliasRule] = DEFAULT_SCIENTIFIC_ALIASES) -> None:
        self._rules: tuple[AliasRule, ...] = tuple(rules)
        self._lookup: dict[tuple[EntityCategory, str], str] = {}
        for rule in self._rules:
            canonical_clean = rule.canonical.strip()
            self._lookup[(rule.category, _normalize_lookup_key(canonical_clean))] = (
                canonical_clean
            )
            for alias in rule.aliases:
                key = _normalize_lookup_key(alias)
                if key:
                    self._lookup[(rule.category, key)] = canonical_clean

    @property
    def rules(self) -> tuple[AliasRule, ...]:
        return self._rules

    def canonicalize_text(self, text: str, category: EntityCategory) -> str:
        """Return canonical form for a known alias/canonical variant, else stripped text."""
        stripped = text.strip()
        key = _normalize_lookup_key(stripped)
        return self._lookup.get((category, key), stripped)

    def canonicalize_claim(self, claim: ScientificClaim) -> ScientificClaim:
        """Canonicalize intervention, condition, and outcome while preserving evidence."""
        ct = claim.claim_tuple
        updated_tuple = ct.model_copy(
            update={
                "intervention": self.canonicalize_text(ct.intervention, "intervention"),
                "condition": self.canonicalize_text(ct.condition, "condition"),
                "outcome": self.canonicalize_text(ct.outcome, "outcome"),
            }
        )
        return claim.model_copy(update={"claim_tuple": updated_tuple})

    def find_canonical_clusters(
        self,
        graph: ClaimGraph,
    ) -> dict[tuple[str, str], tuple[str, ...]]:
        """Group claim IDs by canonical (intervention, outcome) with >=2 distinct surface forms."""
        claim_ids_by_pair: dict[tuple[str, str], list[str]] = {}
        surface_forms_by_pair: dict[tuple[str, str], set[tuple[str, str]]] = {}

        for claim in graph.claims:
            ct = claim.claim_tuple
            canon_pair = (
                self.canonicalize_text(ct.intervention, "intervention"),
                self.canonicalize_text(ct.outcome, "outcome"),
            )
            claim_ids_by_pair.setdefault(canon_pair, []).append(claim.claim_id)
            surface_forms_by_pair.setdefault(canon_pair, set()).add(
                (ct.intervention, ct.outcome)
            )

        return {
            pair: tuple(claim_ids)
            for pair, claim_ids in claim_ids_by_pair.items()
            if len(surface_forms_by_pair[pair]) > 1
        }
