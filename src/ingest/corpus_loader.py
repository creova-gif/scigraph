import json
import re
from pathlib import Path

from pydantic import ValidationError

from ingest.extractor import extract_text_from_pdf_bytes
from ingest.tabular import load_papers_from_csv, parse_pubmed_efetch_xml
from scigraph.models import Paper

_DOI_SEARCH_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_FALLBACK_STEM_SANITIZE = re.compile(r"[^-._;()/:A-Za-z0-9]")


def _load_papers_from_json(path: Path) -> list[Paper]:
    try:
        raw_text = path.read_text(encoding="utf-8")
        payload: object = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON corpus file {path}: {exc}") from exc

    if isinstance(payload, dict) and "papers" in payload:
        items = payload["papers"]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError(
            f"Expected JSON list or {{'papers': [...]}} object in {path}"
        )

    if not isinstance(items, list):
        raise ValueError(f"Expected 'papers' to be a JSON list in {path}")

    papers: list[Paper] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Paper entry {idx} in {path} must be a JSON object")
        try:
            papers.append(Paper.model_validate_json(json.dumps(item)))
        except ValidationError as exc:
            raise ValueError(
                f"Invalid Paper schema at index {idx} in {path}: {exc}"
            ) from exc
    return papers


def _load_paper_from_pdf(path: Path) -> Paper:
    pdf_bytes = path.read_bytes()
    full_text = extract_text_from_pdf_bytes(pdf_bytes)

    doi_match = _DOI_SEARCH_PATTERN.search(full_text)
    if doi_match is not None:
        doi = doi_match.group(0)
    else:
        safe_stem = _FALLBACK_STEM_SANITIZE.sub("_", path.stem) or "paper"
        doi = f"10.0000/local.{safe_stem}"

    paper_id = path.stem or "local-paper"
    first_line = next(
        (line.strip() for line in full_text.splitlines() if line.strip()),
        paper_id,
    )
    title = first_line[:200] if first_line else paper_id

    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=("Unknown",),
        publication_year=2026,
        venue="local-pdf",
        full_text=full_text,
        sections=(),
    )


def _load_papers_from_supported_file(file_path: Path) -> list[Paper] | None:
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        return _load_papers_from_json(file_path)
    if suffix == ".pdf":
        return [_load_paper_from_pdf(file_path)]
    if suffix in {".csv", ".tsv"}:
        return load_papers_from_csv(file_path)
    if suffix == ".xml":
        return parse_pubmed_efetch_xml(file_path.read_bytes())
    return None


def load_papers_from_path(path: Path) -> list[Paper]:
    """Load Paper records from a corpus file or top-level directory.

    Supports ``.json``, ``.pdf``, ``.csv``, ``.tsv``, and PubMed ``.xml`` files.
    When ``path`` is a directory, iterates top-level entries via
    ``sorted(path.iterdir())`` and loads all supported files.
    """
    if not path.exists():
        raise ValueError(f"Corpus path does not exist: {path}")

    if path.is_dir():
        papers: list[Paper] = []
        matched_files = 0
        for entry in sorted(path.iterdir()):
            if not entry.is_file():
                continue
            loaded = _load_papers_from_supported_file(entry)
            if loaded is None:
                continue
            matched_files += 1
            papers.extend(loaded)
        if matched_files == 0 or not papers:
            raise ValueError(
                "No supported .json, .pdf, .csv, .tsv, or .xml papers found in "
                f"directory: {path}"
            )
        return papers

    if path.is_file():
        loaded = _load_papers_from_supported_file(path)
        if loaded is not None:
            return loaded
        raise ValueError(f"Unsupported corpus file extension {path.suffix!r} for {path}")

    raise ValueError(f"Unsupported corpus path: {path}")
