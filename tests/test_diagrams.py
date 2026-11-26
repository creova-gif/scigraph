from graph.claim_graph import ClaimGraph
from scigraph.diagrams import (
    _escape_label,
    _sanitize_id,
    export_graphviz_dot,
    export_mermaid_flowchart,
)
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    ContradictionKind,
    ContradictionPair,
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
    doi: str,
    intervention: str,
    condition: str,
    outcome: str,
    direction: EffectDirection,
    p_value: float = 0.01,
    p_value_raw: str = "p = 0.01",
    sample_size: int = 100,
    sample_size_raw: str = "n = 100",
    title: str | None = None,
) -> tuple[Paper, ScientificClaim]:
    statement = (
        f"In {condition}, {intervention} {direction.value} {outcome} "
        f"({sample_size_raw}, {p_value_raw})."
    )
    full_text = f"DOI: {doi}. Results: {statement}"
    start = full_text.index(statement)
    end = start + len(statement)
    paper = Paper(
        paper_id=paper_id,
        doi=doi,
        title=title or f"Study {paper_id}",
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
            p_value=p_value,
            p_value_raw=p_value_raw,
            sample_size=sample_size,
            sample_size_raw=sample_size_raw,
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=start,
            end_char=end,
            verbatim_text=statement,
        ),
    )
    return paper, claim


def test_sanitize_id_and_escape_label() -> None:
    assert _sanitize_id("paper-1/claim:02.a") == "paper_1_claim_02_a"
    assert _sanitize_id("alpha_99") == "alpha_99"
    assert _sanitize_id("") == "_"

    raw = 'Dose "A"\n[arm 1]\r\n<p < 0.05>'
    escaped = _escape_label(raw)
    assert "\n" not in escaped
    assert "\r" not in escaped
    assert "[" not in escaped and "]" not in escaped
    assert "<" not in escaped and ">" not in escaped
    assert '\\"' in escaped
    assert "\\n" in escaped
    assert "&lt;" in escaped and "&gt;" in escaped


def test_export_empty_graphs() -> None:
    empty = ClaimGraph()

    mermaid = export_mermaid_flowchart(empty)
    assert mermaid.startswith("flowchart LR\n")
    assert "%% Empty claim graph" in mermaid

    dot = export_graphviz_dot(empty)
    assert dot.startswith("digraph SciGraph {\n")
    assert "rankdir=LR;" in dot
    assert "// Empty claim graph" in dot
    assert dot.rstrip().endswith("}")


def test_export_populated_graph_with_edges_and_contradictions() -> None:
    graph = ClaimGraph()
    p1, c1 = _make_paper_and_claim(
        paper_id="paper-1",
        claim_id="claim-1",
        doi="10.1000/test.001",
        intervention="Metformin",
        condition="adult cohort",
        outcome="HbA1c",
        direction=EffectDirection.DECREASES,
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="paper-2",
        claim_id="claim-2",
        doi="10.1000/test.002",
        intervention="Metformin",
        condition="adult cohort",
        outcome="HbA1c",
        direction=EffectDirection.INCREASES,
    )
    p3, c3 = _make_paper_and_claim(
        paper_id="paper-3",
        claim_id="claim-3",
        doi="10.1000/test.003",
        intervention="Metformin",
        condition="pediatric cohort",
        outcome="HbA1c",
        direction=EffectDirection.INCREASES,
    )
    for paper, claim in ((p1, c1), (p2, c2), (p3, c3)):
        graph.add_verified_claim(paper, claim)
    graph.build_edges()

    contradiction = ContradictionPair(
        contradiction_id="contra-1",
        claim_a=c1,
        claim_b=c2,
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
        unsat_constraints=("direction(c1) != direction(c2)",),
        discriminating_factor="Opposite direction under identical condition",
    )

    mermaid = export_mermaid_flowchart(graph, contradictions=(contradiction,))
    assert "flowchart LR" in mermaid
    assert 'claim_1["claim-1: Metformin -> HbA1c (decreases)"]' in mermaid
    assert 'claim_2["claim-2: Metformin -> HbA1c (increases)"]' in mermaid
    assert 'claim_3["claim-3: Metformin -> HbA1c (increases)"]' in mermaid
    assert 'claim_1 -->|"contradicts"| claim_2' in mermaid
    assert 'claim_1 -->|"qualifies"| claim_3' in mermaid
    assert 'claim_2 -->|"supports"| claim_3' in mermaid
    assert 'claim_1 -. "CONFLICT: direct_direction_conflict" .-> claim_2' in mermaid

    dot = export_graphviz_dot(graph, contradictions=(contradiction,))
    assert "digraph SciGraph {" in dot
    assert "rankdir=LR;" in dot
    assert "subgraph cluster_paper_1 {" in dot
    assert "subgraph cluster_paper_2 {" in dot
    assert "subgraph cluster_paper_3 {" in dot
    assert 'claim_1 [label="claim-1: Metformin -> HbA1c (decreases)"];' in dot
    assert 'claim_1 -> claim_2 [label="contradicts", color=crimson];' in dot
    assert 'claim_1 -> claim_3 [label="qualifies", color=darkorange];' in dot
    assert 'claim_2 -> claim_3 [label="supports", color=darkgreen];' in dot
    assert (
        'claim_1 -> claim_2 [label="CONFLICT: direct_direction_conflict", '
        "style=dashed, color=crimson];"
    ) in dot


def test_export_special_characters_and_deterministic_ordering() -> None:
    p_b, c_b = _make_paper_and_claim(
        paper_id="paper-b",
        claim_id="claim-b",
        doi="10.1000/spec.002",
        intervention='Drug "X" [low]',
        condition="cohort <A>",
        outcome="Biomarker\nLevel",
        direction=EffectDirection.INCREASES,
        title='Paper "Beta" [v2]',
    )
    p_a, c_a = _make_paper_and_claim(
        paper_id="paper-a",
        claim_id="claim-a",
        doi="10.1000/spec.001",
        intervention='Drug "X" [low]',
        condition="cohort <A>",
        outcome="Biomarker\nLevel",
        direction=EffectDirection.INCREASES,
        title='Paper "Alpha" <1>',
    )

    g1 = ClaimGraph()
    g1.add_verified_claim(p_a, c_a)
    g1.add_verified_claim(p_b, c_b)
    g1.build_edges()

    g2 = ClaimGraph()
    g2.add_verified_claim(p_b, c_b)
    g2.add_verified_claim(p_a, c_a)
    g2.build_edges()

    m1 = export_mermaid_flowchart(g1)
    m2 = export_mermaid_flowchart(g2)
    assert m1.index("claim_a[") < m1.index("claim_b[")
    assert 'Drug \\"X\\" (low) -> Biomarker\\nLevel (increases)' in m1
    # Note: edge_id depends on insertion order in ClaimGraph.build_edges(),
    # while node and cluster ordering is deterministic by ID.
    assert "claim_a" in m2 and "claim_b" in m2

    d1 = export_graphviz_dot(g1)
    d2 = export_graphviz_dot(g2)
    assert d1.index("subgraph cluster_paper_a") < d1.index("subgraph cluster_paper_b")
    assert d2.index("subgraph cluster_paper_a") < d2.index("subgraph cluster_paper_b")
    assert 'label="paper-a: Paper \\"Alpha\\" &lt;1&gt;";' in d1
    assert 'label="paper-b: Paper \\"Beta\\" (v2)";' in d1
    assert "color=darkgreen" in d1
