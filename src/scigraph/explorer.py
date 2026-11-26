import html
from collections.abc import Sequence

from graph.claim_graph import ClaimGraph
from scigraph.models import (
    BenchmarkMetrics,
    ContradictionKind,
    ContradictionPair,
    EdgeRelation,
    FalsifiableExperiment,
    ScientificClaim,
)

_CSP_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';"
)

_STYLESHEET = """
  :root {
    --bg: #0b1120; --surface: #111827; --border: #1f2937; --text: #f8fafc;
    --muted: #94a3b8; --accent: #38bdf8; --warn: #f59e0b; --danger: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
  }
  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
  }
  .skip-link {
    position: absolute; left: -9999px; top: auto; width: 1px; height: 1px;
    overflow: hidden;
  }
  .skip-link:focus, .skip-link:focus-visible {
    position: fixed; left: 16px; top: 16px; width: auto; height: auto;
    overflow: visible; padding: 8px 14px; background: var(--accent);
    color: #0b1120; font-weight: 700; border-radius: 6px; z-index: 1000;
    text-decoration: none; outline: 2px solid #f8fafc; outline-offset: 2px;
  }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }
  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-variant-numeric: tabular-nums;
  }
  h1, h2 { margin: 0 0 12px; }
  .kpis {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px; margin: 16px 0 28px;
  }
  .kpi {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px;
  }
  .kpi-val { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
  .kpi-lbl { font-size: 0.82rem; color: var(--muted); }
  .filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .search-wrap { margin-bottom: 14px; }
  #claim-search {
    width: 100%; max-width: 520px; padding: 9px 12px; border-radius: 6px;
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    font-size: 0.9rem;
  }
  #claim-search::placeholder { color: var(--muted); }
  #claim-search:focus-visible {
    outline: 2px solid var(--accent); outline-offset: 2px; border-color: var(--accent);
  }
  .filter-status { margin-bottom: 18px; }
  .filter-btn {
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 0.82rem;
  }
  .filter-btn[aria-pressed="true"] { border-color: var(--accent); background: #0c4a6e; }
  .filter-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; margin-bottom: 16px; overflow-wrap: anywhere;
  }
  .card-head {
    display: flex; justify-content: space-between; align-items: center;
    gap: 8px; margin-bottom: 8px;
  }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 0.75rem; border: 1px solid var(--border); background: #1e293b;
  }
  .badge-direct_direction_conflict { border-color: var(--danger); color: #fca5a5; }
  .badge-null_vs_significant_conflict { border-color: var(--warn); color: #fcd34d; }
  .badge-condition_dependent_divergence { border-color: var(--accent); color: #bae6fd; }
  .factor { font-size: 0.92rem; color: #e2e8f0; margin-bottom: 8px; }
  .unsat-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .unsat-chip {
    font-size: 0.75rem; background: #0f172a; border: 1px solid var(--border);
    padding: 2px 6px; border-radius: 4px; color: #cbd5e1;
  }
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 768px) { .split { grid-template-columns: 1fr; } }
  .claim-pane {
    background: #0f172a; border: 1px solid var(--border);
    border-radius: 6px; padding: 12px;
  }
  .pane-head {
    display: flex; justify-content: space-between; gap: 8px;
    font-size: 0.85rem; margin-bottom: 6px;
  }
  .doi { color: var(--accent); }
  .claim-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .pill { font-size: 0.75rem; background: #1e293b; padding: 2px 7px; border-radius: 4px; }
  .condition { font-size: 0.85rem; margin: 6px 0; }
  .quote {
    margin: 8px 0 0; padding: 8px 10px; border-left: 3px solid var(--accent);
    background: #111827; font-size: 0.85rem;
  }
  .offset { font-size: 0.72rem; color: var(--muted); margin-bottom: 4px; }
  .exp-box {
    margin-top: 12px; padding: 10px 12px; border-radius: 6px;
    background: #06281e; border: 1px solid #065f46; font-size: 0.86rem;
  }
  .exp-box p { margin: 4px 0; }
  .table-scroll {
    overflow-x: auto; -webkit-overflow-scrolling: touch;
    border: 1px solid var(--border); border-radius: 8px;
  }
  .table-scroll:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .edge-table {
    width: 100%; min-width: 640px; border-collapse: collapse; font-size: 0.85rem;
    background: var(--surface);
  }
  .edge-table th, .edge-table td {
    padding: 8px 10px; border-bottom: 1px solid var(--border);
    text-align: left; overflow-wrap: anywhere;
  }
  .empty-state, .filter-empty-banner {
    padding: 14px; border: 1px dashed var(--border); border-radius: 8px;
    color: var(--muted); margin-bottom: 16px;
  }
  .hidden { display: none; }
"""

_SCRIPT = """
const filterState = { contra: 'ALL', edge: 'ALL', query: '' };

function applyFilters() {
  const q = filterState.query;
  const contraEls = document.querySelectorAll('.contra-card');
  let contraVisible = 0;
  contraEls.forEach((el) => {
    const kindMatch = filterState.contra === 'ALL' || el.dataset.kind === filterState.contra;
    const textMatch = q === '' || (el.textContent || '').toLowerCase().includes(q);
    const match = kindMatch && textMatch;
    el.classList.toggle('hidden', !match);
    if (match) contraVisible += 1;
  });
  const contraBanner = document.getElementById('contra-empty-filter');
  if (contraBanner) {
    contraBanner.classList.toggle('hidden', contraVisible > 0 || contraEls.length === 0);
  }

  const edgeEls = document.querySelectorAll('.edge-row');
  let edgeVisible = 0;
  edgeEls.forEach((el) => {
    const relMatch = filterState.edge === 'ALL' || el.dataset.relation === filterState.edge;
    const textMatch = q === '' || (el.textContent || '').toLowerCase().includes(q);
    const match = relMatch && textMatch;
    el.classList.toggle('hidden', !match);
    if (match) edgeVisible += 1;
  });
  const edgeBanner = document.getElementById('edge-empty-filter');
  if (edgeBanner) {
    edgeBanner.classList.toggle('hidden', edgeVisible > 0 || edgeEls.length === 0);
  }

  const statusEl = document.getElementById('filter-status');
  if (statusEl) {
    statusEl.textContent =
      'Showing ' + contraVisible + ' of ' + contraEls.length +
      ' contradictions and ' + edgeVisible + ' of ' + edgeEls.length +
      ' evidence edges.';
  }
}

document.querySelectorAll('.filter-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const group = btn.dataset.group;
    const filter = btn.dataset.filter || 'ALL';
    const groupBtns = '.filter-btn[data-group="' + group + '"]';
    document.querySelectorAll(groupBtns).forEach((b) => {
      b.setAttribute('aria-pressed', String(b === btn));
    });
    if (group === 'contra' || group === 'edge') {
      filterState[group] = filter;
    }
    applyFilters();
  });
});

const searchInput = document.getElementById('claim-search');
if (searchInput) {
  searchInput.addEventListener('input', () => {
    filterState.query = searchInput.value.trim().toLowerCase();
    applyFilters();
  });
}
"""


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _render_claim_pane(label: str, claim: ScientificClaim) -> str:
    stats = claim.statistics
    effect_badge = (
        f'<span class="pill">{_esc(stats.effect_size_raw)}</span>'
        if stats.effect_size_raw
        else ""
    )
    span = claim.evidence_span
    return (
        f'<div class="claim-pane">'
        f'<div class="pane-head">'
        f'<span class="pane-label">{_esc(label)}</span>'
        f'<span class="mono doi">{_esc(claim.doi)}</span>'
        f"</div>"
        f'<div class="claim-meta">'
        f'<span class="pill">{_esc(claim.claim_tuple.direction.value)}</span>'
        f'<span class="pill mono">{_esc(stats.sample_size_raw)}</span>'
        f'<span class="pill mono">{_esc(stats.p_value_raw)}</span>'
        f"{effect_badge}"
        f"</div>"
        f'<p class="condition"><strong>Condition:</strong> {_esc(claim.claim_tuple.condition)}</p>'
        f'<blockquote class="quote">'
        f'<div class="offset mono">[{_esc(span.section.value)} '
        f"{span.start_char}:{span.end_char}]</div>"
        f"{_esc(span.verbatim_text)}"
        f"</blockquote>"
        f"</div>"
    )


def render_claim_graph_html(
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair],
    experiments: Sequence[FalsifiableExperiment],
    metrics: BenchmarkMetrics | None = None,
) -> str:
    exp_by_contra = {e.contradiction_id: e for e in experiments}

    f1_kpi = (
        f'<div class="kpi"><div class="kpi-val mono">{metrics.f1_score:.4f}</div>'
        f'<div class="kpi-lbl">Benchmark F1 ({metrics.adversarial_decoys_rejected} '
        f"decoys rejected)</div></div>"
        if metrics is not None
        else ""
    )

    contra_cards: list[str] = []
    for pair in contradictions:
        exp = exp_by_contra.get(pair.contradiction_id)
        unsat_html = "".join(
            f'<code class="unsat-chip">{_esc(u)}</code>' for u in pair.unsat_constraints
        )
        exp_html = (
            f'<div class="exp-box">'
            f'<div class="exp-title">Proposed Experiment <code>{_esc(exp.experiment_id)}</code> '
            f'(<span class="mono">n = {exp.recommended_sample_size}</span>, '
            f'<span class="mono">alpha = {exp.alpha_threshold:.2f}</span>)</div>'
            f"<p><strong>Hypothesis:</strong> {_esc(exp.hypothesis)}</p>"
            f"<p><strong>Falsification:</strong> {_esc(exp.falsification_criterion)}</p>"
            f"</div>"
            if exp is not None
            else ""
        )
        contra_cards.append(
            f'<article class="card contra-card" data-kind="{_esc(pair.kind.value)}">'
            f'<header class="card-head">'
            f'<span class="mono">{_esc(pair.contradiction_id)}</span>'
            f'<span class="badge badge-{_esc(pair.kind.value)}">{_esc(pair.kind.value)}</span>'
            f"</header>"
            f'<div class="factor">{_esc(pair.discriminating_factor)}</div>'
            f'<div class="unsat-row">{unsat_html}</div>'
            f'<div class="split">'
            f'{_render_claim_pane("Claim A (" + pair.claim_a.paper_id + ")", pair.claim_a)}'
            f'{_render_claim_pane("Claim B (" + pair.claim_b.paper_id + ")", pair.claim_b)}'
            f"</div>"
            f"{exp_html}"
            f"</article>"
        )

    contra_section_body = (
        "".join(contra_cards)
        if contra_cards
        else '<div class="empty-state">No contradictions detected across verified claims.</div>'
    )

    edge_rows: list[str] = []
    for edge in graph.edges:
        edge_rows.append(
            f'<tr class="edge-row" data-relation="{_esc(edge.relation.value)}">'
            f'<td class="mono">{_esc(edge.edge_id)}</td>'
            f'<td><span class="badge">{_esc(edge.relation.value)}</span></td>'
            f'<td class="mono">{_esc(edge.source_claim_id)} &rarr; '
            f"{_esc(edge.target_claim_id)}</td>"
            f"<td>{_esc(edge.shared_intervention)} / {_esc(edge.shared_outcome)}</td>"
            f"<td>{_esc(edge.rationale)}</td>"
            f"</tr>"
        )

    edge_section_body = (
        '<div class="table-scroll" role="region" aria-label="Evidence edges" tabindex="0">'
        '<table class="edge-table"><thead><tr>'
        "<th>ID</th><th>Relation</th><th>Claims</th>"
        "<th>Intervention / Outcome</th><th>Rationale</th>"
        f'</tr></thead><tbody>{"".join(edge_rows)}</tbody></table></div>'
        if edge_rows
        else '<div class="empty-state">No evidence edges in graph.</div>'
    )

    contra_buttons = "".join(
        f'<button type="button" class="filter-btn" data-group="contra" '
        f'data-filter="{_esc(k.value)}" aria-pressed="false">{_esc(k.value)}</button>'
        for k in ContradictionKind
    )
    edge_buttons = "".join(
        f'<button type="button" class="filter-btn" data-group="edge" '
        f'data-filter="{_esc(r.value)}" aria-pressed="false">{_esc(r.value)}</button>'
        for r in EdgeRelation
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP_POLICY}">\n'
        "<title>SciGraph Claim-Graph &amp; Contradiction Studio</title>\n"
        f"<style>{_STYLESHEET}</style>\n"
        "</head>\n"
        "<body>\n"
        '<a class="skip-link" href="#main-content">Skip to main content</a>\n'
        '<main id="main-content" class="wrap">\n'
        "  <header>\n"
        "    <h1>SciGraph Claim-Graph &amp; Contradiction Studio</h1>\n"
        '    <p class="kpi-lbl">Deterministic verbatim-verified scientific claims, '
        "UNSAT contradiction cores, and falsifiable experiment designs.</p>\n"
        "  </header>\n"
        '  <section class="kpis" aria-label="Corpus metrics">\n'
        f'    <div class="kpi"><div class="kpi-val mono">{len(graph.papers)}</div>'
        '<div class="kpi-lbl">Papers Audited</div></div>\n'
        f'    <div class="kpi"><div class="kpi-val mono">{len(graph.claims)}</div>'
        '<div class="kpi-lbl">Verified Claims</div></div>\n'
        f'    <div class="kpi"><div class="kpi-val mono">{len(graph.edges)}</div>'
        '<div class="kpi-lbl">Evidence Edges</div></div>\n'
        f'    <div class="kpi"><div class="kpi-val mono">{len(contradictions)}</div>'
        '<div class="kpi-lbl">Contradictions</div></div>\n'
        f'    <div class="kpi"><div class="kpi-val mono">{len(experiments)}</div>'
        '<div class="kpi-lbl">Proposed Experiments</div></div>\n'
        f"    {f1_kpi}\n"
        "  </section>\n"
        '  <div class="search-wrap">\n'
        '    <label for="claim-search" class="sr-only">Search claims and evidence</label>\n'
        '    <input id="claim-search" type="search" '
        'placeholder="Filter by intervention, condition, outcome, DOI..." '
        'autocomplete="off">\n'
        "  </div>\n"
        '  <div id="filter-status" class="filter-status kpi-lbl" '
        'aria-live="polite" aria-atomic="true">'
        f"Showing {len(contradictions)} of {len(contradictions)} contradictions and "
        f"{len(graph.edges)} of {len(graph.edges)} evidence edges.</div>\n"
        '  <section aria-label="Contradiction Studio">\n'
        "    <h2>Contradiction &amp; Experiment Studio</h2>\n"
        '    <div class="filters" role="group" aria-label="Filter contradictions">\n'
        '      <button type="button" class="filter-btn" data-group="contra" '
        'data-filter="ALL" aria-pressed="true">ALL</button>\n'
        f"      {contra_buttons}\n"
        "    </div>\n"
        '    <div id="contra-empty-filter" class="filter-empty-banner hidden">'
        "No items match the selected filter.</div>\n"
        f"    {contra_section_body}\n"
        "  </section>\n"
        '  <section aria-label="Evidence Edge Explorer">\n'
        "    <h2>Evidence Edge Explorer</h2>\n"
        '    <div class="filters" role="group" aria-label="Filter edges">\n'
        '      <button type="button" class="filter-btn" data-group="edge" '
        'data-filter="ALL" aria-pressed="true">ALL</button>\n'
        f"      {edge_buttons}\n"
        "    </div>\n"
        '    <div id="edge-empty-filter" class="filter-empty-banner hidden">'
        "No items match the selected filter.</div>\n"
        f"    {edge_section_body}\n"
        "  </section>\n"
        "</main>\n"
        f"<script>{_SCRIPT}</script>\n"
        "</body>\n"
        "</html>\n"
    )
