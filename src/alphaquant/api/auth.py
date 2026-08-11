"""Shared FastAPI auth dependency for routers that reuse the dashboard's bearer-token
mechanism (`alphaquant.dashboard.permissions`). Extracted from `api/llm.py` (M12's original
home for this) once `api/manual_order.py` needed the identical dependency-factory shape —
one implementation, two callers, rather than a second copy.
"""

from collections.abc import Callable

from fastapi import Header, HTTPException

from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.permissions import (
    AuthError,
    ForbiddenError,
    Permission,
    Role,
    authorize,
    bearer_token,
)


def require_permission(
    permission: Permission, settings: DashboardSettings
) -> Callable[[str | None], Role]:
    def dependency(authorization: str | None = Header(default=None)) -> Role:
        token = bearer_token(authorization)
        try:
            return authorize(token, permission, settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return dependency
