"""HS256 JWT issuance + verification. Keeps the surface tiny on purpose."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

LOG = logging.getLogger(__name__)

_DEFAULT_TTL_MIN = 30


@dataclass(frozen=True)
class TokenPayload:
    username: str
    role: str
    exp: int  # unix seconds


class JwtService:
    def __init__(self, secret: str, ttl_minutes: int = _DEFAULT_TTL_MIN,
                 issuer: str = "traffic-intel") -> None:
        if not secret:
            raise ValueError("JWT secret must be non-empty")
        self._secret = secret
        self._ttl_minutes = ttl_minutes
        self._issuer = issuer

    def issue(self, username: str, role: str) -> tuple[str, TokenPayload]:
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=self._ttl_minutes)
        payload = {
            "sub": username,
            "role": role,
            "iss": self._issuer,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        return token, TokenPayload(username=username, role=role, exp=payload["exp"])

    def verify(self, token: str) -> TokenPayload:
        payload = jwt.decode(token, self._secret, algorithms=["HS256"],
                             options={"require": ["exp", "iat", "sub", "role"]},
                             issuer=self._issuer)
        return TokenPayload(
            username=payload["sub"], role=payload["role"], exp=int(payload["exp"])
        )


def make_service() -> JwtService:
    """Build a JwtService from env. Secret must be set in production.

    Fallback: a per-process random secret (dev-only; tokens don't survive restarts).
    """
    secret = os.getenv("TRAFFIC_INTEL_JWT_SECRET")
    if not secret:
        import secrets
        secret = secrets.token_urlsafe(32)
        LOG.warning("TRAFFIC_INTEL_JWT_SECRET not set; using an ephemeral random secret "
                    "(tokens will be invalidated on process restart)")
    ttl = int(os.getenv("TRAFFIC_INTEL_JWT_TTL_MIN", _DEFAULT_TTL_MIN))
    return JwtService(secret=secret, ttl_minutes=ttl)
