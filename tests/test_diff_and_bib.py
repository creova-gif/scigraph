"""Deterministic tests for graph diff tracking and BibTeX/RIS reference exporters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph.claim_graph import ClaimGraph
from scigraph.diff import GraphDiff, diff_claim_graphs, export_bibtex, export_ris
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
    doi: str,
    claim_id: str,
    direction: EffectDirection,
    condition: str = "adult mouse",
    title: str = "Metabolic Study",
    authors: tuple[str, ...] = ("Alice Smith", "Bob Jones"),
    venue: str = "Journal of Testing",
    year: int = 2024,
) -> tuple[Paper, ScientificClaim]:
    span_text = f"Drug X {direction.value} Biomarker Y in {condition} (n=120, p=0.002)."
    full_text = f"DOI: {doi}. Results: {span_text}"
    start_char = full_text.index(span_text)
    end_char = start_char + len(span_text)

    paper = Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=authors,
        publication_year=year,
        venue=venue,
        full_text=full_text,
    )
    claim = ScientificClaim(
        claim_id=claim_id,
        paper_id=paper_id,
        doi=doi,
        claim_tuple=ClaimTuple(
            intervention="Drug X",
            condition=condition,
            outcome="Biomarker Y",
            direction=direction,
            comparator="placebo",
        ),
        statistics=StatisticalEvidence(
            p_operator=ComparisonOperator.EQ,
            p_value=0.002,
            p_value_raw="p=0.002",
            sample_size=120,
            sample_size_raw="n=120",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=start_char,
            end_char=end_char,
            verbatim_text=span_text,
        ),
    )
    return paper, claim


def test_graph_diff_model_is_strict_and_frozen() -> None:
    diff = GraphDiff(
        added_papers=("p2",),
        removed_papers=(),
        added_claims=("c2",),
        removed_claims=(),
        new_contradictions=(),
        resolved_contradictions=(),
    )
    assert diff.added_papers == ("p2",)

    with pytest.raises(ValidationError):
        GraphDiff(
            added_papers=(),
            removed_papers=(),
            added_claims=(),
            removed_claims=(),
            new_contradictions=(),
            resolved_contradictions=(),
            unexpected="field",  # type: ignore[call-arg]
        )


def test_diff_claim_graphs_identical_graphs_returns_empty_diff() -> None:
    p1, c1 = _make_paper_and_claim(
        paper_id="paper-01",
        doi="10.1000/test.001",
        claim_id="claim-01",
        direction=EffectDirection.INCREASES,
    )
    baseline = ClaimGraph()
    baseline.add_verified_claim(p1, c1)

    current = ClaimGraph()
    current.add_verified_claim(p1, c1)

    diff = diff_claim_graphs(baseline, current)
    assert diff == GraphDiff(
        added_papers=(),
        removed_papers=(),
        added_claims=(),
        removed_claims=(),
        new_contradictions=(),
        resolved_contradictions=(),
    )


def test_diff_claim_graphs_tracks_added_removed_and_contradictions() -> None:
    p1, c1 = _make_paper_and_claim(
        paper_id="paper-01",
        doi="10.1000/test.001",
        claim_id="claim-01",
        direction=EffectDirection.INCREASES,
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="paper-02",
        doi="10.1000/test.002",
        claim_id="claim-02",
        direction=EffectDirection.DECREASES,
    )
    p3, c3 = _make_paper_and_claim(
        paper_id="paper-03",
        doi="10.1000/test.003",
        claim_id="claim-03",
        direction=EffectDirection.NO_EFFECT,
    )

    baseline = ClaimGraph()
    baseline.add_verified_claim(p1, c1)
    baseline.add_verified_claim(p2, c2)

    current = ClaimGraph()
    current.add_verified_claim(p1, c1)
    current.add_verified_claim(p3, c3)

    diff = diff_claim_graphs(baseline, current)
    assert diff.added_papers == ("paper-03",)
    assert diff.removed_papers == ("paper-02",)
    assert diff.added_claims == ("claim-03",)
    assert diff.removed_claims == ("claim-02",)
    assert diff.new_contradictions == ("claim-01|claim-03|null_vs_significant_conflict",)
    assert diff.resolved_contradictions == ("claim-01|claim-02|direct_direction_conflict",)


def test_export_bibtex_empty_and_sorted_with_latex_escaping() -> None:
    assert export_bibtex([]) == ""

    p_b, _ = _make_paper_and_claim(
        paper_id="paper-b",
        doi="10.1000/doi_with_underscore.2",
        claim_id="claim-b",
        direction=EffectDirection.INCREASES,
        title="Effects of 50% Dose & #1_Marker",
        authors=("Jane Doe_Jr", "John & Smith"),
        venue="Annals of A&B #2",
        year=2025,
    )
    p_a, _ = _make_paper_and_claim(
        paper_id="paper-a",
        doi="10.1000/alpha.1",
        claim_id="claim-a",
        direction=EffectDirection.DECREASES,
        title="Baseline Study",
        authors=("Alice One",),
        venue="Nature",
        year=2023,
    )

    bib = export_bibtex([p_b, p_a])
    expected = "\n\n".join(
        [
            "\n".join(
                [
                    "@article{paper-a,",
                    "  title = {Baseline Study},",
                    "  author = {Alice One},",
                    "  journal = {Nature},",
                    "  year = {2023},",
                    "  doi = {10.1000/alpha.1},",
                    "}",
                ]
            ),
            "\n".join(
                [
                    "@article{paper-b,",
                    r"  title = {Effects of 50\% Dose \& \#1\_Marker},",
                    r"  author = {Jane Doe\_Jr and John \& Smith},",
                    r"  journal = {Annals of A\&B \#2},",
                    "  year = {2025},",
                    "  doi = {10.1000/doi_with_underscore.2},",
                    "}",
                ]
            ),
        ]
    )
    assert bib == expected


def test_export_ris_empty_and_sorted_records() -> None:
    assert export_ris([]) == ""

    p_b, _ = _make_paper_and_claim(
        paper_id="paper-b",
        doi="10.1000/beta.2",
        claim_id="claim-b",
        direction=EffectDirection.INCREASES,
        title="Beta Study",
        authors=("First Author", "Second Author"),
        venue="Science",
        year=2025,
    )
    p_a, _ = _make_paper_and_claim(
        paper_id="paper-a",
        doi="10.1000/alpha.1",
        claim_id="claim-a",
        direction=EffectDirection.DECREASES,
        title="Alpha Study",
        authors=("Solo Author",),
        venue="Cell",
        year=2022,
    )

    ris = export_ris([p_b, p_a])
    expected = "\n\n".join(
        [
            "\n".join(
                [
                    "TY  - JOUR",
                    "ID  - paper-a",
                    "TI  - Alpha Study",
                    "AU  - Solo Author",
                    "JO  - Cell",
                    "PY  - 2022",
                    "DO  - 10.1000/alpha.1",
                    "ER  - ",
                ]
            ),
            "\n".join(
                [
                    "TY  - JOUR",
                    "ID  - paper-b",
                    "TI  - Beta Study",
                    "AU  - First Author",
                    "AU  - Second Author",
                    "JO  - Science",
                    "PY  - 2025",
                    "DO  - 10.1000/beta.2",
                    "ER  - ",
                ]
            ),
        ]
    )
    assert ris == expected
