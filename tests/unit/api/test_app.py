from fastapi.testclient import TestClient

from alphaquant.api.app import create_app
from alphaquant.config import Settings, TradingMode


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_health() -> None:
    client = TestClient(create_app(make_settings()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_status_reports_gate_degradation() -> None:
    # Mode set to live but the config gate is closed -> effective mode is paper.
    settings = make_settings(trading_mode=TradingMode.LIVE, live_trading_enabled=False)
    client = TestClient(create_app(settings))
    body = client.get("/system/status").json()
    assert body["configured_mode"] == "live"
    assert body["effective_mode"] == "paper"
    assert body["live_trading_enabled"] is False


def test_system_status_defaults() -> None:
    client = TestClient(create_app(make_settings()))
    body = client.get("/system/status").json()
    assert body["configured_mode"] == "research"
    assert body["effective_mode"] == "research"
