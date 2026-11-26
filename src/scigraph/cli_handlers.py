"""Extracted Wave 4-7 CLI subcommand handlers and shared I/O helpers."""

import argparse
import http.client
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from evals.benchmark import BENCHMARK_30_PAPERS, evaluate_benchmark, run_benchmark_audit
from graph.canonicalizer import EntityCanonicalizer
from graph.claim_graph import ClaimGraph
from graph.scoring import compute_topic_consensus, score_claim_evidence
from graph.store import GraphSQLiteStore, load_graph_json, save_graph_json
from ingest.connectors import fetch_arxiv_papers, fetch_europepmc_papers
from ingest.corpus_loader import load_papers_from_path
from ingest.extractor import (
    extract_claims_from_paper,
    extract_paper_from_layout,
    extract_paper_from_pdf_bytes,
    render_blocks_to_pdf_bytes,
)
from ingest.verifier import verify_paper_claims
from scigraph.alerts import build_alert_payload, dispatch_webhook_alert
from scigraph.config import load_scigraph_config
from scigraph.diagrams import export_graphviz_dot, export_mermaid_flowchart
from scigraph.diff import diff_claim_graphs, export_bibtex, export_ris
from scigraph.doctor import run_doctor
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import export_json_bundle, export_sarif_v210, render_markdown_report
from scigraph.io_utils import atomic_write_text
from scigraph.models import (
    BenchmarkMetrics,
    ContradictionPair,
    EffectDirection,
    FalsifiableExperiment,
    Paper,
    PaperVerificationReport,
)
from scigraph.pipeline import OutputFormat, PipelineConfig, run_pipeline
from scigraph.provenance import (
    ProvenanceManifest,
    build_provenance_manifest,
    verify_provenance_manifest,
)
from scigraph.security import AuthGate, SlidingWindowRateLimiter
from scigraph.server import (
    SciGraphApp,
    create_http_server,
    load_token_policies,
    run_server,
)
from scigraph.workspace import AuditEvent, WorkspaceAction, WorkspaceManager
from solver.prioritizer import prioritize_experiments
from solver.protocols import generate_experiment_protocols, render_protocols_markdown
from solver.symbolic import detect_contradictions, propose_falsifiable_experiments

_SQLITE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})


def _resolve_cli_attr[T](name: str, default: T) -> T:
    """Resolve an attribute from ``scigraph.cli`` when loaded so monkeypatches apply."""
    cli_mod = sys.modules.get("scigraph.cli")
    if cli_mod is not None and hasattr(cli_mod, name):
        return cast(T, getattr(cli_mod, name))
    return default


def _atomic_write_text(output_path: Path, content: str) -> None:
    """Atomically write UTF-8 text to ``output_path`` via shared helper."""
    atomic_write_text(output_path, content)


def _save_graph_to_store(graph: ClaimGraph, store_path: Path) -> None:
    suffix = store_path.suffix.lower()
    if suffix == ".json":
        save_graph_json(graph, store_path)
        return
    if suffix in _SQLITE_SUFFIXES:
        GraphSQLiteStore(store_path).save_graph(graph)
        return
    raise ValueError(
        f"Unsupported store extension {store_path.suffix!r} for {store_path}; "
        "expected .json, .db, .sqlite, or .sqlite3"
    )


def _load_graph_from_store(store_path: Path) -> ClaimGraph:
    if not store_path.exists():
        raise ValueError(f"Store path does not exist: {store_path}")
    if not store_path.is_file():
        raise ValueError(f"Store path is not a file: {store_path}")
    suffix = store_path.suffix.lower()
    if suffix == ".json":
        return load_graph_json(store_path)
    if suffix in _SQLITE_SUFFIXES:
        return GraphSQLiteStore(store_path).load_graph()
    raise ValueError(
        f"Unsupported store extension {store_path.suffix!r} for {store_path}; "
        "expected .json, .db, .sqlite, or .sqlite3"
    )


def _load_audit_events(audit_log: str | None) -> list[AuditEvent]:
    if audit_log is None:
        return []
    audit_path = Path(audit_log)
    events: list[AuditEvent] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            events.append(AuditEvent.model_validate_json(stripped))
    return events


def _write_or_stdout(rendered: str, output: str | None) -> int:
    if output is not None:
        try:
            _atomic_write_text(Path(output), rendered)
        except OSError as exc:
            sys.stderr.write(f"Failed to write output file '{output}': {exc}\n")
            return 2
    else:
        sys.stdout.write(rendered)
    return 0


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
            try:
                claims = extract_claims_from_paper(paper)
                report = verify_paper_claims(paper, claims)
            except (ValueError, OSError) as exc:
                sys.stderr.write(f"Failed to verify paper '{paper.paper_id}': {exc}\n")
                return 2
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
        try:
            if paper_id is None and idx < 5:
                pdf_bytes = render_blocks_to_pdf_bytes(spec.blocks)
                paper = extract_paper_from_pdf_bytes(spec.paper_id, pdf_bytes)
            else:
                paper = extract_paper_from_layout(spec.paper_id, spec.blocks)
            claims = extract_claims_from_paper(paper)
            report = verify_paper_claims(paper, claims)
        except (ValueError, OSError) as exc:
            sys.stderr.write(f"Failed to verify paper '{spec.paper_id}': {exc}\n")
            return 2
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
                f"{claim.statistics.p_value_raw})\n"
            )
    return 0


def _cmd_serve(
    host: str,
    port: int,
    store: str | None,
    tokens: str | None = None,
    rate_limit: int | None = None,
    rate_window: float | None = None,
    workspace_root: str | None = None,
    org: str | None = None,
    workspace: str | None = None,
) -> int:
    try:
        cfg = load_scigraph_config()
        if store is not None and workspace_root is not None:
            sys.stderr.write(
                "Failed to start server: --store and --workspace-root cannot be used together.\n"
            )
            return 2

        resolved_workspace_root = (
            None
            if store is not None
            else (workspace_root if workspace_root is not None else cfg.workspace_root)
        )
        if (org is not None or workspace is not None) and resolved_workspace_root is None:
            sys.stderr.write(
                "Failed to start server: --org and --workspace require --workspace-root "
                "(or workspace_root in config).\n"
            )
            return 2

        resolved_store = (
            store
            if store is not None
            else (None if resolved_workspace_root is not None else cfg.default_store)
        )
        resolved_rate_limit = rate_limit if rate_limit is not None else cfg.rate_limit
        resolved_rate_window = cfg.rate_window_seconds if rate_window is None else rate_window
        resolved_org = org if org is not None else cfg.default_org

        if (
            tokens is None
            and resolved_rate_limit is None
            and resolved_workspace_root is None
        ):
            _resolve_cli_attr("run_server", run_server)(
                host=host,
                port=port,
                store_path=Path(resolved_store) if resolved_store else None,
            )
            return 0

        auth_gate: AuthGate | None = None
        if tokens is not None:
            policies = load_token_policies(Path(tokens))
            if not policies:
                sys.stderr.write(
                    f"Failed to start server: token policy file '{tokens}' "
                    "contains no policies.\n"
                )
                return 2
            auth_gate = AuthGate(policies)
        rate_limiter = (
            SlidingWindowRateLimiter(
                max_requests=resolved_rate_limit,
                window_seconds=resolved_rate_window,
            )
            if resolved_rate_limit is not None
            else None
        )
        workspace_manager = (
            WorkspaceManager(Path(resolved_workspace_root))
            if resolved_workspace_root is not None
            else None
        )
        graph = _load_graph_from_store(Path(resolved_store)) if resolved_store is not None else None
        app = SciGraphApp(
            graph=graph,
            auth_gate=auth_gate,
            rate_limiter=rate_limiter,
            workspace_manager=workspace_manager,
            org_id=resolved_org,
            workspace_id=workspace,
        )
        server = _resolve_cli_attr("create_http_server", create_http_server)(host, port, app)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to start server: {exc}\n")
        return 2
    return 0


def _cmd_consensus(store: str, as_json: bool) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    topics = compute_topic_consensus(graph)
    scores = score_claim_evidence(graph)
    if as_json:
        payload = {
            "consensus": [topic.model_dump(mode="json") for topic in topics],
            "claim_scores": {
                claim_id: score.model_dump(mode="json")
                for claim_id, score in scores.items()
            },
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    elif not topics and not scores:
        sys.stdout.write("No verified claims in store.\n")
    else:
        for topic in topics:
            direction = (
                topic.consensus_direction.value
                if topic.consensus_direction is not None
                else "mixed"
            )
            sys.stdout.write(
                f"Topic: {topic.intervention} -> {topic.outcome} | "
                f"direction={direction} score={topic.consensus_score:.4f} "
                f"supporting={topic.supporting_claims} "
                f"contradicting={topic.contradicting_claims} "
                f"neutral={topic.neutral_claims} contested={topic.contested}\n"
            )
        sys.stdout.write(f"Scored claims: {len(scores)}\n")
    return 0


def _cmd_diff(baseline: str, current: str, as_json: bool) -> int:
    try:
        baseline_graph = _load_graph_from_store(Path(baseline))
        current_graph = _load_graph_from_store(Path(current))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to diff stores '{baseline}' and '{current}': {exc}\n")
        return 2

    diff_result = diff_claim_graphs(baseline_graph, current_graph)
    if as_json:
        sys.stdout.write(
            json.dumps(diff_result.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        )
    else:
        sys.stdout.write(
            f"Diff: added_papers={len(diff_result.added_papers)} "
            f"removed_papers={len(diff_result.removed_papers)} "
            f"added_claims={len(diff_result.added_claims)} "
            f"removed_claims={len(diff_result.removed_claims)} "
            f"new_contradictions={len(diff_result.new_contradictions)} "
            f"resolved_contradictions={len(diff_result.resolved_contradictions)}\n"
        )
    return 0


def _cmd_export_refs(store: str, fmt: str, output: str | None) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    papers = list(graph.papers)
    rendered = export_bibtex(papers) if fmt == "bibtex" else export_ris(papers)
    content = f"{rendered}\n" if rendered and not rendered.endswith("\n") else rendered

    if output is not None:
        try:
            _atomic_write_text(Path(output), content)
        except OSError as exc:
            sys.stderr.write(f"Failed to write output file '{output}': {exc}\n")
            return 2
    else:
        sys.stdout.write(content)
    return 0


def _cmd_workspace(args: argparse.Namespace) -> int:
    manager = WorkspaceManager(Path(str(args.root)))
    org_id = str(args.org)
    workspace_id = str(args.workspace)
    as_json = bool(args.json)
    action = str(args.ws_action)

    try:
        if action == "init":
            config = manager.init_workspace(
                org_id=org_id,
                workspace_id=workspace_id,
                name=str(args.name),
            )
            if as_json:
                sys.stdout.write(
                    json.dumps(config.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
                )
            else:
                sys.stdout.write(
                    f"Initialized workspace {config.org_id}/{config.workspace_id} "
                    f"({config.name})\n"
                )
            return 0

        if action == "ingest":
            papers = load_papers_from_path(Path(str(args.input)))
            graph, reports = manager.ingest_papers(
                org_id=org_id,
                workspace_id=workspace_id,
                papers=papers,
            )
            verified_claims = sum(len(r.verified_claims) for r in reports)
            rejected_claims = sum(len(r.rejected_claim_ids) for r in reports)
            if as_json:
                summary = {
                    "org_id": org_id,
                    "workspace_id": workspace_id,
                    "papers": len(papers),
                    "total_graph_papers": len(graph.papers),
                    "verified_claims": verified_claims,
                    "rejected_claims": rejected_claims,
                    "total_graph_claims": len(graph.claims),
                }
                sys.stdout.write(json.dumps(summary, sort_keys=True, indent=2) + "\n")
            else:
                sys.stdout.write(
                    f"Workspace {org_id}/{workspace_id}: ingested papers={len(papers)} "
                    f"verified_claims={verified_claims} rejected_claims={rejected_claims}\n"
                )
            return 0

        if action == "audit":
            action_filter = cast(WorkspaceAction | None, getattr(args, "action", None))
            limit_arg = getattr(args, "limit", None)
            limit = int(limit_arg) if limit_arg is not None else None
            events = manager.read_audit_log(
                org_id=org_id,
                workspace_id=workspace_id,
                action=action_filter,
                limit=limit,
            )
            if as_json:
                payload = [event.model_dump(mode="json") for event in events]
                sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
            elif not events:
                sys.stdout.write(f"No audit events for {org_id}/{workspace_id}.\n")
            else:
                for event in events:
                    sys.stdout.write(
                        f"{event.timestamp_utc} [{event.action}] status={event.status} "
                        f"papers={event.paper_count} claims={event.claim_count} {event.detail}\n"
                    )
            return 0
    except (ValueError, FileNotFoundError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Workspace command '{action}' failed: {exc}\n")
        return 2

    return 2


def _cmd_fetch(source: str, query: str, output: str, max_results: int) -> int:
    try:
        if source == "arxiv":
            papers = _resolve_cli_attr("fetch_arxiv_papers", fetch_arxiv_papers)(
                query, max_results=max_results
            )
        elif source == "europepmc":
            papers = _resolve_cli_attr("fetch_europepmc_papers", fetch_europepmc_papers)(
                query, max_results=max_results
            )
        else:
            raise ValueError(f"Unsupported fetch source: {source!r}")
        payload = {"papers": [paper.model_dump(mode="json") for paper in papers]}
        output_path = Path(output)
        _atomic_write_text(
            output_path,
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
        )
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"Failed to fetch from '{source}': {exc}\n")
        return 2

    sys.stdout.write(f"Fetched {len(papers)} papers from {source} -> {output_path}\n")
    return 0


def _cmd_provenance(args: argparse.Namespace) -> int:
    action = str(args.prov_action)
    try:
        graph = _load_graph_from_store(Path(str(args.store)))
        audit_events = _load_audit_events(args.audit_log)
        if action == "build":
            manifest = build_provenance_manifest(graph, audit_events=audit_events)
            output_path = Path(str(args.output))
            _atomic_write_text(
                output_path,
                json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
            )
            sys.stdout.write(f"Built provenance manifest -> {output_path}\n")
            return 0
        if action == "verify":
            manifest_path = Path(str(args.manifest))
            manifest = ProvenanceManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            intact, reasons = verify_provenance_manifest(
                graph,
                manifest,
                audit_events=audit_events,
            )
            if bool(args.json):
                payload = {"intact": intact, "reasons": list(reasons)}
                sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
            else:
                status = "intact" if intact else f"tampered ({', '.join(reasons)})"
                sys.stdout.write(f"Provenance: {status}\n")
            return 0 if intact else 1
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Provenance command '{action}' failed: {exc}\n")
        return 2
    return 2


def _cmd_pipeline(args: argparse.Namespace) -> int:
    try:
        formats = tuple(cast(list[OutputFormat], args.format))
        config = PipelineConfig(
            input_path=str(args.input),
            store_path=str(args.store),
            report_dir=str(args.report_dir),
            formats=formats,
            fail_on_contradictions=bool(args.fail_on_contradictions),
            min_verified_papers=int(args.min_verified_papers),
        )
        summary = run_pipeline(config)
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Pipeline failed: {exc}\n")
        return 2

    if bool(args.json):
        sys.stdout.write(
            json.dumps(summary.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        )
    else:
        sys.stdout.write(
            f"Pipeline passed={summary.passed} "
            f"papers_verified={summary.papers_verified}/{summary.papers_loaded} "
            f"claims_verified={summary.claims_verified} "
            f"claims_rejected={summary.claims_rejected} "
            f"contradictions={summary.contradictions_found}\n"
        )
    return 0 if summary.passed else 1


def _cmd_prioritize(store: str, as_json: bool) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    contradictions = detect_contradictions(graph)
    experiments = propose_falsifiable_experiments(contradictions)
    prioritized = prioritize_experiments(graph, contradictions, experiments)

    if as_json:
        payload = {
            "prioritized": [item.model_dump(mode="json") for item in prioritized],
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    elif not prioritized:
        sys.stdout.write("No contradictions or experiments to prioritize.\n")
    else:
        for item in prioritized:
            sys.stdout.write(
                f"#{item.rank} {item.experiment_id} "
                f"[contradiction={item.contradiction_id}] "
                f"score={item.priority_score:.4f} "
                f"cost={item.cost_tier} "
                f"n={item.estimated_participants} | {item.reason}\n"
            )
    return 0


def _cmd_canonicalize(store: str, as_json: bool) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    clusters = EntityCanonicalizer().find_canonical_clusters(graph)
    if as_json:
        payload = {
            "clusters": [
                {
                    "intervention": pair[0],
                    "outcome": pair[1],
                    "claim_ids": list(claim_ids),
                }
                for pair, claim_ids in sorted(clusters.items())
            ]
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    elif not clusters:
        sys.stdout.write("No canonical entity clusters found.\n")
    else:
        for (intervention, outcome), claim_ids in sorted(clusters.items()):
            sys.stdout.write(
                f"Cluster: {intervention} -> {outcome} "
                f"claims={len(claim_ids)} ({', '.join(claim_ids)})\n"
            )
    return 0


def _cmd_alert(store: str, webhook_url: str | None, as_json: bool) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    payload = build_alert_payload(detect_contradictions(graph))
    if webhook_url is not None:
        try:
            ok, status, message = _resolve_cli_attr(
                "dispatch_webhook_alert", dispatch_webhook_alert
            )(webhook_url, payload)
        except ValueError as exc:
            sys.stderr.write(f"Alert webhook rejected: {exc}\n")
            return 2
        except (OSError, http.client.HTTPException) as exc:
            sys.stderr.write(f"Alert webhook failed: {exc}\n")
            return 2

        if as_json:
            result = {
                "ok": ok,
                "status": status,
                "message": message,
                "payload": payload.model_dump(mode="json"),
            }
            sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
        else:
            sys.stdout.write(f"Alert dispatch ok={ok} status={status}: {message}\n")
        return 0 if ok else 1

    if as_json:
        sys.stdout.write(
            json.dumps(payload.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        )
    else:
        sys.stdout.write(
            f"[{payload.severity.upper()}] {payload.title}: {payload.summary} "
            f"(contradictions={len(payload.contradiction_ids)})\n"
        )
    return 0


def _cmd_diagram(store: str, fmt: str, output: str | None) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    contradictions = detect_contradictions(graph)
    if fmt == "mermaid":
        rendered = export_mermaid_flowchart(graph, contradictions)
    else:
        rendered = export_graphviz_dot(graph, contradictions)
    return _write_or_stdout(rendered, output)


def _cmd_protocols(store: str, fmt: str, output: str | None) -> int:
    try:
        graph = _load_graph_from_store(Path(store))
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Failed to load store '{store}': {exc}\n")
        return 2

    contradictions = detect_contradictions(graph)
    experiments = propose_falsifiable_experiments(contradictions)
    protocols = generate_experiment_protocols(graph, contradictions, experiments)

    if fmt == "json":
        payload = {"protocols": [proto.model_dump(mode="json") for proto in protocols]}
        rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    else:
        rendered = render_protocols_markdown(protocols)
    return _write_or_stdout(rendered, output)


def _cmd_doctor(workspace_root: str | None, as_json: bool) -> int:
    report = run_doctor(
        workspace_root=Path(workspace_root) if workspace_root else None,
    )
    if as_json:
        sys.stdout.write(
            json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        )
    else:
        sys.stdout.write(f"SciGraph Doctor (Python {report.python_version})\n")
        for check in report.checks:
            status = "PASS" if check.passed else "FAIL"
            sys.stdout.write(f"[{status}] {check.name}: {check.detail}\n")
    return 0 if report.all_passed else 1


def _cmd_config(path: str | None, as_json: bool) -> int:
    config_path = Path(path) if path is not None else None
    try:
        cfg = load_scigraph_config(config_path)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"Failed to load config: {exc}\n")
        return 2
    if as_json:
        payload = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, indent=2)
        sys.stdout.write(payload + "\n")
    else:
        sys.stdout.write(
            f"default_org={cfg.default_org} "
            f"server={cfg.server_host}:{cfg.server_port} "
            f"default_store={cfg.default_store} "
            f"workspace_root={cfg.workspace_root} "
            f"rate_limit={cfg.rate_limit} "
            f"rate_window_seconds={cfg.rate_window_seconds}\n"
        )
    return 0
