from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from graph import ClaimGraph, GraphSQLiteStore, load_graph_json, save_graph_json
from ingest.verifier import verify_claim_verbatim
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    Paper,
    PaperSection,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
    VerificationFailureReason,
)


def _make_paper_and_claim(
    *,
    paper_id: str,
    doi: str,
    claim_id: str,
    intervention: str,
    condition: str,
    outcome: str,
    direction: EffectDirection,
    p_value_raw: str = "p = 0.004",
    p_value: float = 0.004,
    sample_size_raw: str = "n = 120",
    sample_size: int = 120,
) -> tuple[Paper, ScientificClaim]:
    statement = (
        f"Under {condition}, {intervention} affects {outcome} ({p_value_raw}, {sample_size_raw})."
    )
    full_text = f"DOI: {doi}\nResults: {statement}"
    start_char = full_text.index(statement)
    end_char = start_char + len(statement)
    results_start = full_text.index("Results:")

    paper = Paper(
        paper_id=paper_id,
        doi=doi,
        title=f"Study {paper_id}",
        authors=("Alice Smith", "Bob Jones"),
        publication_year=2025,
        venue="Journal of Reproducible Science",
        full_text=full_text,
        sections=(
            PaperSection(
                kind=SectionKind.RESULTS,
                heading="Results",
                text=full_text[results_start:],
                start_char=results_start,
                end_char=len(full_text),
            ),
        ),
    )
    claim = ScientificClaim(
        claim_id=claim_id,
        paper_id=paper_id,
        doi=doi,
        claim_tuple=ClaimTuple(
            intervention=intervention,
            condition=condition,
            outcome=outcome,
            direction=direction,
        ),
        statistics=StatisticalEvidence(
            p_operator=ComparisonOperator.EQ,
            p_value=p_value,
            p_value_raw=p_value_raw,
            sample_size=sample_size,
            sample_size_raw=sample_size_raw,
            effect_size_raw="d = 0.52",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=start_char,
            end_char=end_char,
            verbatim_text=statement,
        ),
    )
    return paper, claim


def _build_sample_graph() -> ClaimGraph:
    graph = ClaimGraph()

    p1, c1 = _make_paper_and_claim(
        paper_id="paper-001",
        doi="10.1038/scigraph.2025.001",
        claim_id="claim-001",
        intervention="Metformin",
        condition="Normoglycemic Adults",
        outcome="Hepatic Gluconeogenesis",
        direction=EffectDirection.DECREASES,
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="paper-002",
        doi="10.1038/scigraph.2025.002",
        claim_id="claim-002",
        intervention="Metformin Hydrochloride",
        condition="Type 2 Diabetes Cohort",
        outcome="Hepatic Gluconeogenesis",
        direction=EffectDirection.INCREASES,
    )
    p3, c3 = _make_paper_and_claim(
        paper_id="paper-003",
        doi="10.1038/scigraph.2025.003",
        claim_id="claim-003",
        intervention="Metformin",
        condition="Normoglycemic Adults",
        outcome="Hepatic Gluconeogenesis",
        direction=EffectDirection.DECREASES,
    )
    p4, c4 = _make_paper_and_claim(
        paper_id="paper-004",
        doi="10.1038/scigraph.2025.004",
        claim_id="claim-004",
        intervention="Berberine",
        condition="Type 2 Diabetes Cohort",
        outcome="Fasting Blood Glucose",
        direction=EffectDirection.NO_EFFECT,
    )

    for paper, claim in ((p1, c1), (p2, c2), (p3, c3), (p4, c4)):
        graph.add_verified_claim(paper, claim)

    graph.build_edges()
    return graph


def test_query_claims_filters() -> None:
    graph = _build_sample_graph()

    assert len(graph.query_claims()) == 4

    # Case-insensitive substring matching for string filters
    metformin_claims = graph.query_claims(intervention="metform")
    assert [c.claim_id for c in metformin_claims] == ["claim-001", "claim-002", "claim-003"]

    diabetes_claims = graph.query_claims(condition="diabetes")
    assert [c.claim_id for c in diabetes_claims] == ["claim-002", "claim-004"]

    glucose_claims = graph.query_claims(outcome="GLUCOSE")
    assert [c.claim_id for c in glucose_claims] == ["claim-004"]

    # Exact match for effect_direction and paper_id
    no_effect_claims = graph.query_claims(effect_direction=EffectDirection.NO_EFFECT)
    assert [c.claim_id for c in no_effect_claims] == ["claim-004"]

    paper_2_claims = graph.query_claims(paper_id="paper-002")
    assert [c.claim_id for c in paper_2_claims] == ["claim-002"]

    # Partial paper_id must not match (exact match required)
    assert graph.query_claims(paper_id="paper-00") == ()

    # Combined filters
    combined = graph.query_claims(
        intervention="METFORMIN",
        condition="normoglycemic",
        outcome="gluconeogenesis",
        effect_direction=EffectDirection.DECREASES,
        paper_id="paper-003",
    )
    assert [c.claim_id for c in combined] == ["claim-003"]


def test_claim_graph_dict_round_trip_and_validation() -> None:
    graph = _build_sample_graph()
    payload = graph.to_dict()
    reconstructed = ClaimGraph.from_dict(payload)

    assert reconstructed.papers == graph.papers
    assert reconstructed.claims == graph.claims
    assert reconstructed.edges == graph.edges

    # Invalid paper payload is rejected by Pydantic validation
    bad_payload = json.loads(json.dumps(payload))
    bad_payload["papers"][0]["doi"] = "not-a-doi"
    with pytest.raises(ValidationError):
        ClaimGraph.from_dict(bad_payload)

    with pytest.raises(ValueError, match="requires list values"):
        ClaimGraph.from_dict({"papers": {}, "claims": [], "edges": []})


def test_save_and_load_graph_json_round_trip(tmp_path: Path) -> None:
    graph = _build_sample_graph()
    out_path = tmp_path / "nested" / "bundle.json"

    save_graph_json(graph, out_path)
    first_bytes = out_path.read_text(encoding="utf-8")

    # Deterministic sorted JSON output and no leftover temp files
    save_graph_json(graph, out_path)
    second_bytes = out_path.read_text(encoding="utf-8")
    assert first_bytes == second_bytes
    assert [p.name for p in out_path.parent.iterdir()] == ["bundle.json"]

    parsed = json.loads(first_bytes)
    assert list(parsed.keys()) == ["claims", "edges", "papers"]

    loaded = load_graph_json(out_path)
    assert loaded.papers == graph.papers
    assert loaded.claims == graph.claims
    assert loaded.edges == graph.edges


def test_sqlite_store_round_trip_and_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "scigraph.sqlite3"
    store = GraphSQLiteStore(db_path)

    # Fresh store returns empty graph
    empty_loaded = store.load_graph()
    assert empty_loaded.papers == ()
    assert empty_loaded.claims == ()
    assert empty_loaded.edges == ()

    graph = _build_sample_graph()
    store.save_graph(graph)
    loaded = store.load_graph()

    assert loaded.papers == graph.papers
    assert loaded.claims == graph.claims
    assert loaded.edges == graph.edges

    # Verify required tables and indexed columns exist
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"papers", "claims", "edges"}.issubset(tables)

        claim_indexes = {
            row[1] for row in conn.execute("PRAGMA index_list('claims')").fetchall()
        }
        assert {
            "idx_claims_claim_id",
            "idx_claims_paper_id",
            "idx_claims_intervention",
            "idx_claims_outcome",
        }.issubset(claim_indexes)
    finally:
        conn.close()

    # Overwriting with an empty graph replaces prior rows cleanly
    store.save_graph(ClaimGraph())
    replaced = store.load_graph()
    assert replaced.papers == ()
    assert replaced.claims == ()
    assert replaced.edges == ()


def test_verify_claim_verbatim_rejects_mismatched_paper_id() -> None:
    paper, claim = _make_paper_and_claim(
        paper_id="paper-001",
        doi="10.1038/scigraph.2025.001",
        claim_id="claim-001",
        intervention="Metformin",
        condition="Normoglycemic Adults",
        outcome="Hepatic Gluconeogenesis",
        direction=EffectDirection.DECREASES,
    )
    spoofed_claim = claim.model_copy(update={"paper_id": "paper-999"})

    result = verify_claim_verbatim(paper, spoofed_claim)
    assert result.verified is False
    assert VerificationFailureReason.SPAN_OUT_OF_BOUNDS in result.failures


def test_claim_graph_from_dict_rejects_orphan_claims_and_dangling_edges() -> None:
    graph = _build_sample_graph()
    base_payload = graph.to_dict()

    # Orphan claim: claim.paper_id missing from papers
    orphan_payload = json.loads(json.dumps(base_payload))
    orphan_payload["claims"][0]["paper_id"] = "paper-missing"
    with pytest.raises(ValueError, match="unknown paper_id 'paper-missing'"):
        ClaimGraph.from_dict(orphan_payload)

    # Dangling edge: source_claim_id missing from claims
    dangling_source_payload = json.loads(json.dumps(base_payload))
    dangling_source_payload["edges"][0]["source_claim_id"] = "claim-missing-src"
    with pytest.raises(ValueError, match="unknown source_claim_id 'claim-missing-src'"):
        ClaimGraph.from_dict(dangling_source_payload)

    # Dangling edge: target_claim_id missing from claims
    dangling_target_payload = json.loads(json.dumps(base_payload))
    dangling_target_payload["edges"][0]["target_claim_id"] = "claim-missing-tgt"
    with pytest.raises(ValueError, match="unknown target_claim_id 'claim-missing-tgt'"):
        ClaimGraph.from_dict(dangling_target_payload)


def test_sqlite_store_wal_and_busy_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "wal.sqlite3"
    store = GraphSQLiteStore(db_path)

    with store._connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()
        synchronous = conn.execute("PRAGMA synchronous").fetchone()

    assert journal_mode == ("wal",)
    assert busy_timeout == (5000,)
    assert synchronous == (1,)


def test_sqlite_store_query_claims_parity_with_claim_graph(tmp_path: Path) -> None:
    graph = _build_sample_graph()
    store = GraphSQLiteStore(tmp_path / "parity.sqlite3")
    store.save_graph(graph)

    filter_cases: list[dict[str, object]] = [
        {},
        {"intervention": "metform"},
        {"condition": "diabetes"},
        {"outcome": "GLUCOSE"},
        {"effect_direction": EffectDirection.NO_EFFECT},
        {"paper_id": "paper-002"},
        {"paper_id": "paper-00"},
        {
            "intervention": "METFORMIN",
            "condition": "normoglycemic",
            "outcome": "gluconeogenesis",
            "effect_direction": EffectDirection.DECREASES,
            "paper_id": "paper-003",
        },
        {"intervention": "nonexistent"},
    ]

    for kwargs in filter_cases:
        expected = graph.query_claims(**kwargs)  # type: ignore[arg-type]
        actual = store.query_claims(**kwargs)  # type: ignore[arg-type]
        assert actual == expected


def test_sqlite_store_query_claims_escapes_like_wildcards(tmp_path: Path) -> None:
    graph = ClaimGraph()
    p1, c1 = _make_paper_and_claim(
        paper_id="paper-101",
        doi="10.1038/scigraph.2025.101",
        claim_id="claim-101",
        intervention="100% Pure Metformin",
        condition="Adults",
        outcome="Glucose_Level\\Fast",
        direction=EffectDirection.DECREASES,
    )
    p2, c2 = _make_paper_and_claim(
        paper_id="paper-102",
        doi="10.1038/scigraph.2025.102",
        claim_id="claim-102",
        intervention="1000 Pure Metformin",
        condition="Adults",
        outcome="GlucoseXLevelFast",
        direction=EffectDirection.DECREASES,
    )
    graph.add_verified_claim(p1, c1)
    graph.add_verified_claim(p2, c2)

    store = GraphSQLiteStore(tmp_path / "wildcards.sqlite3")
    store.save_graph(graph)

    assert [c.claim_id for c in store.query_claims(intervention="100%")] == ["claim-101"]
    assert [c.claim_id for c in store.query_claims(outcome="glucose_level\\fast")] == [
        "claim-101"
    ]
    assert store.query_claims(intervention="%") == (c1,)
    assert store.query_claims(outcome="_") == (c1,)
