"""Full HTTP flow for the read-only opportunities router (`api/opportunities.py`).
No database or real network fetch is needed -- `fetch_all_equity_candles` and
`find_opportunities` are monkeypatched so this only verifies the router's own
wiring/serialization, not pattern-detection correctness (already covered by
tests/unit/patterns/test_opportunity.py). The background periodic scan itself
is exercised by calling `run_scan_once` directly, the same way
`run_periodic_scan` would -- no real network I/O and no sleeping.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import ceremyn.api.opportunities as opportunities_module
from ceremyn.api.app import create_app
from ceremyn.config import OpportunitiesSettings, Settings
from ceremyn.domain import Candle, Opportunity, TimeFrame
from ceremyn.domain.enums import AssetClass, PatternDirection


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def make_opportunity(tradingsymbol: str = "RELIANCE") -> Opportunity:
    return Opportunity(
        tradingsymbol=tradingsymbol,
        asset_class=AssetClass.EQUITY,
        pattern_name="HAMMER",
        direction=PatternDirection.BULLISH,
        detected_at=datetime(2026, 8, 7, tzinfo=UTC),
        source="candlestick",
        occurrences=15,
        hit_rate=0.6,
        average_forward_return_pct=2.5,
        forward_days=5,
    )


def _dummy_candle() -> Candle:
    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=datetime(2026, 8, 7, tzinfo=UTC),
        open=Decimal("1480"),
        high=Decimal("1495"),
        low=Decimal("1470"),
        close=Decimal("1489.25"),
    )


async def _fake_fetch(
    start: object, end: object, symbols: object = None
) -> dict[str, tuple[Candle, ...]]:
    return {"RELIANCE": (_dummy_candle(),)}


@pytest.fixture(autouse=True)
def _reset_scan_state() -> None:
    opportunities_module._last_scan = None
    opportunities_module._scanning = False


class TestListEquityOpportunities:
    def test_empty_before_any_scan_completes(self) -> None:
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity")

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "scanning": False,
            "last_scanned_at": None,
            "symbols_scanned": 0,
            "opportunities": [],
        }

    async def test_serves_the_last_completed_scan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", _fake_fetch)
        monkeypatch.setattr(
            opportunities_module,
            "find_opportunities",
            lambda *a, **k: (make_opportunity("RELIANCE"), make_opportunity("TCS")),
        )
        await opportunities_module.run_scan_once(OpportunitiesSettings())

        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity")

        body = response.json()
        assert body["scanning"] is False
        assert body["last_scanned_at"] is not None
        assert body["symbols_scanned"] == 1
        assert len(body["opportunities"]) == 2
        first = body["opportunities"][0]
        assert first["tradingsymbol"] == "RELIANCE"
        assert first["pattern_name"] == "HAMMER"
        assert first["direction"] == "bullish"
        assert first["hit_rate"] == 0.6
        assert first["forward_days"] == 5

    async def test_limit_query_param_caps_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", _fake_fetch)
        monkeypatch.setattr(
            opportunities_module,
            "find_opportunities",
            lambda *a, **k: tuple(make_opportunity(f"SYM{i}") for i in range(5)),
        )
        await opportunities_module.run_scan_once(OpportunitiesSettings())

        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity?limit=2")

        assert len(response.json()["opportunities"]) == 2

    async def test_failed_scan_is_logged_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_fetch(
            start: object, end: object, symbols: object = None
        ) -> dict[str, tuple[Candle, ...]]:
            raise RuntimeError("NSE is down")

        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", failing_fetch)
        await opportunities_module.run_scan_once(OpportunitiesSettings())  # must not raise

        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity")

        assert response.json()["opportunities"] == []
        assert opportunities_module._scanning is False

    def test_only_get_is_exposed_under_opportunities(self) -> None:
        with TestClient(create_app(make_settings())) as client:
            response = client.post("/opportunities/equity")
        assert response.status_code == 405
