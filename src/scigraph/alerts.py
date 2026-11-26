import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from scigraph.models import ContradictionPair
from scigraph.net_guard import (
    NoRedirectHandler,
    assert_public_dns_resolution,
    validate_public_https_url,
)

AlertSeverity = Literal["critical", "warning", "info"]
AlertEventType = Literal["contradiction_detected", "verification_failed", "pipeline_passed"]
WebhookSender = Callable[[str, bytes], int]

_NoRedirectHandler = NoRedirectHandler
_assert_public_dns_resolution = assert_public_dns_resolution


class AlertPayload(BaseModel):
    """Structured webhook/Slack alert payload for SciGraph pipeline events."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    event_type: AlertEventType
    severity: AlertSeverity
    title: str
    summary: str
    contradiction_ids: tuple[str, ...]
    rejected_claim_ids: tuple[str, ...]
    timestamp_utc: str


def _validate_https_webhook_url(url: str) -> str:
    """Validate that a webhook URL is a safe public HTTPS URL (SSRF guard)."""
    return validate_public_https_url(url, label="webhook URL")


def build_alert_payload(
    contradictions: Sequence[ContradictionPair],
    rejected_claim_ids: Sequence[str] = (),
) -> AlertPayload:
    """Build a structured AlertPayload from detected contradictions and rejected claims."""
    contradiction_ids = tuple(pair.contradiction_id for pair in contradictions)
    rejected_ids = tuple(rejected_claim_ids)
    timestamp_utc = datetime.now(UTC).isoformat()

    if rejected_ids:
        event_type: AlertEventType = "verification_failed"
        severity: AlertSeverity = "critical"
        title = "SciGraph verification failed"
        summary = (
            f"{len(rejected_ids)} claim(s) failed deterministic verification; "
            f"{len(contradiction_ids)} contradiction(s) detected."
        )
    elif contradiction_ids:
        event_type = "contradiction_detected"
        severity = "warning"
        title = "SciGraph contradictions detected"
        summary = f"Detected {len(contradiction_ids)} contradiction(s) across verified claims."
    else:
        event_type = "pipeline_passed"
        severity = "info"
        title = "SciGraph pipeline passed"
        summary = "All claims verified with 0 contradictions detected."

    return AlertPayload(
        event_type=event_type,
        severity=severity,
        title=title,
        summary=summary,
        contradiction_ids=contradiction_ids,
        rejected_claim_ids=rejected_ids,
        timestamp_utc=timestamp_utc,
    )


def dispatch_webhook_alert(
    webhook_url: str,
    payload: AlertPayload,
    *,
    sender: WebhookSender | None = None,
    timeout: float = 10.0,
) -> tuple[bool, int, str]:
    """Validate webhook_url against SSRF and POST compact JSON alert payload."""
    validated_url = _validate_https_webhook_url(webhook_url)
    envelope = {
        "text": f"[{payload.severity.upper()}] {payload.title}: {payload.summary}",
        "scigraph": payload.model_dump(mode="json"),
    }
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    if sender is not None:
        status = sender(validated_url, body)
        ok = 200 <= status < 300
        message = f"Webhook returned HTTP {status}"
        return (ok, status, message)

    hostname = urllib.parse.urlsplit(validated_url).hostname
    if not hostname:
        raise ValueError("URL must include a non-empty hostname")
    _assert_public_dns_resolution(hostname)

    request = urllib.request.Request(
        validated_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            ok = 200 <= status < 300
            return (ok, status, f"Webhook returned HTTP {status}")
    except urllib.error.HTTPError as exc:
        return (False, int(exc.code), f"Webhook returned HTTP {exc.code}: {exc.reason}")
