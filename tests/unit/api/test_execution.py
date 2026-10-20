"""Full HTTP flow for the runtime arming router (`api/execution.py`). No database is
needed for any of this, so it lives in `tests/unit`, not the Docker-gated `tests/integration`.
"""

from fastapi.testclient import TestClient

from ceremyn.api.app import create_app
from ceremyn.config import Settings, TradingMode
from ceremyn.dashboard.config import DashboardSettings

SECRET = "super-secret-token"


def make_settings(**overrides: object) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, execution={"arming_secret": SECRET}, **overrides
    )


def make_live_settings(**overrides: object) -> Settings:
    return make_settings(trading_mode=TradingMode.LIVE, live_trading_enabled=True, **overrides)


def live_dashboard_settings() -> DashboardSettings:
    return DashboardSettings(auth_enabled=True, admin_token="ADMIN")


def test_status_defaults_to_disarmed_and_simulated() -> None:
    with TestClient(create_app(make_settings())) as client:
        body = client.get("/execution/status").json()
        assert body == {
            "armed": False,
            "live_trading_permitted": False,
            "active_broker": "simulated",
        }


def test_arm_with_wrong_token_is_forbidden() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.post("/execution/arm", json={"token": "wrong"})
        assert response.status_code == 403
        assert client.get("/execution/status").json()["armed"] is False


def test_arm_with_no_secret_configured_is_forbidden() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:  # type: ignore[call-arg]
        response = client.post("/execution/arm", json={"token": ""})
        assert response.status_code == 403


def test_arm_with_correct_token_but_gates_closed_is_conflict() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.post("/execution/arm", json={"token": SECRET, "reason": "test"})
        assert response.status_code == 409
        assert client.get("/execution/status").json()["armed"] is False


def test_arm_with_correct_token_and_gates_open_succeeds() -> None:
    with TestClient(
        create_app(make_live_settings(), dashboard_settings=live_dashboard_settings())
    ) as client:
        response = client.post(
            "/execution/arm",
            json={"token": SECRET, "reason": "ops approved"},
            headers={"Authorization": "Bearer ADMIN"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "armed": True,
            "live_trading_permitted": True,
            "active_broker": "kite",
        }
        assert client.get("/execution/status").json()["armed"] is True


def test_disarm_requires_no_token_and_always_succeeds() -> None:
    with TestClient(
        create_app(make_live_settings(), dashboard_settings=live_dashboard_settings())
    ) as client:
        client.post(
            "/execution/arm",
            json={"token": SECRET, "reason": "ops approved"},
            headers={"Authorization": "Bearer ADMIN"},
        )
        response = client.post(
            "/execution/disarm",
            json={"reason": "end of day"},
            headers={"Authorization": "Bearer ADMIN"},
        )
        assert response.status_code == 200
        assert response.json()["armed"] is False


def test_live_arming_requires_dashboard_authentication() -> None:
    with TestClient(create_app(make_live_settings())) as client:
        response = client.post("/execution/arm", json={"token": SECRET})
    assert response.status_code == 503


def test_disarm_with_empty_body_succeeds() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.post("/execution/disarm")
        assert response.status_code == 200
        assert response.json()["armed"] is False


def test_disarm_when_never_armed_is_a_no_op() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.post("/execution/disarm", json={})
        assert response.status_code == 200
        assert response.json()["armed"] is False


def test_only_get_and_post_are_exposed_under_execution() -> None:
    app = create_app(make_settings())
    methods: set[str] = set()
    for route in app.routes:  # type: ignore[attr-defined]
        path = getattr(route, "path", "")
        if path.startswith("/execution"):
            methods |= getattr(route, "methods", set()) or set()
    assert methods <= {"GET", "HEAD", "POST"}
