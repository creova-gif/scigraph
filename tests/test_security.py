"""Deterministic tests for Bearer-token RBAC and sliding-window rate limiting."""

from __future__ import annotations

import hashlib
import math

import pytest
from pydantic import ValidationError

from scigraph.security import (
    AuthDecision,
    AuthGate,
    SlidingWindowRateLimiter,
    TokenPolicy,
    hash_bearer_token,
)


class FakeClock:
    """Deterministic monotonic clock for rate-limiter tests."""

    def __init__(self, initial: float = 100.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_hash_bearer_token_matches_lowercase_sha256() -> None:
    raw = "sg_live_secret_token"
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    digest = hash_bearer_token(raw)
    assert digest == expected
    assert len(digest) == 64
    assert digest == digest.lower()


def test_token_policy_validation_and_immutability() -> None:
    upper_digest = hash_bearer_token("tok-1").upper()
    policy = TokenPolicy(
        token_sha256=upper_digest,
        org_id="org-alpha",
        role="reader",
        label="ci-reader",
    )
    assert policy.token_sha256 == upper_digest.lower()

    with pytest.raises(ValidationError):
        TokenPolicy(
            token_sha256="short",
            org_id="org-alpha",
            role="reader",
            label="bad",
        )

    with pytest.raises(ValidationError):
        TokenPolicy(
            token_sha256="g" * 64,
            org_id="org-alpha",
            role="reader",
            label="non-hex",
        )

    with pytest.raises(ValidationError):
        TokenPolicy(
            token_sha256=upper_digest,
            org_id="org-alpha",
            role="reader",
            label="extra",
            extra_field="nope",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        policy.org_id = "org-beta"


def test_auth_decision_model_defaults_and_strictness() -> None:
    decision = AuthDecision(allowed=True, status_code=200, reason="ok")
    assert decision.org_id is None
    assert decision.role is None

    with pytest.raises(ValidationError):
        AuthDecision(allowed="yes", status_code=200, reason="bad-type")  # type: ignore[arg-type]


def test_auth_gate_disabled_open_local_mode() -> None:
    gate = AuthGate([])
    assert gate.enabled is False

    decision = gate.authorize(None, "admin")
    assert decision.allowed is True
    assert decision.status_code == 200
    assert decision.org_id is None
    assert decision.role is None


def test_auth_gate_missing_malformed_and_unknown_tokens() -> None:
    valid_token = "secret-reader-token"
    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token(valid_token),
                org_id="org-1",
                role="reader",
                label="reader-key",
            )
        ]
    )
    assert gate.enabled is True

    for bad_header in (
        None,
        "",
        "   ",
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer   ",
        "Bearer token with spaces",
        "Bearer wrong-token",
    ):
        decision = gate.authorize(bad_header, "reader")
        assert decision.allowed is False
        assert decision.status_code == 401
        assert decision.org_id is None
        assert decision.role is None


def test_auth_gate_case_insensitive_bearer_prefix() -> None:
    token = "case-prefix-token"
    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token(token),
                org_id="org-case",
                role="ingestor",
                label="ingestor-key",
            )
        ]
    )

    for prefix in ("Bearer", "bearer", "BEARER", "BeArEr"):
        decision = gate.authorize(f"  {prefix} {token}  ", "ingestor")
        assert decision.allowed is True
        assert decision.status_code == 200
        assert decision.org_id == "org-case"
        assert decision.role == "ingestor"


def test_auth_gate_role_hierarchy() -> None:
    reader_tok = "tok-reader"
    ingestor_tok = "tok-ingestor"
    admin_tok = "tok-admin"

    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token(reader_tok),
                org_id="org-r",
                role="reader",
                label="r",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token(ingestor_tok),
                org_id="org-i",
                role="ingestor",
                label="i",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token(admin_tok),
                org_id="org-a",
                role="admin",
                label="a",
            ),
        ]
    )

    # Reader can only access reader
    assert gate.authorize(f"Bearer {reader_tok}", "reader").status_code == 200
    r_ing = gate.authorize(f"Bearer {reader_tok}", "ingestor")
    assert r_ing.allowed is False
    assert r_ing.status_code == 403
    assert r_ing.org_id == "org-r"
    assert r_ing.role == "reader"

    r_adm = gate.authorize(f"Bearer {reader_tok}", "admin")
    assert r_adm.allowed is False
    assert r_adm.status_code == 403

    # Ingestor can access reader and ingestor, not admin
    assert gate.authorize(f"Bearer {ingestor_tok}", "reader").status_code == 200
    assert gate.authorize(f"Bearer {ingestor_tok}", "ingestor").status_code == 200
    i_adm = gate.authorize(f"Bearer {ingestor_tok}", "admin")
    assert i_adm.allowed is False
    assert i_adm.status_code == 403
    assert i_adm.org_id == "org-i"
    assert i_adm.role == "ingestor"

    # Admin can access all roles
    assert gate.authorize(f"Bearer {admin_tok}", "reader").status_code == 200
    assert gate.authorize(f"Bearer {admin_tok}", "ingestor").status_code == 200
    adm_adm = gate.authorize(f"Bearer {admin_tok}", "admin")
    assert adm_adm.allowed is True
    assert adm_adm.status_code == 200
    assert adm_adm.org_id == "org-a"
    assert adm_adm.role == "admin"


def test_rate_limiter_parameter_validation() -> None:
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=0, window_seconds=10.0)

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=5, window_seconds=0.0)

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=5, window_seconds=-1.0)

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=5, window_seconds=math.nan)

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=5, window_seconds=math.inf)

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=5, window_seconds=10.0, max_clients=0)


def test_rate_limiter_sliding_window_and_retry_after() -> None:
    clock = FakeClock(initial=100.0)
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10.0, clock=clock)

    # First request at t=100.0
    assert limiter.check("client-a") == (True, 0.0)

    # Second request at t=104.0
    clock.advance(4.0)
    assert limiter.check("client-a") == (True, 0.0)

    # Third request at t=106.0 -> throttled (429 equivalent), oldest at 100.0 expires at 110.0
    clock.advance(2.0)
    allowed, retry_after = limiter.check("client-a")
    assert allowed is False
    assert retry_after == pytest.approx(4.0)

    # Independent client key is unaffected
    assert limiter.check("client-b") == (True, 0.0)

    # At t=110.0, timestamp 100.0 is <= 110.0 - 10.0 so it is pruned; 104.0 remains
    clock.advance(4.0)
    assert limiter.check("client-a") == (True, 0.0)

    # Next request at t=110.0 is throttled until 104.0 + 10.0 = 114.0 (retry_after == 4.0)
    allowed2, retry_after2 = limiter.check("client-a")
    assert allowed2 is False
    assert retry_after2 == pytest.approx(4.0)

    # At t=120.0, all previous timestamps are expired
    clock.advance(10.0)
    assert limiter.check("client-a") == (True, 0.0)
    assert limiter.check("client-a") == (True, 0.0)


def test_rate_limiter_sweeps_expired_buckets_at_cap() -> None:
    clock = FakeClock(initial=100.0)
    limiter = SlidingWindowRateLimiter(
        max_requests=1,
        window_seconds=10.0,
        clock=clock,
        max_clients=3,
    )

    assert limiter.check("c1") == (True, 0.0)
    assert limiter.check("c2") == (True, 0.0)
    assert limiter.check("c3") == (True, 0.0)
    assert len(limiter._windows) == 3

    # Advance past window so c1, c2, c3 are all expired
    clock.advance(11.0)
    assert limiter.check("c4") == (True, 0.0)
    assert list(limiter._windows.keys()) == ["c4"]


def test_rate_limiter_preserves_active_windows_and_fails_closed_at_cap() -> None:
    clock = FakeClock(initial=100.0)
    limiter = SlidingWindowRateLimiter(
        max_requests=1,
        window_seconds=10.0,
        clock=clock,
        max_clients=3,
    )

    assert limiter.check("c1") == (True, 0.0)
    clock.advance(1.0)
    assert limiter.check("c2") == (True, 0.0)
    clock.advance(1.0)
    assert limiter.check("c3") == (True, 0.0)
    assert len(limiter._windows) == 3

    # At t=102.0 no buckets are expired; c4 must fail closed without evicting c1..c3
    c4_allowed, c4_retry = limiter.check("c4")
    assert c4_allowed is False
    assert c4_retry == pytest.approx(8.0)
    assert len(limiter._windows) == 3
    assert set(limiter._windows.keys()) == {"c1", "c2", "c3"}

    # c1 is still rate-limited within its window (not evicted)
    c1_allowed, c1_retry = limiter.check("c1")
    assert c1_allowed is False
    assert c1_retry == pytest.approx(8.0)

    # Once c1's window expires at t=110.0, expired bucket c1 is swept and c4 is admitted
    clock.advance(8.0)
    assert limiter.check("c4") == (True, 0.0)
    assert set(limiter._windows.keys()) == {"c2", "c3", "c4"}
