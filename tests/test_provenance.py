from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph.claim_graph import ClaimGraph
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    Paper,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)
from scigraph.provenance import (
    ProvenanceManifest,
    build_provenance_manifest,
    compute_audit_chain_head,
    verify_provenance_manifest,
)
from scigraph.workspace import AuditEvent


def _make_sample_graph() -> tuple[ClaimGraph, Paper, ScientificClaim]:
    sentence = (
        "Metformin under normoxia decreased blood glucose compared with placebo "
        "(n = 120, p < 0.001)."
    )
    doi = "10.1234/scigraph.001"
    prefix = f"DOI: {doi}\nResults\n"
    full_text = f"{prefix}{sentence}"
    start_char = len(prefix)
    end_char = start_char + len(sentence)

    paper = Paper(
        paper_id="paper-1",
        doi=doi,
        title="Metformin Glucose Study",
        authors=("Ada Lovelace",),
        publication_year=2025,
        venue="Journal of Deterministic Science",
        full_text=full_text,
    )
    claim = ScientificClaim(
        claim_id="claim-1",
        paper_id="paper-1",
        doi=doi,
        claim_tuple=ClaimTuple(
            intervention="Metformin",
            condition="normoxia",
            outcome="blood glucose",
            direction=EffectDirection.DECREASES,
            comparator="placebo",
        ),
        statistics=StatisticalEvidence(
            p_operator=ComparisonOperator.LT,
            p_value=0.001,
            p_value_raw="p < 0.001",
            sample_size=120,
            sample_size_raw="n = 120",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=start_char,
            end_char=end_char,
            verbatim_text=sentence,
        ),
    )

    graph = ClaimGraph()
    graph.add_verified_claim(paper, claim)
    graph.build_edges()
    return graph, paper, claim


def _make_audit_events() -> list[AuditEvent]:
    return [
        AuditEvent(
            event_id="evt-1",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            org_id="org-alpha",
            workspace_id="ws-one",
            action="ingest",
            paper_count=1,
            claim_count=1,
            status="ok",
            detail="Ingested paper-1",
        ),
        AuditEvent(
            event_id="evt-2",
            timestamp_utc="2026-01-01T00:01:00+00:00",
            org_id="org-alpha",
            workspace_id="ws-one",
            action="verify",
            paper_count=1,
            claim_count=1,
            status="ok",
            detail="Verified claim-1",
        ),
    ]


def test_build_and_verify_manifest_intact() -> None:
    graph, _, _ = _make_sample_graph()
    events = _make_audit_events()

    manifest = build_provenance_manifest(graph, audit_events=events)
    assert manifest.manifest_version == "1.0"
    assert len(manifest.graph_sha256) == 64
    assert set(manifest.paper_hashes.keys()) == {"paper-1"}
    assert set(manifest.claim_hashes.keys()) == {"claim-1"}
    assert manifest.audit_chain_head_sha256 == compute_audit_chain_head(events)
    assert manifest.signature_hmac_sha256 is None

    ok, reasons = verify_provenance_manifest(graph, manifest, audit_events=events)
    assert ok is True
    assert reasons == ()


def test_manifest_is_deterministic_across_builds() -> None:
    graph, _, _ = _make_sample_graph()
    events = _make_audit_events()
    key = b"deterministic-secret-key"

    m1 = build_provenance_manifest(graph, audit_events=events, hmac_key=key)
    m2 = build_provenance_manifest(graph, audit_events=events, hmac_key=key)

    assert m1.graph_sha256 == m2.graph_sha256
    assert m1.paper_hashes == m2.paper_hashes
    assert m1.claim_hashes == m2.claim_hashes
    assert m1.audit_chain_head_sha256 == m2.audit_chain_head_sha256


def test_audit_chain_head_empty_and_tampering() -> None:
    assert compute_audit_chain_head(()) is None

    events = _make_audit_events()
    head = compute_audit_chain_head(events)
    assert head is not None
    assert len(head) == 64

    graph, _, _ = _make_sample_graph()
    manifest = build_provenance_manifest(graph, audit_events=events)

    tampered_event = events[1].model_copy(update={"detail": "Tampered detail"})
    ok, reasons = verify_provenance_manifest(
        graph, manifest, audit_events=[events[0], tampered_event]
    )
    assert ok is False
    assert "audit_chain_head_mismatch" in reasons

    ok_reordered, reasons_reordered = verify_provenance_manifest(
        graph, manifest, audit_events=[events[1], events[0]]
    )
    assert ok_reordered is False
    assert "audit_chain_head_mismatch" in reasons_reordered


def test_paper_tampering_detection() -> None:
    graph, paper, claim = _make_sample_graph()
    manifest = build_provenance_manifest(graph)

    tampered_graph = ClaimGraph()
    tampered_paper = paper.model_copy(update={"title": "Altered Title"})
    tampered_graph.add_verified_claim(tampered_paper, claim)

    ok, reasons = verify_provenance_manifest(tampered_graph, manifest)
    assert ok is False
    assert "paper_hash_mismatch:paper-1" in reasons
    assert "graph_sha256_mismatch" in reasons


def test_claim_tampering_and_missing_unexpected_detection() -> None:
    graph, paper, claim = _make_sample_graph()
    manifest = build_provenance_manifest(graph)

    tampered_graph = ClaimGraph()
    tampered_claim = claim.model_copy(
        update={
            "claim_tuple": claim.claim_tuple.model_copy(
                update={"direction": EffectDirection.INCREASES}
            )
        }
    )
    tampered_graph.add_verified_claim(paper, tampered_claim)

    ok, reasons = verify_provenance_manifest(tampered_graph, manifest)
    assert ok is False
    assert "claim_hash_mismatch:claim-1" in reasons
    assert "graph_sha256_mismatch" in reasons

    empty_graph = ClaimGraph()
    ok_empty, reasons_empty = verify_provenance_manifest(empty_graph, manifest)
    assert ok_empty is False
    assert "paper_missing:paper-1" in reasons_empty
    assert "claim_missing:claim-1" in reasons_empty
    assert "graph_sha256_mismatch" in reasons_empty

    extra_paper = Paper(
        paper_id="paper-2",
        doi="10.1234/scigraph.002",
        title="Extra Study",
        authors=("Grace Hopper",),
        publication_year=2025,
        venue="Journal of Deterministic Science",
        full_text="DOI: 10.1234/scigraph.002\nResults\nNo effect.",
    )
    graph.add_paper(extra_paper)
    ok_extra, reasons_extra = verify_provenance_manifest(graph, manifest)
    assert ok_extra is False
    assert "paper_unexpected:paper-2" in reasons_extra


def test_hmac_signing_verification_and_failures() -> None:
    graph, _, _ = _make_sample_graph()
    events = _make_audit_events()
    key = b"super-secret-hmac-key"
    wrong_key = b"wrong-secret-hmac-key"

    with pytest.raises(ValueError, match="hmac_key must not be empty"):
        build_provenance_manifest(graph, hmac_key=b"")

    signed_manifest = build_provenance_manifest(
        graph, audit_events=events, hmac_key=key
    )
    assert signed_manifest.signature_hmac_sha256 is not None
    assert len(signed_manifest.signature_hmac_sha256) == 64

    ok, reasons = verify_provenance_manifest(
        graph, signed_manifest, audit_events=events, hmac_key=key
    )
    assert ok is True
    assert reasons == ()

    ok_wrong, reasons_wrong = verify_provenance_manifest(
        graph, signed_manifest, audit_events=events, hmac_key=wrong_key
    )
    assert ok_wrong is False
    assert "hmac_signature_mismatch" in reasons_wrong

    ok_no_key, reasons_no_key = verify_provenance_manifest(
        graph, signed_manifest, audit_events=events
    )
    assert ok_no_key is False
    assert "hmac_key_required" in reasons_no_key

    unsigned_manifest = build_provenance_manifest(graph, audit_events=events)
    ok_missing_sig, reasons_missing_sig = verify_provenance_manifest(
        graph, unsigned_manifest, audit_events=events, hmac_key=key
    )
    assert ok_missing_sig is False
    assert "hmac_signature_missing" in reasons_missing_sig

    with pytest.raises(ValueError, match="hmac_key must not be empty"):
        verify_provenance_manifest(graph, signed_manifest, hmac_key=b"")


def test_provenance_manifest_strict_frozen_model() -> None:
    graph, _, _ = _make_sample_graph()
    manifest = build_provenance_manifest(graph)

    with pytest.raises(ValidationError):
        manifest.graph_sha256 = "0" * 64

    with pytest.raises(ValidationError):
        ProvenanceManifest.model_validate(
            {
                "created_at_utc": "2026-01-01T00:00:00+00:00",
                "graph_sha256": "0" * 64,
                "paper_hashes": {},
                "claim_hashes": {},
                "unexpected_field": "nope",
            }
        )
