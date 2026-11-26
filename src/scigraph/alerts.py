import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from http.client import HTTPMessage
from typing import IO, Literal

from pydantic import BaseModel, ConfigDict

from scigraph.models import ContradictionPair

AlertSeverity = Literal["critical", "warning", "info"]
AlertEventType = Literal["contradiction_detected", "verification_failed", "pipeline_passed"]
WebhookSender = Callable[[str, bytes], int]


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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP redirect handler that blocks all redirects to prevent SSRF bypasses."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise ValueError("HTTP redirects are blocked by SSRF policy")


def _is_non_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _assert_public_dns_resolution(hostname: str) -> None:
    """Resolve hostname via DNS and verify every returned IP address is public."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise ValueError(f"DNS resolution failed for hostname {hostname!r}: {exc}") from exc

    if not addr_infos:
        raise ValueError(f"DNS resolution returned no addresses for hostname {hostname!r}")

    for info in addr_infos:
        raw_ip = str(info[4][0]).split("%", 1)[0]
        ip = ipaddress.ip_address(raw_ip)
        if _is_non_public_ip(ip):
            raise ValueError(
                f"Refusing hostname {hostname!r} resolving to non-public IP {raw_ip!r}"
            )


def _validate_https_webhook_url(url: str) -> str:
    """Validate that a webhook URL is a safe public HTTPS URL (SSRF guard)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Only https:// URLs are allowed, got scheme {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a non-empty hostname")

    normalized_host = hostname.lower().rstrip(".")
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError(f"Refusing localhost URL: {hostname!r}")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None and _is_non_public_ip(ip):
        raise ValueError(f"Refusing non-public IP literal in URL: {hostname!r}")

    return url


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
