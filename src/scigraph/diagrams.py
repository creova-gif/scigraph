import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence

from graph.claim_graph import ClaimGraph
from scigraph.models import (
    ContradictionPair,
    EdgeRelation,
    Paper,
    ScientificClaim,
)

_EDGE_COLORS: dict[EdgeRelation, str] = {
    EdgeRelation.SUPPORTS: "darkgreen",
    EdgeRelation.REPLICATES: "darkgreen",
    EdgeRelation.CONTRADICTS: "crimson",
    EdgeRelation.QUALIFIES: "darkorange",
}


def _sanitize_id(raw_id: str) -> str:
    """Replace non-alphanumeric characters with underscores for Mermaid/DOT node IDs."""
    sanitized = re.sub(r"[^A-Za-z0-9]", "_", raw_id)
    return sanitized if sanitized else "_"


def _escape_label(text: str) -> str:
    """Escape quotes, newlines, brackets, and angle brackets for Mermaid/DOT labels."""
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    escaped = escaped.replace("[", "(").replace("]", ")")
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
    return escaped


def _format_claim_label(claim: ScientificClaim) -> str:
    ct = claim.claim_tuple
    cid = _escape_label(claim.claim_id)
    intervention = _escape_label(ct.intervention)
    outcome = _escape_label(ct.outcome)
    direction = _escape_label(ct.direction.value)
    return f"{cid}: {intervention} -> {outcome} ({direction})"


def export_mermaid_flowchart(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair] = (),
) -> str:
    """Export a ClaimGraph and optional ContradictionPairs as a Mermaid flowchart."""
    lines: list[str] = ["flowchart LR"]
    if not graph.claims and not contradictions:
        lines.append("    %% Empty claim graph")
        return "\n".join(lines) + "\n"

    for claim in sorted(graph.claims, key=lambda c: c.claim_id):
        nid = _sanitize_id(claim.claim_id)
        label = _format_claim_label(claim)
        lines.append(f'    {nid}["{label}"]')

    for edge in sorted(
        graph.edges,
        key=lambda e: (e.edge_id, e.source_claim_id, e.target_claim_id),
    ):
        src_nid = _sanitize_id(edge.source_claim_id)
        dst_nid = _sanitize_id(edge.target_claim_id)
        rel = _escape_label(edge.relation.value)
        lines.append(f'    {src_nid} -->|"{rel}"| {dst_nid}')

    for pair in sorted(
        contradictions,
        key=lambda p: (p.contradiction_id, p.claim_a.claim_id, p.claim_b.claim_id),
    ):
        a_nid = _sanitize_id(pair.claim_a.claim_id)
        b_nid = _sanitize_id(pair.claim_b.claim_id)
        kind = _escape_label(pair.kind.value)
        lines.append(f'    {a_nid} -. "CONFLICT: {kind}" .-> {b_nid}')

    return "\n".join(lines) + "\n"


def export_graphviz_dot(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair] = (),
) -> str:
    """Export a ClaimGraph and optional ContradictionPairs as a Graphviz DOT digraph."""
    lines: list[str] = ["digraph SciGraph {", "    rankdir=LR;"]

    papers_by_id: dict[str, Paper] = {p.paper_id: p for p in graph.papers}
    claims_by_paper: dict[str, list[ScientificClaim]] = {}
    for claim in graph.claims:
        claims_by_paper.setdefault(claim.paper_id, []).append(claim)

    all_paper_ids = sorted(set(papers_by_id) | set(claims_by_paper))
    if not all_paper_ids and not contradictions:
        lines.append("    // Empty claim graph")
        lines.append("}")
        return "\n".join(lines) + "\n"

    for paper_id in all_paper_ids:
        cluster_id = _sanitize_id(paper_id)
        paper = papers_by_id.get(paper_id)
        cluster_label = (
            f"{_escape_label(paper_id)}: {_escape_label(paper.title)}"
            if paper is not None
            else _escape_label(paper_id)
        )
        lines.append(f"    subgraph cluster_{cluster_id} {{")
        lines.append(f'        label="{cluster_label}";')
        for claim in sorted(claims_by_paper.get(paper_id, []), key=lambda c: c.claim_id):
            nid = _sanitize_id(claim.claim_id)
            label = _format_claim_label(claim)
            lines.append(f'        {nid} [label="{label}"];')
        lines.append("    }")

    for edge in sorted(
        graph.edges,
        key=lambda e: (e.edge_id, e.source_claim_id, e.target_claim_id),
    ):
        src_nid = _sanitize_id(edge.source_claim_id)
        dst_nid = _sanitize_id(edge.target_claim_id)
        color = _EDGE_COLORS[edge.relation]
        rel = _escape_label(edge.relation.value)
        lines.append(f'    {src_nid} -> {dst_nid} [label="{rel}", color={color}];')

    for pair in sorted(
        contradictions,
        key=lambda p: (p.contradiction_id, p.claim_a.claim_id, p.claim_b.claim_id),
    ):
        a_nid = _sanitize_id(pair.claim_a.claim_id)
        b_nid = _sanitize_id(pair.claim_b.claim_id)
        kind = _escape_label(pair.kind.value)
        lines.append(
            f'    {a_nid} -> {b_nid} [label="CONFLICT: {kind}", style=dashed, color=crimson];'
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


_GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
_GRAPHML_NODE_KEYS: tuple[tuple[str, str], ...] = (
    ("paper_id", "string"),
    ("doi", "string"),
    ("intervention", "string"),
    ("condition", "string"),
    ("outcome", "string"),
    ("direction", "string"),
    ("p_value", "double"),
    ("sample_size", "int"),
)
_GRAPHML_EDGE_KEYS: tuple[tuple[str, str], ...] = (
    ("relation", "string"),
    ("rationale", "string"),
)


def _graphml_tag(name: str) -> str:
    """Return a GraphML-namespaced ElementTree tag name."""
    return f"{{{_GRAPHML_NS}}}{name}"


def _add_graphml_data(parent: ET.Element, key: str, value: str) -> None:
    """Append a GraphML <data key=...> element with text content."""
    data_el = ET.SubElement(parent, _graphml_tag("data"), {"key": key})
    data_el.text = value


def export_graphml(graph: ClaimGraph) -> str:
    """Export a ClaimGraph as standard GraphML XML for Cytoscape/Gephi/NetworkX."""
    ET.register_namespace("", _GRAPHML_NS)
    root = ET.Element(_graphml_tag("graphml"))

    for attr_name, attr_type in _GRAPHML_NODE_KEYS:
        ET.SubElement(
            root,
            _graphml_tag("key"),
            {
                "id": attr_name,
                "for": "node",
                "attr.name": attr_name,
                "attr.type": attr_type,
            },
        )
    for attr_name, attr_type in _GRAPHML_EDGE_KEYS:
        ET.SubElement(
            root,
            _graphml_tag("key"),
            {
                "id": attr_name,
                "for": "edge",
                "attr.name": attr_name,
                "attr.type": attr_type,
            },
        )

    graph_el = ET.SubElement(
        root,
        _graphml_tag("graph"),
        {"id": "scigraph", "edgedefault": "directed"},
    )

    for claim in sorted(graph.claims, key=lambda c: c.claim_id):
        node_el = ET.SubElement(
            graph_el,
            _graphml_tag("node"),
            {"id": claim.claim_id},
        )
        ct = claim.claim_tuple
        node_attrs: tuple[tuple[str, str], ...] = (
            ("paper_id", claim.paper_id),
            ("doi", claim.doi),
            ("intervention", ct.intervention),
            ("condition", ct.condition),
            ("outcome", ct.outcome),
            ("direction", ct.direction.value),
            ("p_value", str(claim.statistics.p_value)),
            ("sample_size", str(claim.statistics.sample_size)),
        )
        for key, value in node_attrs:
            _add_graphml_data(node_el, key, value)

    for edge in sorted(
        graph.edges,
        key=lambda e: (e.edge_id, e.source_claim_id, e.target_claim_id),
    ):
        edge_el = ET.SubElement(
            graph_el,
            _graphml_tag("edge"),
            {
                "id": edge.edge_id,
                "source": edge.source_claim_id,
                "target": edge.target_claim_id,
            },
        )
        _add_graphml_data(edge_el, "relation", edge.relation.value)
        _add_graphml_data(edge_el, "rationale", edge.rationale)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"

