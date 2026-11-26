from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from graph.claim_graph import ClaimGraph

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    intervention TEXT NOT NULL,
    outcome TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_claim_id ON claims (claim_id);
CREATE INDEX IF NOT EXISTS idx_claims_paper_id ON claims (paper_id);
CREATE INDEX IF NOT EXISTS idx_claims_intervention ON claims (intervention);
CREATE INDEX IF NOT EXISTS idx_claims_outcome ON claims (outcome);

CREATE TABLE IF NOT EXISTS edges (
    edge_id TEXT PRIMARY KEY,
    source_claim_id TEXT NOT NULL,
    target_claim_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def save_graph_json(graph: ClaimGraph, path: Path) -> None:
    """Atomically write a ClaimGraph as deterministic, sorted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph.to_dict(), indent=2, sort_keys=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise


def load_graph_json(path: Path) -> ClaimGraph:
    """Load and validate a ClaimGraph from a JSON bundle file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return ClaimGraph.from_dict(raw)


class GraphSQLiteStore:
    """Zero-dependency SQLite persistence store for ClaimGraph."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(_SCHEMA_SQL)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save_graph(self, graph: ClaimGraph) -> None:
        """Persist the full ClaimGraph, replacing any previously stored state."""
        with self._connection() as conn:
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM claims")
            conn.execute("DELETE FROM papers")

            conn.executemany(
                "INSERT INTO papers (paper_id, payload_json) VALUES (?, ?)",
                [(paper.paper_id, paper.model_dump_json()) for paper in graph.papers],
            )
            conn.executemany(
                """
                INSERT INTO claims (claim_id, paper_id, intervention, outcome, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        claim.claim_id,
                        claim.paper_id,
                        claim.claim_tuple.intervention,
                        claim.claim_tuple.outcome,
                        claim.model_dump_json(),
                    )
                    for claim in graph.claims
                ],
            )
            conn.executemany(
                """
                INSERT INTO edges (edge_id, source_claim_id, target_claim_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        edge.edge_id,
                        edge.source_claim_id,
                        edge.target_claim_id,
                        edge.model_dump_json(),
                    )
                    for edge in graph.edges
                ],
            )

    def load_graph(self) -> ClaimGraph:
        """Load and validate the persisted ClaimGraph from SQLite."""
        with self._connection() as conn:
            papers = [
                json.loads(row[0])
                for row in conn.execute("SELECT payload_json FROM papers ORDER BY rowid")
            ]
            claims = [
                json.loads(row[0])
                for row in conn.execute("SELECT payload_json FROM claims ORDER BY rowid")
            ]
            edges = [
                json.loads(row[0])
                for row in conn.execute("SELECT payload_json FROM edges ORDER BY rowid")
            ]

        return ClaimGraph.from_dict(
            {
                "papers": papers,
                "claims": claims,
                "edges": edges,
            }
        )
