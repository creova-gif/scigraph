import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from evals.benchmark import BENCHMARK_30_PAPERS, evaluate_benchmark, run_benchmark_audit
from ingest.extractor import (
    extract_claims_from_paper,
    extract_paper_from_layout,
    extract_paper_from_pdf_bytes,
    render_blocks_to_pdf_bytes,
)
from ingest.verifier import verify_paper_claims
from scigraph.explorer import render_claim_graph_html
from scigraph.exporters import export_json_bundle, export_sarif_v210, render_markdown_report


def _atomic_write_text(output_path: Path, content: str) -> None:
    if output_path.exists() and output_path.is_dir():
        raise IsADirectoryError(f"Output path is a directory: {output_path}")
    if not output_path.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {output_path.parent}")

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            delete=False,
            prefix=".scigraph-",
            suffix=".tmp",
        ) as handle:
            tmp_name = handle.name
            handle.write(content)
            handle.flush()
        os.replace(tmp_name, output_path)
    except OSError:
        if tmp_name is not None and os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


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


def _cmd_verify(paper_id: str | None) -> int:
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


def _cmd_report(fmt: str, output: str | None, fail_on_contradictions: bool) -> int:
    bundle = run_benchmark_audit()
    if fmt == "markdown":
        rendered = render_markdown_report(
            bundle.graph, bundle.contradictions, bundle.experiments, bundle.metrics
        )
    elif fmt == "html":
        rendered = render_claim_graph_html(
            bundle.graph, bundle.contradictions, bundle.experiments, bundle.metrics
        )
    elif fmt == "sarif":
        rendered = export_sarif_v210(bundle.contradictions, bundle.reports)
    else:
        rendered = export_json_bundle(
            bundle.graph, bundle.contradictions, bundle.experiments, bundle.metrics
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
        (not r.doi_verified) or bool(r.rejected_claim_ids) for r in bundle.reports
    )
    if has_verify_failure or (fail_on_contradictions and len(bundle.contradictions) > 0):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scigraph",
        description="SciGraph Neuro-Symbolic Scientific Discovery & Reasoning CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    bench_p = sub.add_parser("benchmark", help="Run the 30-paper benchmark evaluation.")
    bench_p.add_argument("--json", action="store_true", help="Emit BenchmarkMetrics as JSON.")

    verify_p = sub.add_parser("verify", help="Verify paper DOIs and verbatim claim spans.")
    verify_group = verify_p.add_mutually_exclusive_group()
    verify_group.add_argument(
        "--paper-id", type=str, default=None, help="Verify one benchmark paper."
    )
    verify_group.add_argument("--all", action="store_true", help="Verify all 30 benchmark papers.")

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
        return _cmd_verify(paper_id=args.paper_id)
    if args.command == "report":
        return _cmd_report(
            fmt=str(args.format),
            output=args.output,
            fail_on_contradictions=bool(args.fail_on_contradictions),
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
