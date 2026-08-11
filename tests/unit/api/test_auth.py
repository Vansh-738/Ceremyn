"""Direct coverage for the shared auth dependency factory (`api/auth.py`), extracted from
`api/llm.py` once `api/manual_order.py` needed the identical shape. HTTP-level coverage of
each caller stays in `test_llm.py`/`test_manual_order.py`; this file only covers the
dependency-factory mapping itself.
"""

import pytest
from fastapi import HTTPException

from alphaquant.api.auth import require_permission
from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.permissions import Permission

ADMIN_TOKEN = "admin-token"
VIEWER_TOKEN = "viewer-token"


def make_settings(**overrides: object) -> DashboardSettings:
    base: dict[str, object] = {
        "auth_enabled": True,
        "admin_token": ADMIN_TOKEN,
        "viewer_token": VIEWER_TOKEN,
    }
    base.update(overrides)
    return DashboardSettings(**base)  # type: ignore[arg-type]


def test_missing_token_is_401() -> None:
    dependency = require_permission(Permission.VIEW_DASHBOARD, make_settings())
    with pytest.raises(HTTPException) as exc_info:
        dependency(None)
    assert exc_info.value.status_code == 401


def test_invalid_token_is_401() -> None:
    dependency = require_permission(Permission.VIEW_DASHBOARD, make_settings())
    with pytest.raises(HTTPException) as exc_info:
        dependency("Bearer nope")
    assert exc_info.value.status_code == 401


def test_valid_token_lacking_permission_is_403() -> None:
    dependency = require_permission(Permission.VIEW_LOGS, make_settings())
    with pytest.raises(HTTPException) as exc_info:
        dependency(f"Bearer {VIEWER_TOKEN}")
    assert exc_info.value.status_code == 403


def test_valid_token_with_permission_resolves_role() -> None:
    from alphaquant.dashboard.permissions import Role

    dependency = require_permission(Permission.VIEW_DASHBOARD, make_settings())
    assert dependency(f"Bearer {VIEWER_TOKEN}") is Role.VIEWER


def test_dev_mode_grants_viewer_regardless_of_token() -> None:
    from alphaquant.dashboard.permissions import Role

    dependency = require_permission(
        Permission.VIEW_DASHBOARD, DashboardSettings(auth_enabled=False)
    )
    assert dependency(None) is Role.VIEWER
