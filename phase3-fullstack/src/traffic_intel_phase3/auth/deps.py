"""FastAPI dependencies for JWT auth + role-based access control."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from .jwt_service import JwtService, TokenPayload, make_service

_ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}
_bearer = HTTPBearer(auto_error=False)
_service: JwtService | None = None


def set_service(svc: JwtService) -> None:
    """Install the JWT service used by get_auth_context. Call this at server
    startup so the login route and the auth dependency share one secret."""
    global _service
    _service = svc


def _svc() -> JwtService:
    global _service
    if _service is None:
        _service = make_service()
    return _service


@dataclass(frozen=True)
class AuthContext:
    username: str
    role: str


def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    elif "token" in request.query_params:
        # WebSocket-friendly fallback (browsers can't set headers on WS).
        token = request.query_params["token"]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing token")
    try:
        payload: TokenPayload = _svc().verify(token)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {exc}") from exc
    return AuthContext(username=payload.username, role=payload.role)


def require_role(min_role: str) -> Callable[[AuthContext], AuthContext]:
    """Return a FastAPI dependency that demands at least ``min_role``."""
    if min_role not in _ROLE_RANK:
        raise ValueError(f"unknown role: {min_role}")
    floor = _ROLE_RANK[min_role]

    def _dep(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if _ROLE_RANK.get(ctx.role, -1) < floor:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail=f"role {ctx.role} lacks {min_role}")
        return ctx

    return _dep
