import json

import pytest

from scigraph.alerts import (
    AlertPayload,
    build_alert_payload,
    dispatch_webhook_alert,
)
from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    ContradictionKind,
    ContradictionPair,
    EffectDirection,
    EvidenceSpan,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)


def _make_claim(claim_id: str, direction: EffectDirection) -> ScientificClaim:
    verbatim = "Metformin altered fasting glucose (p < 0.01, n = 120)."
    return ScientificClaim(
        claim_id=claim_id,
        paper_id="paper-1",
        doi="10.1000/test-doi",
        claim_tuple=ClaimTuple(
            intervention="metformin",
            condition="type 2 diabetes",
            outcome="fasting glucose",
            direction=direction,
        ),
        statistics=StatisticalEvidence(
            p_operator=ComparisonOperator.LT,
            p_value=0.01,
            p_value_raw="p < 0.01",
            sample_size=120,
            sample_size_raw="n = 120",
        ),
        evidence_span=EvidenceSpan(
            section=SectionKind.RESULTS,
            start_char=0,
            end_char=len(verbatim),
            verbatim_text=verbatim,
        ),
    )


def _make_contradiction(contradiction_id: str = "contra-1") -> ContradictionPair:
    return ContradictionPair(
        contradiction_id=contradiction_id,
        claim_a=_make_claim("claim-a", EffectDirection.DECREASES),
        claim_b=_make_claim("claim-b", EffectDirection.INCREASES),
        kind=ContradictionKind.DIRECT_DIRECTION_CONFLICT,
        unsat_constraints=("direction(claim-a) != direction(claim-b)",),
        discriminating_factor="dosage_regimen",
    )


def test_build_alert_payload_critical_on_rejected_claims() -> None:
    contradiction = _make_contradiction("contra-1")
    payload = build_alert_payload(
        contradictions=[contradiction],
        rejected_claim_ids=["claim-bad-1", "claim-bad-2"],
    )
    assert isinstance(payload, AlertPayload)
    assert payload.event_type == "verification_failed"
    assert payload.severity == "critical"
    assert payload.rejected_claim_ids == ("claim-bad-1", "claim-bad-2")
    assert payload.contradiction_ids == ("contra-1",)
    assert payload.title
    assert payload.summary
    assert payload.timestamp_utc


def test_build_alert_payload_warning_on_contradictions() -> None:
    contradiction = _make_contradiction("contra-42")
    payload = build_alert_payload(contradictions=[contradiction])
    assert payload.event_type == "contradiction_detected"
    assert payload.severity == "warning"
    assert payload.contradiction_ids == ("contra-42",)
    assert payload.rejected_claim_ids == ()
    assert payload.title
    assert payload.summary
    assert payload.timestamp_utc


def test_build_alert_payload_info_on_pipeline_passed() -> None:
    payload = build_alert_payload(contradictions=[])
    assert payload.event_type == "pipeline_passed"
    assert payload.severity == "info"
    assert payload.contradiction_ids == ()
    assert payload.rejected_claim_ids == ()
    assert payload.title
    assert payload.summary
    assert payload.timestamp_utc


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://hooks.slack.com/services/T000/B000/XXXX",
        "https://127.0.0.1/webhook",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/webhook",
    ],
)
def test_dispatch_webhook_alert_rejects_ssrf_urls(unsafe_url: str) -> None:
    payload = build_alert_payload(contradictions=[])
    called = False

    def _sender(url: str, body: bytes) -> int:
        nonlocal called
        called = True
        return 200

    with pytest.raises(ValueError):
        dispatch_webhook_alert(unsafe_url, payload, sender=_sender)
    assert called is False


def test_dispatch_webhook_alert_success_200() -> None:
    payload = build_alert_payload(contradictions=[_make_contradiction("contra-9")])
    captured: list[tuple[str, bytes]] = []

    def _sender(url: str, body: bytes) -> int:
        captured.append((url, body))
        return 200

    target_url = "https://hooks.slack.com/services/T000/B000/XXXX"
    ok, status, message = dispatch_webhook_alert(target_url, payload, sender=_sender)

    assert ok is True
    assert status == 200
    assert "200" in message
    assert len(captured) == 1
    sent_url, sent_body = captured[0]
    assert sent_url == target_url
    decoded = json.loads(sent_body.decode("utf-8"))
    assert sent_body == json.dumps(decoded, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    assert decoded["text"] == f"[WARNING] {payload.title}: {payload.summary}"
    assert decoded["scigraph"] == payload.model_dump(mode="json")


def test_dispatch_webhook_alert_failure_500() -> None:
    payload = build_alert_payload(contradictions=[], rejected_claim_ids=["claim-x"])

    def _sender(url: str, body: bytes) -> int:
        return 500

    ok, status, message = dispatch_webhook_alert(
        "https://hooks.slack.com/services/T000/B000/XXXX",
        payload,
        sender=_sender,
    )

    assert ok is False
    assert status == 500
    assert "500" in message
