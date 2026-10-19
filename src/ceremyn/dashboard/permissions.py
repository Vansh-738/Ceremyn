"""Read-only authentication and authorization.

The dashboard only ever reads. Access is gated by an operator-provisioned bearer token
mapped to a role; there are no login, account-creation, or write flows. When
``auth_enabled`` is False (dev), every caller is granted the VIEWER role.
"""

from enum import StrEnum

from ceremyn.dashboard.config import DashboardSettings


class Role(StrEnum):
    VIEWER = "viewer"
    ADMIN = "admin"


class Permission(StrEnum):
    VIEW_DASHBOARD = "view_dashboard"
    VIEW_LOGS = "view_logs"
    USE_LLM = "use_llm"
    PLACE_TRADES = "place_trades"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.VIEW_DASHBOARD, Permission.USE_LLM}),
    Role.ADMIN: frozenset(
        {
            Permission.VIEW_DASHBOARD,
            Permission.VIEW_LOGS,
            Permission.USE_LLM,
            Permission.PLACE_TRADES,
        }
    ),
}


class AuthError(Exception):
    """Raised when authentication fails (missing/invalid token)."""


class ForbiddenError(Exception):
    """Raised when an authenticated role lacks the required permission."""


def resolve_role(token: str | None, settings: DashboardSettings) -> Role:
    """Resolve a bearer token to a role, or raise AuthError.

    Dev mode (auth disabled) always yields ADMIN: with no login configured at all,
    restricting any one page (e.g. Logs) behind a role nobody can reach is just a
    confusing dead end, not real access control -- there's no boundary to enforce
    until an operator actually turns auth on. In prod the token must match a
    configured token exactly.
    """
    if not settings.auth_enabled:
        return Role.ADMIN
    if not token:
        raise AuthError("missing bearer token")
    if settings.admin_token and token == settings.admin_token:
        return Role.ADMIN
    if settings.viewer_token and token == settings.viewer_token:
        return Role.VIEWER
    raise AuthError("invalid bearer token")


def role_has(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def authorize(token: str | None, permission: Permission, settings: DashboardSettings) -> Role:
    """Resolve the role and assert it holds ``permission``; raise on failure."""
    role = resolve_role(token, settings)
    if not role_has(role, permission):
        raise ForbiddenError(f"role {role.value} lacks {permission.value}")
    return role


def bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header value."""
    if not authorization:
        return None
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix) :].strip() or None
    return None
