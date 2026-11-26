import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.benchmark import BENCHMARK_30_PAPERS, evaluate_benchmark, run_benchmark_audit
from graph.claim_graph import ClaimGraph
from graph.store import GraphSQLiteStore, load_graph_json
from ingest.connectors import (  # noqa: F401 - re-exported for test monkeypatching
    fetch_arxiv_papers,
    fetch_europepmc_papers,
)
from ingest.corpus_loader import load_papers_from_path
from ingest.extractor import (
    extract_claims_from_paper,
    extract_paper_from_layout,
    extract_paper_from_pdf_bytes,
    render_blocks_to_pdf_bytes,
)
from ingest.verifier import verify_paper_claims
from scigraph.alerts import (  # noqa: F401 - re-exported for test monkeypatching
    dispatch_webhook_alert,
)
from scigraph.cli_handlers import (
    _SQLITE_SUFFIXES,
    _atomic_write_text,
    _cmd_alert,
    _cmd_canonicalize,
    _cmd_config,
    _cmd_consensus,
    _cmd_diagram,
    _cmd_diff,
    _cmd_doctor,
    _cmd_export_refs,
    _cmd_fetch,
    _cmd_pipeline,
    _cmd_prioritize,
    _cmd_protocols,
    _cmd_provenance,
    _cmd_serve,
    _cmd_workspace,
    _load_audit_events,  # noqa: F401 - re-exported for compatibility
    _load_graph_from_store,  # noqa: F401 - re-exported for compatibility
    _save_graph_to_store,
    _write_or_stdout,  # noqa: F401 - re-exported for compatibility
)
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import export_json_bundle, export_sarif_v210, render_markdown_report
from scigraph.models import (
    BenchmarkMetrics,
    ContradictionPair,
    EffectDirection,
    FalsifiableExperiment,
    Paper,
    PaperVerificationReport,
)
from scigraph.pipeline import OutputFormat
from scigraph.server import (  # noqa: F401 - re-exported for test monkeypatching
    create_http_server,
    run_server,
)
from solver.symbolic import detect_contradictions, propose_falsifiable_experiments

_PIPELINE_FORMATS: tuple[OutputFormat, ...] = (
    "markdown",
    "html",
    "sarif",
    "json",
    "bibtex",
    "ris",
)


def _cmd_benchmark(as_json: bool) -> int:
    metrics = evaluate_benchmark()
    if as_json:
        payload = json.dumps(metrics.model_dump(mode="json"), sort_keys=True, indent=2)
        sys.stdout.write(payload + "\n")
    else:
        sys.stdout.write(
            f"SciGraph Benchmark: papers={metrics.total_papers} "
            f"F1={metrics.f1_score:.4f} precision={metrics.precision:.4f} "
            f"recall={metrics.recall:.4f} fabricated_dois={metrics.fabricated_dois_accepted} "
            f"fabricated_p={metrics.fabricated_p_values_accepted} "
            f"decoys_rejected={metrics.adversarial_decoys_rejected} "
            f"contradictions={metrics.contradictions_detected} "
            f"elapsed_ms={metrics.elapsed_ms:.3f}\n"
        )
    passed = (
        metrics.f1_score >= 0.85
        and metrics.fabricated_dois_accepted == 0
        and metrics.fabricated_p_values_accepted == 0
    )
    return 0 if passed else 1


def _ingest_papers_into_graph(
    papers: Sequence[Paper],
) -> tuple[ClaimGraph, list[PaperVerificationReport]]:
    graph = ClaimGraph()
    reports: list[PaperVerificationReport] = []
    for paper in papers:
        graph.add_paper(paper)
        claims = extract_claims_from_paper(paper)
        report = verify_paper_claims(paper, claims)
        reports.append(report)
        for verified_claim in report.verified_claims:
            graph.add_verified_claim(paper, verified_claim)
    graph.build_edges()
    return graph, reports


def _render_report(
    fmt: str,
    graph: ClaimGraph,
    contradictions: Sequence[ContradictionPair],
    experiments: Sequence[FalsifiableExperiment],
    reports: Sequence[PaperVerificationReport],
    metrics: BenchmarkMetrics | None,
) -> str:
    if fmt == "markdown":
        return render_markdown_report(graph, contradictions, experiments, metrics)
    if fmt == "html":
        return render_claim_graph_html(graph, contradictions, experiments, metrics)
    if fmt == "sarif":
        return export_sarif_v210(contradictions, reports)
    return export_json_bundle(graph, contradictions, experiments, metrics)


def _cmd_verify(paper_id: str | None, input_path: str | None = None) -> int:
    if input_path is not None:
        try:
            papers = load_papers_from_path(Path(input_path))
        except (ValueError, OSError) as exc:
            sys.stderr.write(f"Failed to load corpus '{input_path}': {exc}\n")
            return 2
        all_ok = True
        for paper in papers:
            claims = extract_claims_from_paper(paper)
            report = verify_paper_claims(paper, claims)
            if not report.doi_verified or report.rejected_claim_ids:
                all_ok = False
            sys.stdout.write(
                f"{report.paper_id}: doi_verified={report.doi_verified} "
                f"verified={len(report.verified_claims)} "
                f"rejected={len(report.rejected_claim_ids)}\n"
            )
        return 0 if all_ok else 1

    specs_by_id = {spec.paper_id: spec for spec in BENCHMARK_30_PAPERS}
    if paper_id is not None and paper_id not in specs_by_id:
        sys.stderr.write(f"Unknown paper_id: {paper_id}\n")
        return 2

    target_specs = [specs_by_id[paper_id]] if paper_id is not None else list(BENCHMARK_30_PAPERS)
    all_ok = True
    for idx, spec in enumerate(target_specs):
        if paper_id is None and idx < 5:
            pdf_bytes = render_blocks_to_pdf_bytes(spec.blocks)
            paper = extract_paper_from_pdf_bytes(spec.paper_id, pdf_bytes)
        else:
            paper = extract_paper_from_layout(spec.paper_id, spec.blocks)
        claims = extract_claims_from_paper(paper)
        report = verify_paper_claims(paper, claims)
        if not report.doi_verified or report.rejected_claim_ids:
            all_ok = False
        sys.stdout.write(
            f"{report.paper_id}: doi_verified={report.doi_verified} "
            f"verified={len(report.verified_claims)} rejected={len(report.rejected_claim_ids)}\n"
        )
    return 0 if all_ok else 1


def _cmd_report(
    fmt: str,
    output: str | None,
    fail_on_contradictions: bool,
    input_path: str | None = None,
) -> int:
    if input_path is not None:
        try:
            papers = load_papers_from_path(Path(input_path))
        except (ValueError, OSError) as exc:
            sys.stderr.write(f"Failed to load corpus '{input_path}': {exc}\n")
            return 2
        graph, reports = _ingest_papers_into_graph(papers)
        contradictions = detect_contradictions(graph)
        experiments = propose_falsifiable_experiments(contradictions)
        rendered = _render_report(
            fmt=fmt,
            graph=graph,
            contradictions=contradictions,
            experiments=experiments,
            reports=reports,
            metrics=None,
        )
    else:
        bundle = run_benchmark_audit()
        reports = list(bundle.reports)
        contradictions = bundle.contradictions
        rendered = _render_report(
            fmt=fmt,
            graph=bundle.graph,
            contradictions=bundle.contradictions,
            experiments=bundle.experiments,
            reports=bundle.reports,
            metrics=bundle.metrics,
        )

    if output is not None:
        try:
            _atomic_write_text(Path(output), rendered)
        except OSError as exc:
            sys.stderr.write(f"Failed to write output file '{output}': {exc}\n")
            return 2
    else:
        sys.stdout.write(rendered)

    has_verify_failure = any(
        (not r.doi_verified) or bool(r.rejected_claim_ids) for r in reports
    )
    if has_verify_failure or (fail_on_contradictions and len(contradictions) > 0):
        return 1
    return 0


def _cmd_ingest(input_path: str, store: str, as_json: bool) -> int:
    store_path = Path(store)
    try:
        papers = load_papers_from_path(Path(input_path))
        graph, _ = _ingest_papers_into_graph(papers)
        _save_graph_to_store(graph, store_path)
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to ingest '{input_path}' to '{store}': {exc}\n")
        return 2

    if as_json:
        summary = {
            "papers": len(graph.papers),
            "verified_claims": len(graph.claims),
            "edges": len(graph.edges),
            "store": str(store_path),
        }
        sys.stdout.write(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Ingested papers={len(graph.papers)} "
            f"verified_claims={len(graph.claims)} "
            f"edges={len(graph.edges)} store={store_path}\n"
        )
    return 0


def _cmd_query(
    store: str,
    intervention: str | None,
    condition: str | None,
    outcome: str | None,
    direction: str | None,
    paper_id: str | None,
    as_json: bool,
) -> int:
    try:
        parsed_direction = EffectDirection(direction) if direction is not None else None
        store_path = Path(store)
        if not store_path.exists():
            raise ValueError(f"Store path does not exist: {store_path}")
        if not store_path.is_file():
            raise ValueError(f"Store path is not a file: {store_path}")
        suffix = store_path.suffix.lower()
        if suffix == ".json":
            matched = load_graph_json(store_path).query_claims(
                intervention=intervention,
                condition=condition,
                outcome=outcome,
                effect_direction=parsed_direction,
                paper_id=paper_id,
            )
        elif suffix in _SQLITE_SUFFIXES:
            matched = GraphSQLiteStore(store_path).query_claims(
                intervention=intervention,
                condition=condition,
                outcome=outcome,
                effect_direction=parsed_direction,
                paper_id=paper_id,
            )
        else:
            raise ValueError(
                f"Unsupported store extension {store_path.suffix!r} for {store_path}; "
                "expected .json, .db, .sqlite, or .sqlite3"
            )
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to query store '{store}': {exc}\n")
        return 2
    if as_json:
        payload = [claim.model_dump(mode="json") for claim in matched]
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    elif not matched:
        sys.stdout.write("No matching claims found.\n")
    else:
        for claim in matched:
            ct = claim.claim_tuple
            sys.stdout.write(
                f"{claim.claim_id} [{claim.paper_id}]: "
                f"{ct.intervention} ({ct.condition}) -> {ct.outcome} "
                f"[{ct.direction.value}] (n={claim.statistics.sample_size}, "
                f"p={claim.statistics.p_value:g})\n"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scigraph",
        description="SciGraph Neuro-Symbolic Scientific Discovery & Reasoning CLI",
    )
    parser.add_argument("--version", action="version", version="scigraph 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    bench_p = sub.add_parser("benchmark", help="Run the 30-paper benchmark evaluation.")
    bench_p.add_argument("--json", action="store_true", help="Emit BenchmarkMetrics as JSON.")

    verify_p = sub.add_parser("verify", help="Verify paper DOIs and verbatim claim spans.")
    verify_group = verify_p.add_mutually_exclusive_group()
    verify_group.add_argument(
        "--paper-id", type=str, default=None, help="Verify one benchmark paper."
    )
    verify_group.add_argument("--all", action="store_true", help="Verify all 30 benchmark papers.")
    verify_group.add_argument(
        "--input",
        type=str,
        default=None,
        help="Verify papers from a .json, .pdf, or corpus directory path.",
    )

    rep_p = sub.add_parser("report", help="Generate contradiction and experiment reports.")
    rep_p.add_argument(
        "--format",
        choices=("markdown", "html", "sarif", "json"),
        required=True,
        help="Output report format.",
    )
    rep_p.add_argument("--output", type=str, default=None, help="Optional output file path.")
    rep_p.add_argument(
        "--fail-on-contradictions",
        action="store_true",
        help="Return exit code 1 when contradictions are detected.",
    )
    rep_p.add_argument(
        "--input",
        type=str,
        default=None,
        help="Optional corpus path (.json, .pdf, or directory) instead of benchmark.",
    )

    ingest_p = sub.add_parser(
        "ingest",
        help="Ingest a corpus (.json, .pdf, or directory) and persist a ClaimGraph.",
    )
    ingest_p.add_argument(
        "input_path",
        type=str,
        help="Path to .json, .pdf, or corpus directory.",
    )
    ingest_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Destination store path (.json, .db, .sqlite, or .sqlite3).",
    )
    ingest_p.add_argument("--json", action="store_true", help="Emit ingestion summary as JSON.")

    query_p = sub.add_parser(
        "query",
        help="Query verified claims from a persisted ClaimGraph store.",
    )
    query_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    query_p.add_argument(
        "--intervention", type=str, default=None, help="Filter by intervention."
    )
    query_p.add_argument("--condition", type=str, default=None, help="Filter by condition.")
    query_p.add_argument("--outcome", type=str, default=None, help="Filter by outcome.")
    query_p.add_argument(
        "--direction",
        type=str,
        choices=tuple(d.value for d in EffectDirection),
        default=None,
        help="Filter by effect direction.",
    )
    query_p.add_argument("--paper-id", type=str, default=None, help="Filter by paper ID.")
    query_p.add_argument("--json", action="store_true", help="Emit matching claims as JSON.")

    serve_p = sub.add_parser("serve", help="Start the local SciGraph HTTP/REST API server.")
    serve_p.add_argument("--host", type=str, default="127.0.0.1", help="Bind host address.")
    serve_p.add_argument("--port", type=int, default=8765, help="Bind port number.")
    serve_p.add_argument(
        "--store",
        type=str,
        default=None,
        help="Optional store path (.json, .db, .sqlite, or .sqlite3) to preload.",
    )
    serve_p.add_argument(
        "--tokens",
        type=str,
        default=None,
        help="Optional JSON file of Bearer TokenPolicy entries.",
    )
    serve_p.add_argument(
        "--rate-limit",
        type=int,
        default=None,
        help="Optional max requests per client within --rate-window seconds.",
    )
    serve_p.add_argument(
        "--rate-window",
        type=float,
        default=60.0,
        help="Sliding rate-limit window duration in seconds (default: 60.0).",
    )
    serve_p.add_argument(
        "--workspace-root",
        type=str,
        default=None,
        help="Optional multi-tenant workspace root directory.",
    )
    serve_p.add_argument(
        "--org",
        type=str,
        default=None,
        help="Optional organization ID slug for workspace-backed serving.",
    )
    serve_p.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Optional workspace ID slug for workspace-backed serving.",
    )

    consensus_p = sub.add_parser(
        "consensus",
        help="Compute topic consensus and claim evidence scores for a persisted store.",
    )
    consensus_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    consensus_p.add_argument(
        "--json", action="store_true", help="Emit consensus and claim scores as JSON."
    )

    diff_p = sub.add_parser(
        "diff",
        help="Compare baseline and current ClaimGraph stores.",
    )
    diff_p.add_argument(
        "--baseline",
        type=str,
        required=True,
        help="Baseline store path (.json, .db, .sqlite, or .sqlite3).",
    )
    diff_p.add_argument(
        "--current",
        type=str,
        required=True,
        help="Current store path (.json, .db, .sqlite, or .sqlite3).",
    )
    diff_p.add_argument("--json", action="store_true", help="Emit GraphDiff as JSON.")

    export_refs_p = sub.add_parser(
        "export-refs",
        help="Export papers from a persisted store as BibTeX or RIS.",
    )
    export_refs_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    export_refs_p.add_argument(
        "--format",
        choices=("bibtex", "ris"),
        required=True,
        help="Reference export format.",
    )
    export_refs_p.add_argument("--output", type=str, default=None, help="Optional output file.")

    ws_p = sub.add_parser(
        "workspace",
        help="Manage multi-tenant isolated workspaces and audit logs.",
    )
    ws_sub = ws_p.add_subparsers(dest="ws_action", required=True)

    ws_init = ws_sub.add_parser("init", help="Initialize a new tenant workspace.")
    ws_init.add_argument("--root", type=str, required=True, help="Workspace root directory.")
    ws_init.add_argument("--org", type=str, required=True, help="Organization ID slug.")
    ws_init.add_argument("--workspace", type=str, required=True, help="Workspace ID slug.")
    ws_init.add_argument("--name", type=str, required=True, help="Human-readable workspace name.")
    ws_init.add_argument("--json", action="store_true", help="Emit WorkspaceConfig as JSON.")

    ws_ingest = ws_sub.add_parser("ingest", help="Ingest a corpus into a tenant workspace.")
    ws_ingest.add_argument("--root", type=str, required=True, help="Workspace root directory.")
    ws_ingest.add_argument("--org", type=str, required=True, help="Organization ID slug.")
    ws_ingest.add_argument("--workspace", type=str, required=True, help="Workspace ID slug.")
    ws_ingest.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to .json, .pdf, or corpus directory.",
    )
    ws_ingest.add_argument("--json", action="store_true", help="Emit ingestion summary as JSON.")

    ws_audit = ws_sub.add_parser("audit", help="Read a tenant workspace audit log.")
    ws_audit.add_argument("--root", type=str, required=True, help="Workspace root directory.")
    ws_audit.add_argument("--org", type=str, required=True, help="Organization ID slug.")
    ws_audit.add_argument("--workspace", type=str, required=True, help="Workspace ID slug.")
    ws_audit.add_argument("--json", action="store_true", help="Emit audit events as JSON.")

    fetch_p = sub.add_parser("fetch", help="Fetch papers from external scientific APIs.")
    fetch_p.add_argument(
        "--source",
        choices=("arxiv", "europepmc"),
        required=True,
        help="External paper source API.",
    )
    fetch_p.add_argument("--query", type=str, required=True, help="Search query string.")
    fetch_p.add_argument("--output", type=str, required=True, help="Output JSON corpus path.")
    fetch_p.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of papers to fetch (1-100).",
    )

    prov_p = sub.add_parser(
        "provenance",
        help="Build and verify cryptographic provenance manifests.",
    )
    prov_sub = prov_p.add_subparsers(dest="prov_action", required=True)

    prov_build = prov_sub.add_parser("build", help="Build a provenance manifest for a store.")
    prov_build.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    prov_build.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output manifest JSON path.",
    )
    prov_build.add_argument(
        "--audit-log",
        type=str,
        default=None,
        help="Optional audit.jsonl path to chain into the manifest.",
    )

    prov_verify = prov_sub.add_parser(
        "verify",
        help="Verify a store against a provenance manifest.",
    )
    prov_verify.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    prov_verify.add_argument(
        "--manifest",
        type=str,
        required=True,
        help="Manifest JSON path.",
    )
    prov_verify.add_argument(
        "--audit-log",
        type=str,
        default=None,
        help="Optional audit.jsonl path to verify against the manifest.",
    )
    prov_verify.add_argument(
        "--json",
        action="store_true",
        help="Emit verification result as JSON.",
    )

    pipe_p = sub.add_parser(
        "pipeline",
        help="Run the end-to-end SciGraph batch pipeline.",
    )
    pipe_p.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to .json, .pdf, or corpus directory.",
    )
    pipe_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Destination store path (.json, .db, .sqlite, or .sqlite3).",
    )
    pipe_p.add_argument(
        "--report-dir",
        type=str,
        required=True,
        help="Output directory for generated reports and summary.json.",
    )
    pipe_p.add_argument(
        "--format",
        nargs="+",
        choices=_PIPELINE_FORMATS,
        default=["markdown", "sarif", "json"],
        help="Report output formats.",
    )
    pipe_p.add_argument(
        "--fail-on-contradictions",
        action="store_true",
        help="Return exit code 1 when contradictions are detected.",
    )
    pipe_p.add_argument(
        "--min-verified-papers",
        type=int,
        default=1,
        help="Minimum number of verified papers required to pass.",
    )
    pipe_p.add_argument("--json", action="store_true", help="Emit PipelineSummary as JSON.")

    prioritize_p = sub.add_parser(
        "prioritize",
        help="Rank falsifiable experiments for detected contradictions.",
    )
    prioritize_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    prioritize_p.add_argument(
        "--json",
        action="store_true",
        help="Emit prioritized experiments as JSON.",
    )

    canonicalize_p = sub.add_parser(
        "canonicalize",
        help="Find canonical entity clusters across surface-form aliases.",
    )
    canonicalize_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    canonicalize_p.add_argument(
        "--json",
        action="store_true",
        help="Emit canonical clusters as JSON.",
    )

    alert_p = sub.add_parser(
        "alert",
        help="Build or dispatch a structured webhook alert from a ClaimGraph store.",
    )
    alert_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    alert_p.add_argument(
        "--webhook-url",
        type=str,
        default=None,
        help="Optional HTTPS webhook URL to POST the alert payload.",
    )
    alert_p.add_argument(
        "--json",
        action="store_true",
        help="Emit AlertPayload or dispatch result as JSON.",
    )

    diagram_p = sub.add_parser(
        "diagram",
        help="Export a ClaimGraph as a Mermaid flowchart or Graphviz DOT digraph.",
    )
    diagram_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    diagram_p.add_argument(
        "--format",
        choices=("mermaid", "dot"),
        required=True,
        help="Diagram output format.",
    )
    diagram_p.add_argument("--output", type=str, default=None, help="Optional output file.")

    protocols_p = sub.add_parser(
        "protocols",
        help="Generate lab-ready falsifiable experiment protocols for contradictions.",
    )
    protocols_p.add_argument(
        "--store",
        type=str,
        required=True,
        help="Source store path (.json, .db, .sqlite, or .sqlite3).",
    )
    protocols_p.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Protocol output format (default: markdown).",
    )
    protocols_p.add_argument("--output", type=str, default=None, help="Optional output file.")

    doctor_p = sub.add_parser(
        "doctor",
        help="Run system diagnostics and self-checks.",
    )
    doctor_p.add_argument(
        "--workspace-root",
        type=str,
        default=None,
        help="Optional workspace root directory to check writability.",
    )
    doctor_p.add_argument(
        "--json",
        action="store_true",
        help="Emit DoctorReport as JSON.",
    )

    config_p = sub.add_parser(
        "config",
        help="Load and inspect SciGraph TOML configuration.",
    )
    config_p.add_argument(
        "--path",
        type=str,
        default=None,
        help="Optional path to scigraph.toml.",
    )
    config_p.add_argument(
        "--json",
        action="store_true",
        help="Emit SciGraphConfig as JSON.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return 0 if code == 0 else 2

    if args.command == "benchmark":
        return _cmd_benchmark(as_json=bool(args.json))
    if args.command == "verify":
        return _cmd_verify(paper_id=args.paper_id, input_path=args.input)
    if args.command == "report":
        return _cmd_report(
            fmt=str(args.format),
            output=args.output,
            fail_on_contradictions=bool(args.fail_on_contradictions),
            input_path=args.input,
        )
    if args.command == "ingest":
        return _cmd_ingest(
            input_path=str(args.input_path),
            store=str(args.store),
            as_json=bool(args.json),
        )
    if args.command == "query":
        return _cmd_query(
            store=str(args.store),
            intervention=args.intervention,
            condition=args.condition,
            outcome=args.outcome,
            direction=args.direction,
            paper_id=args.paper_id,
            as_json=bool(args.json),
        )
    if args.command == "serve":
        return _cmd_serve(
            host=str(args.host),
            port=int(args.port),
            store=args.store,
            tokens=args.tokens,
            rate_limit=args.rate_limit,
            rate_window=float(args.rate_window),
            workspace_root=args.workspace_root,
            org=args.org,
            workspace=args.workspace,
        )
    if args.command == "consensus":
        return _cmd_consensus(
            store=str(args.store),
            as_json=bool(args.json),
        )
    if args.command == "diff":
        return _cmd_diff(
            baseline=str(args.baseline),
            current=str(args.current),
            as_json=bool(args.json),
        )
    if args.command == "export-refs":
        return _cmd_export_refs(
            store=str(args.store),
            fmt=str(args.format),
            output=args.output,
        )
    if args.command == "workspace":
        return _cmd_workspace(args)
    if args.command == "fetch":
        return _cmd_fetch(
            source=str(args.source),
            query=str(args.query),
            output=str(args.output),
            max_results=int(args.max_results),
        )
    if args.command == "provenance":
        return _cmd_provenance(args)
    if args.command == "pipeline":
        return _cmd_pipeline(args)
    if args.command == "prioritize":
        return _cmd_prioritize(store=str(args.store), as_json=bool(args.json))
    if args.command == "canonicalize":
        return _cmd_canonicalize(store=str(args.store), as_json=bool(args.json))
    if args.command == "alert":
        return _cmd_alert(
            store=str(args.store),
            webhook_url=args.webhook_url,
            as_json=bool(args.json),
        )
    if args.command == "diagram":
        return _cmd_diagram(
            store=str(args.store),
            fmt=str(args.format),
            output=args.output,
        )
    if args.command == "protocols":
        return _cmd_protocols(
            store=str(args.store),
            fmt=str(args.format),
            output=args.output,
        )
    if args.command == "doctor":
        return _cmd_doctor(
            workspace_root=args.workspace_root,
            as_json=bool(args.json),
        )
    if args.command == "config":
        return _cmd_config(
            path=args.path,
            as_json=bool(args.json),
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
