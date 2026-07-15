import pytest

from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.permissions import (
    AuthError,
    ForbiddenError,
    Permission,
    Role,
    authorize,
    bearer_token,
    resolve_role,
    role_has,
)


def settings(**over: object) -> DashboardSettings:
    base = {"auth_enabled": True, "admin_token": "ADMIN", "viewer_token": "VIEW"}
    base.update(over)
    return DashboardSettings(**base)  # type: ignore[arg-type]


class TestResolveRole:
    def test_dev_mode_grants_viewer(self) -> None:
        assert resolve_role(None, DashboardSettings(auth_enabled=False)) is Role.VIEWER

    def test_admin_token(self) -> None:
        assert resolve_role("ADMIN", settings()) is Role.ADMIN

    def test_viewer_token(self) -> None:
        assert resolve_role("VIEW", settings()) is Role.VIEWER

    def test_missing_token_raises(self) -> None:
        with pytest.raises(AuthError, match="missing"):
            resolve_role(None, settings())

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(AuthError, match="invalid"):
            resolve_role("nope", settings())


class TestPermissions:
    def test_role_has(self) -> None:
        assert role_has(Role.ADMIN, Permission.VIEW_LOGS)
        assert not role_has(Role.VIEWER, Permission.VIEW_LOGS)
        assert role_has(Role.VIEWER, Permission.VIEW_DASHBOARD)

    def test_authorize_allows(self) -> None:
        assert authorize("VIEW", Permission.VIEW_DASHBOARD, settings()) is Role.VIEWER

    def test_authorize_forbidden(self) -> None:
        with pytest.raises(ForbiddenError, match="lacks"):
            authorize("VIEW", Permission.VIEW_LOGS, settings())

    def test_authorize_admin_logs(self) -> None:
        assert authorize("ADMIN", Permission.VIEW_LOGS, settings()) is Role.ADMIN


class TestBearerToken:
    def test_extracts_token(self) -> None:
        assert bearer_token("Bearer abc123") == "abc123"

    def test_none_and_malformed(self) -> None:
        assert bearer_token(None) is None
        assert bearer_token("Basic abc") is None
        assert bearer_token("Bearer ") is None
