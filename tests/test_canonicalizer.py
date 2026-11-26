from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph import (
    DEFAULT_SCIENTIFIC_ALIASES,
    AliasRule,
    ClaimGraph,
    EntityCanonicalizer,
)
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    Paper,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)


def _make_paper_and_claim(
    *,
    paper_id: str,
    claim_id: str,
    intervention: str,
    condition: str,
    outcome: str,
    direction: EffectDirection = EffectDirection.INCREASES,
    verbatim_sentence: str | None = None,
) -> tuple[Paper, ScientificClaim]:
    doi = f"10.1234/{paper_id}"
    sentence = (
        verbatim_sentence
        if verbatim_sentence is not None
        else f"{intervention} under {condition} altered {outcome} (p = 0.01, n = 40)."
    )
    prefix = f"DOI: {doi}. Results: "
    full_text = f"{prefix}{sentence}"
    start_char = len(prefix)
    end_char = start_char + len(sentence)

    paper = Paper(
        paper_id=paper_id,
        doi=doi,
        title=f"Study {paper_id}",
        authors=("Author A",),
        publication_year=2025,
        venue="Journal of Testing",
        full_text=full_text,
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
            p_value=0.01,
            p_value_raw="p = 0.01",
            sample_size=40,
            sample_size_raw="n = 40",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=start_char,
            end_char=end_char,
            verbatim_text=sentence,
        ),
    )
    return paper, claim


def test_alias_rule_strict_frozen_forbid() -> None:
    rule = AliasRule(
        canonical="LiFePO4",
        aliases=("LFP",),
        category="intervention",
    )
    with pytest.raises(ValidationError):
        AliasRule.model_validate(
            {
                "canonical": "LiFePO4",
                "aliases": ("LFP",),
                "category": "intervention",
                "unexpected": 1,
            }
        )
    with pytest.raises(ValidationError):
        rule.canonical = "other"


def test_canonicalize_text_normalizes_whitespace_and_case() -> None:
    canon = EntityCanonicalizer()

    assert len(DEFAULT_SCIENTIFIC_ALIASES) >= 5
    assert canon.canonicalize_text("  crispr/cas9  ", "intervention") == "CRISPR-Cas9"
    assert (
        canon.canonicalize_text("Cas9   gene\tediting", "intervention")
        == "CRISPR-Cas9"
    )
    assert canon.canonicalize_text("lfp", "intervention") == "LiFePO4"
    assert (
        canon.canonicalize_text("Lithium  Iron\nPhosphate", "intervention") == "LiFePO4"
    )
    assert canon.canonicalize_text("glycated hemoglobin", "outcome") == "HbA1c"
    assert canon.canonicalize_text("a1c", "outcome") == "HbA1c"
    assert canon.canonicalize_text("interleukin 6", "outcome") == "IL-6"
    assert (
        canon.canonicalize_text("discharge capacity retention", "outcome")
        == "capacity retention"
    )
    assert canon.canonicalize_text("T2DM", "condition") == "type 2 diabetes"


def test_canonicalize_text_respects_category_and_preserves_unknown() -> None:
    canon = EntityCanonicalizer()

    # Category-scoped: "LFP" is only registered under "intervention", not "outcome".
    assert canon.canonicalize_text("  LFP  ", "outcome") == "LFP"
    assert canon.canonicalize_text("  novel compound X  ", "intervention") == "novel compound X"
    # Canonical form itself is normalized back to canonical casing.
    assert canon.canonicalize_text("  crispr-cas9 ", "intervention") == "CRISPR-Cas9"


def test_canonicalize_claim_preserves_evidence_span_verbatim() -> None:
    canon = EntityCanonicalizer()
    _, claim = _make_paper_and_claim(
        paper_id="p1",
        claim_id="c1",
        intervention="  LFP ",
        condition="25°C",
        outcome="cycle retention",
        verbatim_sentence="LFP at 25°C improved cycle retention (p = 0.01, n = 40).",
    )

    canonical_claim = canon.canonicalize_claim(claim)

    assert canonical_claim.claim_tuple.intervention == "LiFePO4"
    assert canonical_claim.claim_tuple.condition == "room temperature"
    assert canonical_claim.claim_tuple.outcome == "capacity retention"
    assert canonical_claim.evidence_span == claim.evidence_span
    assert canonical_claim.evidence_span.verbatim_text == claim.evidence_span.verbatim_text
    assert canonical_claim.evidence_span.start_char == claim.evidence_span.start_char
    assert canonical_claim.evidence_span.end_char == claim.evidence_span.end_char
    assert canonical_claim.evidence_span.section == claim.evidence_span.section
    assert canonical_claim.claim_id == claim.claim_id
    assert canonical_claim.statistics == claim.statistics


def test_custom_alias_rules() -> None:
    custom_rules = (
        AliasRule(
            canonical="aspirin",
            aliases=("acetylsalicylic acid", "ASA"),
            category="intervention",
        ),
        AliasRule(
            canonical="systolic blood pressure",
            aliases=("SBP",),
            category="outcome",
        ),
    )
    canon = EntityCanonicalizer(rules=custom_rules)

    assert canon.canonicalize_text("asa", "intervention") == "aspirin"
    assert (
        canon.canonicalize_text("sbp", "outcome") == "systolic blood pressure"
    )
    # Default rules are not active when custom rules are supplied.
    assert canon.canonicalize_text("LFP", "intervention") == "LFP"


def test_find_canonical_clusters_groups_distinct_surface_forms() -> None:
    canon = EntityCanonicalizer()
    graph = ClaimGraph()

    # Cluster 1: ("LiFePO4", "capacity retention") with two distinct surface forms
    p1, c1 = _make_paper_and_claim(
        paper_id="p1",
        claim_id="c1",
        intervention="LFP",
        condition="room temperature",
        outcome="cycle retention",
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="p2",
        claim_id="c2",
        intervention="lithium iron phosphate",
        condition="25 C",
        outcome="discharge capacity retention",
    )

    # Same surface form twice -> should NOT appear as a cluster
    p3, c3 = _make_paper_and_claim(
        paper_id="p3",
        claim_id="c3",
        intervention="CRISPR/Cas9",
        condition="in vitro",
        outcome="IL-6",
    )
    p4, c4 = _make_paper_and_claim(
        paper_id="p4",
        claim_id="c4",
        intervention="CRISPR/Cas9",
        condition="in vivo",
        outcome="IL-6",
    )

    # Single claim -> should NOT appear as a cluster
    p5, c5 = _make_paper_and_claim(
        paper_id="p5",
        claim_id="c5",
        intervention="metformin",
        condition="T2DM",
        outcome="HbA1c",
    )

    for paper, claim in ((p1, c1), (p2, c2), (p3, c3), (p4, c4), (p5, c5)):
        graph.add_verified_claim(paper, claim)

    clusters = canon.find_canonical_clusters(graph)
    assert clusters == {
        ("LiFePO4", "capacity retention"): ("c1", "c2"),
    }
