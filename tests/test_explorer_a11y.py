from graph import ClaimGraph
from ingest import extract_claims_from_paper
from scigraph.explorer import render_claim_graph_html
from scigraph.models import Paper
from solver import detect_contradictions, propose_falsifiable_experiments


def _build_sample_graph() -> tuple[ClaimGraph, int, int]:
    graph = ClaimGraph()
    text_a = (
        "Title: Metformin Effects\n"
        "DOI: 10.48550/arXiv.2401.10001\n"
        "Abstract: Treatment with Metformin under 37 C "
        "increased AMPK phosphorylation compared with control (n = 48, p = 0.002)."
    )
    text_b = (
        "Title: Metformin Null\n"
        "DOI: 10.48550/arXiv.2401.10002\n"
        "Abstract: Treatment with Metformin under 37 C "
        "decreased AMPK phosphorylation compared with control (n = 52, p = 0.004)."
    )
    for pid, doi, txt in (
        ("paper-a", "10.48550/arXiv.2401.10001", text_a),
        ("paper-b", "10.48550/arXiv.2401.10002", text_b),
    ):
        paper = Paper(
            paper_id=pid,
            doi=doi,
            title=f"Study {pid}",
            authors=("A. Researcher",),
            publication_year=2024,
            venue="arXiv",
            full_text=txt,
        )
        for claim in extract_claims_from_paper(paper):
            graph.add_verified_claim(paper, claim)
    graph.build_edges()
    contras = detect_contradictions(graph)
    return graph, len(contras), len(graph.edges)


def test_explorer_wcag_landmarks_and_viewport() -> None:
    graph, contra_count, edge_count = _build_sample_graph()
    contras = detect_contradictions(graph)
    exps = propose_falsifiable_experiments(contras)
    html_out = render_claim_graph_html(graph, contras, exps, None)

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html_out
    assert (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';"
        in html_out
    )
    assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in html_out
    assert ".skip-link:focus" in html_out
    assert '<main id="main-content" class="wrap">' in html_out
    assert (
        f"Showing {contra_count} of {contra_count} contradictions and "
        f"{edge_count} of {edge_count} evidence edges."
    ) in html_out


def test_explorer_live_search_and_aria_live_status() -> None:
    graph, _, _ = _build_sample_graph()
    contras = detect_contradictions(graph)
    exps = propose_falsifiable_experiments(contras)
    html_out = render_claim_graph_html(graph, contras, exps, None)

    assert (
        '<label for="claim-search" class="sr-only">Search claims and evidence</label>'
        in html_out
    )
    assert 'id="claim-search" type="search"' in html_out
    assert 'placeholder="Filter by intervention, condition, outcome, DOI..."' in html_out
    assert 'id="filter-status"' in html_out
    assert 'aria-live="polite"' in html_out
    assert "applyFilters()" in html_out
    assert "addEventListener('input'" in html_out


def test_explorer_responsive_table_scroll_region() -> None:
    graph, _, edge_count = _build_sample_graph()
    assert edge_count > 0
    contras = detect_contradictions(graph)
    exps = propose_falsifiable_experiments(contras)
    html_out = render_claim_graph_html(graph, contras, exps, None)

    assert "overflow-x: auto" in html_out
    assert (
        '<div class="table-scroll" role="region" aria-label="Evidence edges" tabindex="0">'
        '<table class="edge-table">'
    ) in html_out


def test_explorer_xss_escaping_and_empty_state() -> None:
    empty_html = render_claim_graph_html(ClaimGraph(), (), (), None)
    assert "empty-state" in empty_html
    assert '<main id="main-content" class="wrap">' in empty_html
    assert 'id="claim-search"' in empty_html
    assert 'id="filter-status"' in empty_html
    assert "No contradictions detected across verified claims." in empty_html
    assert "No evidence edges in graph." in empty_html

    xss_graph = ClaimGraph()
    xss_a = (
        'Title: <script>alert("xss")</script>\nDOI: 10.48550/arXiv.2401.99991\n'
        'Abstract: Treatment with <script>alert("xss")</script> under 28 C '
        "increased <img src=x> compared with control (n = 40, p = 0.01)."
    )
    xss_b = (
        'Title: <script>alert("xss")</script>\nDOI: 10.48550/arXiv.2401.99992\n'
        'Abstract: Treatment with <script>alert("xss")</script> under 28 C '
        "decreased <img src=x> compared with control (n = 40, p = 0.01)."
    )
    for pid, doi, txt in (
        ('xss-"a"', "10.48550/arXiv.2401.99991", xss_a),
        ('xss-"b"', "10.48550/arXiv.2401.99992", xss_b),
    ):
        paper = Paper(
            paper_id=pid,
            doi=doi,
            title='<script>alert("xss")</script>',
            authors=("Alice",),
            publication_year=2024,
            venue="arXiv",
            full_text=txt,
        )
        for claim in extract_claims_from_paper(paper):
            xss_graph.add_verified_claim(paper, claim)
    xss_graph.build_edges()
    xss_contras = detect_contradictions(xss_graph)
    xss_exps = propose_falsifiable_experiments(xss_contras)
    xss_html = render_claim_graph_html(xss_graph, xss_contras, xss_exps, None)

    assert '<script>alert("xss")</script>' not in xss_html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in xss_html
    assert "<img src=x>" not in xss_html
    assert "&lt;img src=x&gt;" in xss_html
    assert "xss-&quot;a&quot;" in xss_html
