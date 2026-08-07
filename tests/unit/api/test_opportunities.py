"""Full HTTP flow for the read-only opportunities router (`api/opportunities.py`).
No database or real network fetch is needed -- `fetch_all_equity_candles` and
`find_opportunities` are monkeypatched so this only verifies the router's own
wiring/caching/serialization, not pattern-detection correctness (already covered
by tests/unit/patterns/test_opportunity.py).
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import ceremyn.api.opportunities as opportunities_module
from ceremyn.api.app import create_app
from ceremyn.config import Settings
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


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    opportunities_module._cache = None


async def _fake_fetch(start: object, end: object, symbols: object = None) -> dict:  # type: ignore[type-arg]
    return {"RELIANCE": (_dummy_candle(),)}


def _dummy_candle() -> Candle:
    from decimal import Decimal

    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=datetime(2026, 8, 7, tzinfo=UTC),
        open=Decimal("1480"),
        high=Decimal("1495"),
        low=Decimal("1470"),
        close=Decimal("1489.25"),
    )


class TestListEquityOpportunities:
    def test_returns_ranked_opportunities(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", _fake_fetch)
        monkeypatch.setattr(
            opportunities_module,
            "find_opportunities",
            lambda *a, **k: (make_opportunity("RELIANCE"), make_opportunity("TCS")),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["tradingsymbol"] == "RELIANCE"
        assert body[0]["pattern_name"] == "HAMMER"
        assert body[0]["direction"] == "bullish"
        assert body[0]["hit_rate"] == 0.6

    def test_limit_query_param_caps_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", _fake_fetch)
        monkeypatch.setattr(
            opportunities_module,
            "find_opportunities",
            lambda *a, **k: tuple(make_opportunity(f"SYM{i}") for i in range(5)),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity?limit=2")

        assert len(response.json()) == 2

    def test_second_call_within_ttl_does_not_rescan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = []

        async def counting_fetch(start: object, end: object, symbols: object = None) -> dict:  # type: ignore[type-arg]
            calls.append(1)
            return await _fake_fetch(start, end, symbols)

        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", counting_fetch)
        monkeypatch.setattr(
            opportunities_module, "find_opportunities", lambda *a, **k: (make_opportunity(),)
        )
        with TestClient(create_app(make_settings())) as client:
            client.get("/opportunities/equity")
            client.get("/opportunities/equity")

        assert len(calls) == 1

    def test_only_get_is_exposed_under_opportunities(self) -> None:
        with TestClient(create_app(make_settings())) as client:
            response = client.post("/opportunities/equity")
        assert response.status_code == 405
