import argparse
from collections.abc import Sequence

from ingest.connectors import (  # noqa: F401 - re-exported for test monkeypatching
    fetch_arxiv_papers,
    fetch_europepmc_papers,
)
from scigraph.alerts import (  # noqa: F401 - re-exported for test monkeypatching
    dispatch_webhook_alert,
)
from scigraph.cli_handlers import (
    _SQLITE_SUFFIXES,  # noqa: F401 - re-exported for compatibility
    _atomic_write_text,  # noqa: F401 - re-exported for compatibility
    _cmd_alert,
    _cmd_benchmark,
    _cmd_canonicalize,
    _cmd_config,
    _cmd_consensus,
    _cmd_diagram,
    _cmd_diff,
    _cmd_doctor,
    _cmd_export_refs,
    _cmd_fetch,
    _cmd_ingest,
    _cmd_pipeline,
    _cmd_prioritize,
    _cmd_protocols,
    _cmd_provenance,
    _cmd_query,
    _cmd_report,
    _cmd_serve,
    _cmd_verify,
    _cmd_workspace,
    _ingest_papers_into_graph,  # noqa: F401 - re-exported for compatibility
    _load_audit_events,  # noqa: F401 - re-exported for compatibility
    _load_graph_from_store,  # noqa: F401 - re-exported for compatibility
    _render_report,  # noqa: F401 - re-exported for compatibility
    _save_graph_to_store,  # noqa: F401 - re-exported for compatibility
    _write_or_stdout,  # noqa: F401 - re-exported for compatibility
)
from scigraph.models import EffectDirection
from scigraph.pipeline import OutputFormat
from scigraph.server import (  # noqa: F401 - re-exported for test monkeypatching
    create_http_server,
    run_server,
)

_PIPELINE_FORMATS: tuple[OutputFormat, ...] = (
    "markdown",
    "html",
    "sarif",
    "json",
    "bibtex",
    "ris",
)


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
        default=None,
        help="Sliding rate-limit window duration in seconds (default: config or 60.0).",
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
    ws_audit.add_argument(
        "--action",
        choices=("ingest", "verify", "query", "export", "contradiction_scan"),
        default=None,
        help="Filter audit events by action.",
    )
    ws_audit.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of most-recent audit events to return (>= 1).",
    )
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
            rate_window=float(args.rate_window) if args.rate_window is not None else None,
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
