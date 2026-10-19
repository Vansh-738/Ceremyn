"""Full HTTP flow for the manual-trade router (`api/trading.py`). No database is
needed for any of this, so it lives in `tests/unit`, not the Docker-gated
`tests/integration` -- same rationale as `tests/unit/api/test_execution.py`.
"""

from datetime import time as dtime

from fastapi.testclient import TestClient

from ceremyn.api.app import create_app
from ceremyn.config import Settings
from ceremyn.dashboard.config import DashboardSettings


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def make_permissive_settings(**overrides: object) -> Settings:
    """Widens the two rules that would otherwise reject *any* single-symbol trade
    regardless of the reference-price fix under test: market-hours (irrelevant to
    what's being tested here) and cross-underlying concentration (a fresh portfolio
    with one symbol is definitionally 100% concentrated)."""
    return make_settings(
        risk={
            "time": {"trading_start": dtime(0, 0), "trading_end": dtime(23, 59)},
            "exposure": {"max_underlying_concentration_ratio": 1.0},
        },
        **overrides,
    )


def test_place_equity_trade_succeeds_in_paper_mode() -> None:
    with TestClient(create_app(make_permissive_settings())) as client:
        response = client.post(
            "/trading/equity",
            json={
                "tradingsymbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "reference_price": "1489.25",
            },
        )
        assert response.status_code == 201
        (order,) = response.json()
        assert order["tradingsymbol"] == "RELIANCE"
        assert order["side"] == "BUY"
        assert order["quantity"] == 10
        assert order["product"] == "CNC"
        assert order["execution_state"] != "REJECTED"


def test_place_equity_trade_defaults_to_cnc_product() -> None:
    with TestClient(create_app(make_permissive_settings())) as client:
        response = client.post(
            "/trading/equity",
            json={
                "tradingsymbol": "RELIANCE",
                "side": "BUY",
                "quantity": 5,
                "reference_price": "1489.25",
            },
        )
        (order,) = response.json()
        assert order["product"] == "CNC"


def test_place_equity_trade_missing_reference_price_is_unprocessable() -> None:
    with TestClient(create_app(make_permissive_settings())) as client:
        response = client.post(
            "/trading/equity",
            json={"tradingsymbol": "RELIANCE", "side": "BUY", "quantity": 10},
        )
        assert response.status_code == 422


def test_place_equity_trade_rejected_by_concentration_limit_by_default() -> None:
    """Default settings: a fresh portfolio's first trade is 100% concentrated in one
    underlying, against the default 60% limit. This is also a regression check for
    the notional/margin blind spot itself -- before that fix, an equity leg always
    priced at zero, so this rule could never have fired for an equity trade at all."""
    with TestClient(create_app(make_settings())) as client:
        response = client.post(
            "/trading/equity",
            json={
                "tradingsymbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "reference_price": "1489.25",
            },
        )
        assert response.status_code == 422
        assert "concentration" in response.json()["detail"]


def test_place_equity_trade_exit_signal_type_accepted() -> None:
    with TestClient(create_app(make_permissive_settings())) as client:
        response = client.post(
            "/trading/equity",
            json={
                "tradingsymbol": "RELIANCE",
                "side": "SELL",
                "quantity": 10,
                "reference_price": "1489.25",
                "signal_type": "EXIT",
            },
        )
        assert response.status_code == 201


def test_place_equity_trade_accepts_only_cash_delivery_product() -> None:
    with TestClient(create_app(make_permissive_settings())) as client:
        response = client.post(
            "/trading/equity",
            json={
                "tradingsymbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "reference_price": "1489.25",
                "product": "MIS",
            },
        )
        assert response.status_code == 422


def test_place_equity_trade_requires_admin_token_when_auth_is_enabled() -> None:
    settings = DashboardSettings(auth_enabled=True, admin_token="ADMIN", viewer_token="VIEW")
    request = {
        "tradingsymbol": "RELIANCE",
        "side": "BUY",
        "quantity": 10,
        "reference_price": "1489.25",
    }
    with TestClient(create_app(make_permissive_settings(), dashboard_settings=settings)) as client:
        assert client.post("/trading/equity", json=request).status_code == 401
        viewer = client.post(
            "/trading/equity", json=request, headers={"Authorization": "Bearer VIEW"}
        )
        assert viewer.status_code == 403
        admin = client.post(
            "/trading/equity", json=request, headers={"Authorization": "Bearer ADMIN"}
        )
        assert admin.status_code == 201


def test_only_get_and_post_are_exposed_under_trading() -> None:
    app = create_app(make_settings())
    methods: set[str] = set()
    for route in app.routes:  # type: ignore[attr-defined]
        path = getattr(route, "path", "")
        if path.startswith("/trading"):
            methods |= getattr(route, "methods", set()) or set()
    assert methods <= {"GET", "HEAD", "POST"}
