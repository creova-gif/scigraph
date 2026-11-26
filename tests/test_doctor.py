"""Tests for scigraph.doctor system diagnostics."""

import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from pydantic import ValidationError

from scigraph.doctor import DiagnosticCheck, DoctorReport, run_doctor


class _Py312Info(NamedTuple):
    major: int = 3
    minor: int = 12
    micro: int = 0
    releaselevel: str = "final"
    serial: int = 0


def test_run_doctor_default_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", _Py312Info())
    report = run_doctor()

    assert isinstance(report, DoctorReport)
    assert report.all_passed is True
    assert [check.name for check in report.checks] == [
        "python_version",
        "flate_pdf_roundtrip",
        "benchmark_gate",
    ]
    assert all(check.passed for check in report.checks)


def test_run_doctor_workspace_writable_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "version_info", _Py312Info())
    report = run_doctor(workspace_root=tmp_path)

    assert report.all_passed is True
    assert [check.name for check in report.checks] == [
        "python_version",
        "flate_pdf_roundtrip",
        "benchmark_gate",
        "workspace_writable",
    ]
    workspace_check = report.checks[-1]
    assert workspace_check.passed is True
    assert list(tmp_path.iterdir()) == []


def test_run_doctor_workspace_nonexistent_fails(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does_not_exist"
    report = run_doctor(workspace_root=missing_dir)

    assert report.all_passed is False
    workspace_check = next(
        check for check in report.checks if check.name == "workspace_writable"
    )
    assert workspace_check.passed is False


def test_run_doctor_workspace_file_fails(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello", encoding="utf-8")

    report = run_doctor(workspace_root=file_path)

    assert report.all_passed is False
    workspace_check = next(
        check for check in report.checks if check.name == "workspace_writable"
    )
    assert workspace_check.passed is False


def test_doctor_models_are_frozen_and_strict() -> None:
    check = DiagnosticCheck(name="sample", passed=True, detail="ok")
    report = DoctorReport(
        python_version="3.12.0",
        checks=(check,),
        all_passed=True,
    )

    with pytest.raises(ValidationError):
        check.passed = False

    with pytest.raises(ValidationError):
        report.all_passed = False

    with pytest.raises(ValidationError):
        DiagnosticCheck(name="sample", passed=True, detail="ok", extra_field=1)  # type: ignore[call-arg]
