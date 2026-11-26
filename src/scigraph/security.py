"""Bearer-token RBAC and thread-safe sliding-window rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

ApiRole = Literal["reader", "ingestor", "admin"]

_ROLE_RANK: dict[ApiRole, int] = {
    "reader": 1,
    "ingestor": 2,
    "admin": 3,
}

_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def hash_bearer_token(raw_token: str) -> str:
    """Return the lowercase SHA-256 hex digest for a raw Bearer token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class TokenPolicy(BaseModel):
    """Authorization policy binding a hashed Bearer token to an org and role."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    token_sha256: str
    org_id: str
    role: ApiRole
    label: str

    @field_validator("token_sha256")
    @classmethod
    def _validate_token_sha256(cls, value: str) -> str:
        if _SHA256_HEX_RE.fullmatch(value) is None:
            raise ValueError("token_sha256 must be a 64-character hexadecimal string")
        return value.lower()


class AuthDecision(BaseModel):
    """Result of evaluating an Authorization header against an AuthGate."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    allowed: bool
    status_code: int
    reason: str
    org_id: str | None = None
    role: ApiRole | None = None


class AuthGate:
    """Bearer-token RBAC gate with constant-time digest comparison."""

    def __init__(self, policies: Sequence[TokenPolicy]) -> None:
        self._policies: tuple[TokenPolicy, ...] = tuple(policies)
        self.enabled: bool = len(self._policies) > 0

    def authorize(
        self,
        authorization_header: str | None,
        required_role: ApiRole,
    ) -> AuthDecision:
        """Authorize a request's Authorization header for the required role."""
        if not self.enabled:
            return AuthDecision(
                allowed=True,
                status_code=200,
                reason="auth disabled (open local mode)",
            )

        if authorization_header is None:
            return AuthDecision(
                allowed=False,
                status_code=401,
                reason="missing Authorization header",
            )

        parts = authorization_header.strip().split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return AuthDecision(
                allowed=False,
                status_code=401,
                reason="malformed Authorization header; expected Bearer token",
            )

        bearer_value = parts[1].strip()
        if not bearer_value or any(ch.isspace() for ch in bearer_value):
            return AuthDecision(
                allowed=False,
                status_code=401,
                reason="malformed Bearer token",
            )

        candidate_digest = hash_bearer_token(bearer_value)
        matched_policy: TokenPolicy | None = None
        for policy in self._policies:
            if hmac.compare_digest(candidate_digest, policy.token_sha256):
                matched_policy = policy

        if matched_policy is None:
            return AuthDecision(
                allowed=False,
                status_code=401,
                reason="invalid Bearer token",
            )

        if _ROLE_RANK[matched_policy.role] < _ROLE_RANK[required_role]:
            return AuthDecision(
                allowed=False,
                status_code=403,
                reason=(
                    f"insufficient role: requires {required_role}, "
                    f"token has {matched_policy.role}"
                ),
                org_id=matched_policy.org_id,
                role=matched_policy.role,
            )

        return AuthDecision(
            allowed=True,
            status_code=200,
            reason="authorized",
            org_id=matched_policy.org_id,
            role=matched_policy.role,
        )


class SlidingWindowRateLimiter:
    """Thread-safe per-client sliding-window rate limiter."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] | None = None,
        max_clients: int = 10_000,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("window_seconds must be a finite number > 0")
        if max_clients < 1:
            raise ValueError("max_clients must be >= 1")

        self._max_requests = max_requests
        self._window_seconds = float(window_seconds)
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._max_clients = max_clients
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = {}

    def _prune_windows_locked(self, cutoff: float) -> None:
        """Sweep expired buckets and evict oldest entries if still at capacity."""
        expired_keys: list[str] = []
        for key, win in self._windows.items():
            while win and win[0] <= cutoff:
                win.popleft()
            if not win:
                expired_keys.append(key)

        for key in expired_keys:
            del self._windows[key]

        while len(self._windows) >= self._max_clients:
            oldest_key = next(iter(self._windows))
            del self._windows[oldest_key]

    def check(self, client_key: str) -> tuple[bool, float]:
        """Record a request if under limit, or return (False, retry_after_seconds)."""
        with self._lock:
            now = self._clock()
            cutoff = now - self._window_seconds
            bucket = self._windows.get(client_key)
            if bucket is None:
                if len(self._windows) >= self._max_clients:
                    self._prune_windows_locked(cutoff)
                bucket = deque()
                self._windows[client_key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) < self._max_requests:
                bucket.append(now)
                return (True, 0.0)

            retry_after = max(0.0, (bucket[0] + self._window_seconds) - now)
            return (False, retry_after)
