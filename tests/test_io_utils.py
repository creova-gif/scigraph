"""Unit tests for shared atomic file I/O utilities."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scigraph.io_utils import atomic_write_text


def test_atomic_write_text_writes_and_overwrites_utf8(tmp_path: Path) -> None:
    target = tmp_path / "output.txt"
    atomic_write_text(target, "hello αβγ\n")
    assert target.read_text(encoding="utf-8") == "hello αβγ\n"

    atomic_write_text(target, "updated\n")
    assert target.read_text(encoding="utf-8") == "updated\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_text_raises_is_a_directory_error(tmp_path: Path) -> None:
    directory = tmp_path / "existing_dir"
    directory.mkdir()

    with pytest.raises(IsADirectoryError):
        atomic_write_text(directory, "content")


def test_atomic_write_text_raises_file_not_found_when_parent_missing(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "nested" / "output.txt"

    with pytest.raises(FileNotFoundError):
        atomic_write_text(target, "content")

    assert not target.parent.exists()


def test_atomic_write_text_create_parents_creates_directories(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "output.txt"
    atomic_write_text(target, "nested ok\n", prefix=".custom-", create_parents=True)

    assert target.read_text(encoding="utf-8") == "nested ok\n"
    assert list(target.parent.glob("*.tmp")) == []


def test_atomic_write_text_cleans_up_temp_file_on_replace_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "output.txt"
    target.write_text("original", encoding="utf-8")

    def _failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("scigraph.io_utils.os.replace", _failing_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(target, "new content", prefix=".test-")

    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob("*.tmp")) == []
