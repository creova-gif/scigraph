import ipaddress
import socket
import urllib.parse
import urllib.request
from http.client import HTTPMessage
from typing import IO

__all__ = [
    "NoRedirectHandler",
    "assert_public_dns_resolution",
    "is_non_public_ip",
    "validate_public_https_url",
]


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
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


def is_non_public_ip(ip_str: str) -> bool:
    """Return True if the IP string (with optional IPv6 scope suffix) is non-public."""
    clean_ip = ip_str.split("%", 1)[0]
    ip = ipaddress.ip_address(clean_ip)
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    )


def assert_public_dns_resolution(hostname: str) -> None:
    """Resolve hostname via DNS and verify every returned IP address is public."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise ValueError(f"DNS resolution failed for hostname {hostname!r}: {exc}") from exc

    if not addr_infos:
        raise ValueError(f"DNS resolution returned no addresses for hostname {hostname!r}")

    for info in addr_infos:
        raw_ip = str(info[4][0]).split("%", 1)[0]
        if is_non_public_ip(raw_ip):
            raise ValueError(
                f"Refusing hostname {hostname!r} resolving to non-public IP {raw_ip!r}"
            )


def validate_public_https_url(url: str, *, label: str = "URL") -> str:
    """Validate that a URL is a safe public HTTPS URL (SSRF guard)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(
            f"Only https:// {label}s are allowed, got scheme {parsed.scheme!r}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{label} must include a non-empty hostname")

    normalized_host = hostname.lower().rstrip(".")
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError(f"Refusing localhost {label}: {hostname!r}")

    try:
        non_public = is_non_public_ip(hostname)
    except ValueError:
        non_public = False

    if non_public:
        raise ValueError(f"Refusing non-public IP literal in {label}: {hostname!r}")

    return url
