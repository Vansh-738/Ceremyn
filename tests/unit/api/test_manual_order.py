"""Full HTTP flow for the manual order ticket router (`api/manual_order.py`). Built
directly via `build_manual_order_router` with fake chain/instrument sources (no Postgres
needed) and a real `OrderManagementEngine` wired with `SimulatedBroker` for the submit
path — mirroring `test_execution.py`/`test_llm.py`'s shape for the equally-separate
`/execution` and `/llm` routers, and proving the submit path actually runs risk -> OMS ->
broker rather than just asserting a call was made.
"""

from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaquant.api.manual_order import build_manual_order_router
from alphaquant.broker.simulated import SimulatedBroker
from alphaquant.core.exceptions import BrokerError
from alphaquant.dashboard.config import DashboardSettings
from alphaquant.domain import (
    ChainEntry,
    Exchange,
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Quote,
)
from alphaquant.oms.engine import OrderManagementEngine
from alphaquant.risk import RiskEngine
from tests.unit.oms.conftest import permissive_settings

UNDERLYINGS = ("NIFTY", "BANKNIFTY")
EXPIRY = date(2026, 8, 14)
NIFTY_CE = OptionContract(
    tradingsymbol="NIFTY26814CE",
    exchange=Exchange.NFO,
    underlying="NIFTY",
    expiry=EXPIRY,
    strike=21500,
    option_type=OptionType.CALL,
    lot_size=75,
)
NIFTY_PE = OptionContract(
    tradingsymbol="NIFTY26814PE",
    exchange=Exchange.NFO,
    underlying="NIFTY",
    expiry=EXPIRY,
    strike=21500,
    option_type=OptionType.PUT,
    lot_size=75,
)
ADMIN_TOKEN = "admin-token"
VIEWER_TOKEN = "viewer-token"


class FakeInstrumentRepository:
    def __init__(self, contracts: tuple[OptionContract, ...] = (NIFTY_CE, NIFTY_PE)) -> None:
        self._contracts = contracts

    async def expiries(self, underlying: str, on_or_after: date) -> list[date]:
        return sorted(
            {
                c.expiry
                for c in self._contracts
                if c.underlying == underlying and c.expiry >= on_or_after
            }
        )

    async def list_contracts(self, underlying: str, expiry: date) -> list[OptionContract]:
        return [c for c in self._contracts if c.underlying == underlying and c.expiry == expiry]


class FakeChainService:
    def __init__(
        self, snapshot: OptionChainSnapshot | None = None, error: Exception | None = None
    ) -> None:
        self._snapshot = snapshot
        self._error = error

    async def build(self, underlying: str, expiry: date) -> OptionChainSnapshot:
        if self._error is not None:
            raise self._error
        assert self._snapshot is not None
        return self._snapshot


def make_snapshot() -> OptionChainSnapshot:
    now = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)
    quote = Quote(
        tradingsymbol=NIFTY_CE.tradingsymbol,
        timestamp=now,
        last_price=125,
        bid=124,
        ask=126,
    )
    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=EXPIRY,
        spot=21510,
        timestamp=now,
        entries=(
            ChainEntry(contract=NIFTY_CE, quote=quote),
            ChainEntry(contract=NIFTY_PE, quote=None),
        ),
    )


def make_app(
    *,
    chain_service: FakeChainService | None = None,
    instruments: FakeInstrumentRepository | None = None,
    oms_engine: OrderManagementEngine | None = None,
    auth_enabled: bool = True,
) -> FastAPI:
    settings = DashboardSettings(
        auth_enabled=auth_enabled, admin_token=ADMIN_TOKEN, viewer_token=VIEWER_TOKEN
    )
    engine = oms_engine or OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={"execution": SimulatedBroker()},
        default_broker="execution",
    )
    resolved_chain_service = chain_service or FakeChainService(make_snapshot())
    router = build_manual_order_router(
        chain_service_factory=lambda: resolved_chain_service,
        instruments=instruments or FakeInstrumentRepository(),
        oms_engine=engine,
        underlyings=UNDERLYINGS,
        settings=settings,
    )
    app = FastAPI()
    app.include_router(router, prefix="/manual-orders")
    return app


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def viewer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {VIEWER_TOKEN}"}


class TestReadEndpoints:
    def test_underlyings_lists_configured_underlyings(self) -> None:
        with TestClient(make_app()) as client:
            response = client.get("/manual-orders/underlyings", headers=viewer_headers())
        assert response.status_code == 200
        assert response.json() == {"underlyings": list(UNDERLYINGS)}

    def test_expiries_for_unknown_underlying_is_400(self) -> None:
        with TestClient(make_app()) as client:
            response = client.get(
                "/manual-orders/expiries", params={"underlying": "TCS"}, headers=viewer_headers()
            )
        assert response.status_code == 400

    def test_expiries_happy_path(self) -> None:
        with TestClient(make_app()) as client:
            response = client.get(
                "/manual-orders/expiries",
                params={"underlying": "NIFTY"},
                headers=viewer_headers(),
            )
        assert response.status_code == 200
        assert response.json()["expiries"] == [EXPIRY.isoformat()]

    def test_chain_missing_contracts_is_404(self) -> None:
        app = make_app(chain_service=FakeChainService(error=ValueError("no stored contracts")))
        with TestClient(app) as client:
            response = client.get(
                "/manual-orders/chain",
                params={"underlying": "NIFTY", "expiry": str(EXPIRY)},
                headers=viewer_headers(),
            )
        assert response.status_code == 404

    def test_chain_missing_kite_credentials_is_503(self) -> None:
        app = make_app(chain_service=FakeChainService(error=BrokerError("no api key")))
        with TestClient(app) as client:
            response = client.get(
                "/manual-orders/chain",
                params={"underlying": "NIFTY", "expiry": str(EXPIRY)},
                headers=viewer_headers(),
            )
        assert response.status_code == 503

    def test_chain_happy_path_auto_fills_premium(self) -> None:
        with TestClient(make_app()) as client:
            response = client.get(
                "/manual-orders/chain",
                params={"underlying": "NIFTY", "expiry": str(EXPIRY)},
                headers=viewer_headers(),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["spot"] == "21510"
        ce_entry = next(e for e in body["entries"] if e["option_type"] == "CE")
        assert ce_entry["last_price"] == "125"


class TestSubmit:
    def test_unknown_contract_is_404(self) -> None:
        with TestClient(make_app()) as client:
            response = client.post(
                "/manual-orders/submit",
                json={
                    "underlying": "NIFTY",
                    "expiry": str(EXPIRY),
                    "strike": "99999",
                    "option_type": "CE",
                    "side": "BUY",
                    "lots": 1,
                },
                headers=admin_headers(),
            )
        assert response.status_code == 404

    def test_risk_rejection_surfaces_violations_as_422(self) -> None:
        restrictive = permissive_settings()
        restrictive.risk.position.max_lots_per_signal = 1
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(restrictive),
            brokers={"execution": SimulatedBroker()},
            default_broker="execution",
        )
        with TestClient(make_app(oms_engine=engine)) as client:
            response = client.post(
                "/manual-orders/submit",
                json={
                    "underlying": "NIFTY",
                    "expiry": str(EXPIRY),
                    "strike": "21500",
                    "option_type": "CE",
                    "side": "BUY",
                    "lots": 50,
                },
                headers=admin_headers(),
            )
        assert response.status_code == 422
        assert "lots" in response.json()["detail"].lower()

    def test_happy_path_builds_correct_signal_and_fills(self) -> None:
        with TestClient(make_app()) as client:
            response = client.post(
                "/manual-orders/submit",
                json={
                    "underlying": "NIFTY",
                    "expiry": str(EXPIRY),
                    "strike": "21500",
                    "option_type": "CE",
                    "side": "BUY",
                    "lots": 2,
                },
                headers=admin_headers(),
            )
        assert response.status_code == 200
        orders = response.json()["orders"]
        assert len(orders) == 1
        assert orders[0]["tradingsymbol"] == NIFTY_CE.tradingsymbol
        assert orders[0]["side"] == "BUY"
        assert orders[0]["quantity"] == 2 * NIFTY_CE.lot_size

    def test_submit_without_submit_order_permission_is_403(self) -> None:
        with TestClient(make_app()) as client:
            response = client.post(
                "/manual-orders/submit",
                json={
                    "underlying": "NIFTY",
                    "expiry": str(EXPIRY),
                    "strike": "21500",
                    "option_type": "CE",
                    "side": "BUY",
                    "lots": 1,
                },
                headers=viewer_headers(),
            )
        assert response.status_code == 403

    def test_submit_requires_bearer_token_when_auth_enabled(self) -> None:
        with TestClient(make_app()) as client:
            response = client.post(
                "/manual-orders/submit",
                json={
                    "underlying": "NIFTY",
                    "expiry": str(EXPIRY),
                    "strike": "21500",
                    "option_type": "CE",
                    "side": "BUY",
                    "lots": 1,
                },
            )
        assert response.status_code == 401

    def test_submit_unreachable_when_auth_disabled_default(self) -> None:
        # auth_enabled=False -> resolve_role always returns VIEWER, which lacks
        # SUBMIT_ORDER -> 403, even with no token at all. This is the safe-by-default
        # posture: no order (not even simulated) is placeable on an unconfigured instance.
        with TestClient(make_app(auth_enabled=False)) as client:
            response = client.post(
                "/manual-orders/submit",
                json={
                    "underlying": "NIFTY",
                    "expiry": str(EXPIRY),
                    "strike": "21500",
                    "option_type": "CE",
                    "side": "BUY",
                    "lots": 1,
                },
            )
        assert response.status_code == 403


def test_only_get_and_post_are_exposed_under_manual_orders() -> None:
    app = make_app()
    methods: set[str] = set()
    for route in app.routes:  # type: ignore[attr-defined]
        path = getattr(route, "path", "")
        if path.startswith("/manual-orders"):
            methods |= getattr(route, "methods", set()) or set()
    assert methods <= {"GET", "HEAD", "POST"}
