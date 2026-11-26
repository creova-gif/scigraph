"""System diagnostics and self-check utilities for SciGraph."""

import sys
import tempfile
import zlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from evals.benchmark import evaluate_benchmark
from ingest.extractor import extract_text_from_pdf_bytes

_MIN_PYTHON = (3, 12)
_MIN_F1_SCORE = 0.85
_ROUNDTRIP_SENTINEL = "SciGraph doctor roundtrip ok"


class DiagnosticCheck(BaseModel):
    """Single diagnostic check result."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    name: str
    passed: bool
    detail: str


class DoctorReport(BaseModel):
    """Aggregated system diagnostics report."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    python_version: str
    checks: tuple[DiagnosticCheck, ...]
    all_passed: bool


def _check_python_version(version_str: str) -> DiagnosticCheck:
    passed = sys.version_info >= _MIN_PYTHON
    return DiagnosticCheck(
        name="python_version",
        passed=passed,
        detail=f"Python {version_str} (requires >= 3.12)",
    )


def _check_flate_pdf_roundtrip() -> DiagnosticCheck:
    stream_payload = f"BT /F1 12 Tf 72 720 Td ({_ROUNDTRIP_SENTINEL}) Tj ET".encode("latin-1")
    compressed = zlib.compress(stream_payload)
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n"
        + f"<< /Length {len(compressed)} /Filter /FlateDecode >>\n".encode("ascii")
        + b"stream\n"
        + compressed
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    try:
        extracted = extract_text_from_pdf_bytes(pdf_bytes)
    except (ValueError, zlib.error) as exc:
        return DiagnosticCheck(
            name="flate_pdf_roundtrip",
            passed=False,
            detail=f"PDF FlateDecode roundtrip failed: {exc}",
        )

    passed = _ROUNDTRIP_SENTINEL in extracted
    detail = (
        f"Extracted '{_ROUNDTRIP_SENTINEL}' from /FlateDecode PDF"
        if passed
        else f"Unexpected extracted text: {extracted!r}"
    )
    return DiagnosticCheck(
        name="flate_pdf_roundtrip",
        passed=passed,
        detail=detail,
    )


def _check_benchmark_gate() -> DiagnosticCheck:
    try:
        metrics = evaluate_benchmark()
    except (ValueError, RuntimeError) as exc:
        return DiagnosticCheck(
            name="benchmark_gate",
            passed=False,
            detail=f"Benchmark evaluation failed: {exc}",
        )

    passed = (
        metrics.f1_score >= _MIN_F1_SCORE
        and metrics.fabricated_dois_accepted == 0
        and metrics.fabricated_p_values_accepted == 0
    )
    detail = (
        f"f1={metrics.f1_score:.3f}, "
        f"fabricated_dois={metrics.fabricated_dois_accepted}, "
        f"fabricated_p={metrics.fabricated_p_values_accepted}"
    )
    return DiagnosticCheck(
        name="benchmark_gate",
        passed=passed,
        detail=detail,
    )


def _check_workspace_writable(workspace_root: Path) -> DiagnosticCheck:
    if not (workspace_root.exists() and workspace_root.is_dir()):
        return DiagnosticCheck(
            name="workspace_writable",
            passed=False,
            detail=f"Workspace root does not exist or is not a directory: {workspace_root}",
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=workspace_root,
            prefix=".scigraph_doctor_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(b"ok")
        tmp_path.unlink()
        tmp_path = None
    except OSError as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return DiagnosticCheck(
            name="workspace_writable",
            passed=False,
            detail=f"Workspace root is not writable ({workspace_root}): {exc}",
        )

    return DiagnosticCheck(
        name="workspace_writable",
        passed=True,
        detail=f"Workspace root is writable: {workspace_root}",
    )


def run_doctor(workspace_root: Path | None = None) -> DoctorReport:
    """Run system self-checks and return a structured Diagnostic report."""
    version_str = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    checks: list[DiagnosticCheck] = [
        _check_python_version(version_str),
        _check_flate_pdf_roundtrip(),
        _check_benchmark_gate(),
    ]
    if workspace_root is not None:
        checks.append(_check_workspace_writable(workspace_root))

    return DoctorReport(
        python_version=version_str,
        checks=tuple(checks),
        all_passed=all(check.passed for check in checks),
    )
