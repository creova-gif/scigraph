"""Shared atomic file I/O utilities for SciGraph."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(
    output_path: Path,
    content: str,
    *,
    prefix: str = ".scigraph-",
    create_parents: bool = False,
) -> None:
    """Atomically write UTF-8 text to ``output_path`` via NamedTemporaryFile + os.replace."""
    if output_path.exists() and output_path.is_dir():
        raise IsADirectoryError(f"Output path is a directory: {output_path}")
    if create_parents:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    elif not output_path.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {output_path.parent}")

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            delete=False,
            prefix=prefix,
            suffix=".tmp",
        ) as handle:
            tmp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, output_path)
    except OSError:
        if tmp_name is not None and os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
