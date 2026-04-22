"""Phase 3 §8.4 authorised-user access control: JWT + 3 roles."""
from .jwt_service import JwtService, TokenPayload, make_service
from .users import (
    ROLES,
    Role,
    UsersRepository,
    ensure_default_users,
)
from .deps import (
    AuthContext,
    get_auth_context,
    require_role,
    set_service,
)

__all__ = [
    "JwtService",
    "TokenPayload",
    "make_service",
    "ROLES",
    "Role",
    "UsersRepository",
    "ensure_default_users",
    "AuthContext",
    "get_auth_context",
    "require_role",
    "set_service",
]
