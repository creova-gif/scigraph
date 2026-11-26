import io
import socket
import urllib.request
from http.client import HTTPMessage

import pytest

from scigraph.net_guard import (
    NoRedirectHandler,
    assert_public_dns_resolution,
    is_non_public_ip,
    validate_public_https_url,
)

type _AddrInfoList = list[
    tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]
]


@pytest.mark.parametrize(
    ("ip_str", "expected"),
    [
        ("93.184.216.34", False),
        ("8.8.8.8", False),
        ("2606:2800:220:1:248:1893:25c8:1946", False),
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("172.16.0.1", True),
        ("192.168.1.1", True),
        ("169.254.169.254", True),
        ("100.64.0.1", True),
        ("0.0.0.0", True),
        ("224.0.0.1", True),
        ("240.0.0.1", True),
        ("::1", True),
        ("::", True),
        ("fc00::1", True),
        ("fe80::1", True),
        ("fe80::1%eth0", True),
        ("fe80::1%en0", True),
        ("fec0::1", True),
        ("::1%lo0", True),
        ("::ffff:127.0.0.1", True),
    ],
)
def test_is_non_public_ip(ip_str: str, expected: bool) -> None:
    assert is_non_public_ip(ip_str) is expected


def test_is_non_public_ip_rejects_invalid_ip() -> None:
    with pytest.raises(ValueError):
        is_non_public_ip("not-an-ip")


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://example.org/resource",
        "file:///etc/passwd",
        "ftp://example.org/file",
        "https:///missing-host",
        "https://",
        "https://localhost/api",
        "https://LOCALHOST./api",
        "https://sub.localhost/api",
        "https://sub.localhost./api",
        "https://127.0.0.1/api",
        "https://10.0.0.1/internal",
        "https://172.16.0.5/internal",
        "https://192.168.1.10/internal",
        "https://169.254.169.254/latest/meta-data",
        "https://100.64.0.1/internal",
        "https://0.0.0.0/",
        "https://224.0.0.1/",
        "https://[::1]/api",
        "https://[fe80::1]/api",
        "https://[fc00::1]/api",
        "https://[::ffff:127.0.0.1]/api",
    ],
)
def test_validate_public_https_url_rejects_ssrf_targets(unsafe_url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_https_url(unsafe_url)


@pytest.mark.parametrize(
    "valid_url",
    [
        "https://export.arxiv.org/api/query?search_query=all:test",
        "https://hooks.slack.com/services/T000/B000/XXXX",
        "https://93.184.216.34/resource",
    ],
)
def test_validate_public_https_url_accepts_public_https(valid_url: str) -> None:
    assert validate_public_https_url(valid_url) == valid_url


def test_validate_public_https_url_uses_custom_label() -> None:
    with pytest.raises(ValueError, match="webhook URL"):
        validate_public_https_url("http://example.org/hook", label="webhook URL")
    with pytest.raises(ValueError, match="webhook URL"):
        validate_public_https_url("https://localhost/hook", label="webhook URL")


def test_assert_public_dns_resolution_accepts_public_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, port: object) -> _AddrInfoList:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 0),
            ),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert_public_dns_resolution("example.org")


@pytest.mark.parametrize(
    "resolved_ips",
    [
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["100.64.0.1"],
        ["10.0.0.1"],
        ["fe80::1%eth0"],
        ["93.184.216.34", "127.0.0.1"],
    ],
)
def test_assert_public_dns_resolution_blocks_non_public_ips(
    monkeypatch: pytest.MonkeyPatch,
    resolved_ips: list[str],
) -> None:
    def fake_getaddrinfo(host: str, port: object) -> _AddrInfoList:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
            for ip in resolved_ips
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="non-public IP"):
        assert_public_dns_resolution("rebind.example.org")


def test_assert_public_dns_resolution_rejects_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_getaddrinfo(host: str, port: object) -> _AddrInfoList:
        return []

    monkeypatch.setattr(socket, "getaddrinfo", empty_getaddrinfo)
    with pytest.raises(ValueError, match="returned no addresses"):
        assert_public_dns_resolution("empty.example.org")


def test_assert_public_dns_resolution_handles_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_getaddrinfo(host: str, port: object) -> _AddrInfoList:
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    with pytest.raises(ValueError, match="DNS resolution failed"):
        assert_public_dns_resolution("missing.example.org")


@pytest.mark.parametrize("status_code", [301, 302, 307, 308])
def test_no_redirect_handler_blocks_redirects(status_code: int) -> None:
    handler = NoRedirectHandler()
    req = urllib.request.Request("https://example.org/resource")
    headers = HTTPMessage()
    headers["Location"] = "https://127.0.0.1/admin"

    method = getattr(handler, f"http_error_{status_code}")
    with pytest.raises(ValueError, match="HTTP redirects are blocked by SSRF policy"):
        method(req, io.BytesIO(b""), status_code, "Redirect", headers)
