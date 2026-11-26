"""Graph diff / regression tracker and BibTeX/RIS reference exporters."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from graph.claim_graph import ClaimGraph
from scigraph.models import ContradictionPair, Paper
from solver.symbolic import detect_contradictions

_LATEX_SPECIAL_CHARS: tuple[tuple[str, str], ...] = (
    ("&", r"\&"),
    ("%", r"\%"),
    ("#", r"\#"),
    ("_", r"\_"),
)


class GraphDiff(BaseModel):
    """Deterministic structural and contradiction diff between two ClaimGraphs."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    added_papers: tuple[str, ...]
    removed_papers: tuple[str, ...]
    added_claims: tuple[str, ...]
    removed_claims: tuple[str, ...]
    new_contradictions: tuple[str, ...]
    resolved_contradictions: tuple[str, ...]


def _contradiction_signature(pair: ContradictionPair) -> str:
    """Return a canonical string key for a contradiction pair."""
    id_a = pair.claim_a.claim_id
    id_b = pair.claim_b.claim_id
    low, high = (id_a, id_b) if id_a <= id_b else (id_b, id_a)
    return f"{low}|{high}|{pair.kind.value}"


def diff_claim_graphs(baseline: ClaimGraph, current: ClaimGraph) -> GraphDiff:
    """Compare baseline and current ClaimGraphs for paper, claim, and contradiction changes."""
    baseline_papers = {paper.paper_id for paper in baseline.papers}
    current_papers = {paper.paper_id for paper in current.papers}

    baseline_claims = {claim.claim_id for claim in baseline.claims}
    current_claims = {claim.claim_id for claim in current.claims}

    baseline_contradictions = {
        _contradiction_signature(pair) for pair in detect_contradictions(baseline)
    }
    current_contradictions = {
        _contradiction_signature(pair) for pair in detect_contradictions(current)
    }

    return GraphDiff(
        added_papers=tuple(sorted(current_papers - baseline_papers)),
        removed_papers=tuple(sorted(baseline_papers - current_papers)),
        added_claims=tuple(sorted(current_claims - baseline_claims)),
        removed_claims=tuple(sorted(baseline_claims - current_claims)),
        new_contradictions=tuple(sorted(current_contradictions - baseline_contradictions)),
        resolved_contradictions=tuple(sorted(baseline_contradictions - current_contradictions)),
    )


def _escape_latex(text: str) -> str:
    """Escape common LaTeX special characters for non-DOI BibTeX fields."""
    escaped = text
    for char, replacement in _LATEX_SPECIAL_CHARS:
        escaped = escaped.replace(char, replacement)
    return escaped


def export_bibtex(papers: Sequence[Paper]) -> str:
    """Export papers as deterministic BibTeX @article entries sorted by paper_id."""
    if not papers:
        return ""

    entries: list[str] = []
    for paper in sorted(papers, key=lambda p: p.paper_id):
        authors = " and ".join(_escape_latex(author) for author in paper.authors)
        title = _escape_latex(paper.title)
        journal = _escape_latex(paper.venue)
        entry = "\n".join(
            [
                f"@article{{{paper.paper_id},",
                f"  title = {{{title}}},",
                f"  author = {{{authors}}},",
                f"  journal = {{{journal}}},",
                f"  year = {{{paper.publication_year}}},",
                f"  doi = {{{paper.doi}}},",
                "}",
            ]
        )
        entries.append(entry)

    return "\n\n".join(entries)


def export_ris(papers: Sequence[Paper]) -> str:
    """Export papers as deterministic RIS journal records sorted by paper_id."""
    if not papers:
        return ""

    records: list[str] = []
    for paper in sorted(papers, key=lambda p: p.paper_id):
        lines: list[str] = [
            "TY  - JOUR",
            f"ID  - {paper.paper_id}",
            f"TI  - {paper.title}",
        ]
        for author in paper.authors:
            lines.append(f"AU  - {author}")
        lines.extend(
            [
                f"JO  - {paper.venue}",
                f"PY  - {paper.publication_year}",
                f"DO  - {paper.doi}",
                "ER  - ",
            ]
        )
        records.append("\n".join(lines))

    return "\n\n".join(records)
