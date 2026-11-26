from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from graph.claim_graph import ClaimGraph
from scigraph.workspace import AuditEvent


class ProvenanceManifest(BaseModel):
    """Cryptographic SHA-256 and optional HMAC-SHA256 manifest for a ClaimGraph."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    manifest_version: str = "1.0"
    created_at_utc: str
    graph_sha256: str
    paper_hashes: dict[str, str]
    claim_hashes: dict[str, str]
    audit_chain_head_sha256: str | None = None
    signature_hmac_sha256: str | None = None


def _canonical_json(obj: object) -> str:
    """Serialize a JSON-compatible object deterministically."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256_canonical(obj: object) -> str:
    """Compute SHA-256 hex digest of a canonically serialized object."""
    return hashlib.sha256(_canonical_json(obj).encode()).hexdigest()


def _signing_payload_bytes(
    *,
    manifest_version: str,
    created_at_utc: str,
    graph_sha256: str,
    paper_hashes: dict[str, str],
    claim_hashes: dict[str, str],
    audit_chain_head_sha256: str | None,
) -> bytes:
    """Build the canonical UTF-8 payload covered by the manifest HMAC signature."""
    payload = {
        "manifest_version": manifest_version,
        "created_at_utc": created_at_utc,
        "graph_sha256": graph_sha256,
        "paper_hashes": paper_hashes,
        "claim_hashes": claim_hashes,
        "audit_chain_head_sha256": audit_chain_head_sha256,
    }
    return _canonical_json(payload).encode()


def _compute_hmac_sha256(hmac_key: bytes, payload: bytes) -> str:
    """Compute HMAC-SHA256 hex digest with a non-empty key."""
    if len(hmac_key) == 0:
        raise ValueError("hmac_key must not be empty")
    return hmac.new(hmac_key, payload, hashlib.sha256).hexdigest()


def _compute_paper_hashes(graph: ClaimGraph) -> dict[str, str]:
    return {
        paper.paper_id: _sha256_canonical(paper.model_dump(mode="json"))
        for paper in sorted(graph.papers, key=lambda p: p.paper_id)
    }


def _compute_claim_hashes(graph: ClaimGraph) -> dict[str, str]:
    return {
        claim.claim_id: _sha256_canonical(claim.model_dump(mode="json"))
        for claim in sorted(graph.claims, key=lambda c: c.claim_id)
    }


def compute_audit_chain_head(audit_events: Sequence[AuditEvent]) -> str | None:
    """Compute an iterative SHA-256 hash chain over canonical JSON audit events."""
    if not audit_events:
        return None

    prev_hash = ""
    for event in audit_events:
        payload = _canonical_json(event.model_dump(mode="json"))
        chain_input = f"{prev_hash}:{payload}".encode()
        prev_hash = hashlib.sha256(chain_input).hexdigest()
    return prev_hash


def build_provenance_manifest(
    graph: ClaimGraph,
    *,
    audit_events: Sequence[AuditEvent] = (),
    hmac_key: bytes | None = None,
) -> ProvenanceManifest:
    """Generate a deterministic SHA-256 provenance manifest, optionally HMAC-signed."""
    if hmac_key is not None and len(hmac_key) == 0:
        raise ValueError("hmac_key must not be empty")

    manifest_version = "1.0"
    created_at_utc = datetime.now(UTC).isoformat()
    paper_hashes = _compute_paper_hashes(graph)
    claim_hashes = _compute_claim_hashes(graph)
    graph_sha256 = _sha256_canonical(graph.to_dict())
    audit_chain_head_sha256 = compute_audit_chain_head(audit_events)

    signature_hmac_sha256: str | None = None
    if hmac_key is not None:
        signing_payload = _signing_payload_bytes(
            manifest_version=manifest_version,
            created_at_utc=created_at_utc,
            graph_sha256=graph_sha256,
            paper_hashes=paper_hashes,
            claim_hashes=claim_hashes,
            audit_chain_head_sha256=audit_chain_head_sha256,
        )
        signature_hmac_sha256 = _compute_hmac_sha256(hmac_key, signing_payload)

    return ProvenanceManifest(
        manifest_version=manifest_version,
        created_at_utc=created_at_utc,
        graph_sha256=graph_sha256,
        paper_hashes=paper_hashes,
        claim_hashes=claim_hashes,
        audit_chain_head_sha256=audit_chain_head_sha256,
        signature_hmac_sha256=signature_hmac_sha256,
    )


def _diff_hash_maps(
    expected: dict[str, str],
    actual: dict[str, str],
    prefix: str,
) -> list[str]:
    reasons: list[str] = []
    for item_id in sorted(set(expected) | set(actual)):
        if item_id not in actual:
            reasons.append(f"{prefix}_missing:{item_id}")
        elif item_id not in expected:
            reasons.append(f"{prefix}_unexpected:{item_id}")
        elif not hmac.compare_digest(actual[item_id], expected[item_id]):
            reasons.append(f"{prefix}_hash_mismatch:{item_id}")
    return reasons


def verify_provenance_manifest(
    graph: ClaimGraph,
    manifest: ProvenanceManifest,
    *,
    audit_events: Sequence[AuditEvent] = (),
    hmac_key: bytes | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Verify graph hashes, audit chain head, and optional HMAC-SHA256 signature."""
    if hmac_key is not None and len(hmac_key) == 0:
        raise ValueError("hmac_key must not be empty")

    reasons: list[str] = []

    actual_paper_hashes = _compute_paper_hashes(graph)
    reasons.extend(_diff_hash_maps(manifest.paper_hashes, actual_paper_hashes, "paper"))

    actual_claim_hashes = _compute_claim_hashes(graph)
    reasons.extend(_diff_hash_maps(manifest.claim_hashes, actual_claim_hashes, "claim"))

    actual_graph_sha256 = _sha256_canonical(graph.to_dict())
    if not hmac.compare_digest(actual_graph_sha256, manifest.graph_sha256):
        reasons.append("graph_sha256_mismatch")

    actual_audit_head = compute_audit_chain_head(audit_events)
    if actual_audit_head != manifest.audit_chain_head_sha256:
        reasons.append("audit_chain_head_mismatch")

    if hmac_key is not None:
        if manifest.signature_hmac_sha256 is None:
            reasons.append("hmac_signature_missing")
        else:
            signing_payload = _signing_payload_bytes(
                manifest_version=manifest.manifest_version,
                created_at_utc=manifest.created_at_utc,
                graph_sha256=manifest.graph_sha256,
                paper_hashes=manifest.paper_hashes,
                claim_hashes=manifest.claim_hashes,
                audit_chain_head_sha256=manifest.audit_chain_head_sha256,
            )
            expected_sig = _compute_hmac_sha256(hmac_key, signing_payload)
            if not hmac.compare_digest(expected_sig, manifest.signature_hmac_sha256):
                reasons.append("hmac_signature_mismatch")
    elif manifest.signature_hmac_sha256 is not None:
        reasons.append("hmac_key_required")

    return (len(reasons) == 0, tuple(reasons))
