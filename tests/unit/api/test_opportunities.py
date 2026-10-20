"""Full HTTP flow for the read-only opportunities router (`api/opportunities.py`).
No database or real network fetch is needed -- `fetch_all_equity_candles`,
`fetch_index_constituents`, and `find_opportunities` are monkeypatched so this
only verifies the router's own wiring/universe-selection/serialization, not
pattern-detection correctness (already covered by
tests/unit/patterns/test_opportunity.py). The background periodic scan itself
is exercised by calling `run_scan_once` directly, the same way
`run_periodic_scan` would -- no real network I/O and no sleeping.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import ceremyn.api.opportunities as opportunities_module
from ceremyn.api.app import create_app
from ceremyn.config import OpportunitiesSettings, Settings
from ceremyn.data.services.equity_history import DEFAULT_TURNOVER_WINDOW
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


def _liquid_candles(
    symbol: str, *, close: float = 1489.25, volume: int = 1_000_000
) -> tuple[Candle, ...]:
    """`DEFAULT_TURNOVER_WINDOW` uniformly-liquid daily candles -- enough history
    for the point-in-time turnover filter to actually confirm the symbol
    (a single candle, below, always gets dropped: there's no full trailing
    window behind it yet)."""
    start = datetime(2026, 8, 7, tzinfo=UTC) - timedelta(days=DEFAULT_TURNOVER_WINDOW - 1)
    return tuple(
        Candle(
            tradingsymbol=symbol,
            timeframe=TimeFrame.DAY,
            timestamp=start + timedelta(days=i),
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=volume,
        )
        for i in range(DEFAULT_TURNOVER_WINDOW)
    )


async def _fake_fetch(
    start: object, end: object, symbols: object = None
) -> dict[str, tuple[Candle, ...]]:
    return {"RELIANCE": _liquid_candles("RELIANCE")}


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
        await opportunities_module.run_scan_once(OpportunitiesSettings(universe="watchlist"))

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
        await opportunities_module.run_scan_once(OpportunitiesSettings(universe="watchlist"))

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
        await opportunities_module.run_scan_once(
            OpportunitiesSettings(universe="watchlist")
        )  # must not raise

        with TestClient(create_app(make_settings())) as client:
            response = client.get("/opportunities/equity")

        assert response.json()["opportunities"] == []
        assert opportunities_module._scanning is False

    def test_only_get_is_exposed_under_opportunities(self) -> None:
        with TestClient(create_app(make_settings())) as client:
            response = client.post("/opportunities/equity")
        assert response.status_code == 405


class TestScanUniverseSelection:
    async def test_watchlist_universe_uses_the_built_in_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[object] = []

        async def capturing_fetch(
            start: object, end: object, symbols: object = None
        ) -> dict[str, tuple[Candle, ...]]:
            seen.append(symbols)
            return {}

        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", capturing_fetch)
        await opportunities_module.run_scan_once(OpportunitiesSettings(universe="watchlist"))

        assert seen == [set(opportunities_module.WATCHLIST)]

    async def test_all_equities_universe_passes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[object] = []

        async def capturing_fetch(
            start: object, end: object, symbols: object = None
        ) -> dict[str, tuple[Candle, ...]]:
            seen.append(symbols)
            return {}

        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", capturing_fetch)
        await opportunities_module.run_scan_once(OpportunitiesSettings(universe="all_equities"))

        assert seen == [None]

    async def test_nifty500_universe_fetches_index_constituents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[object] = []

        async def capturing_fetch(
            start: object, end: object, symbols: object = None
        ) -> dict[str, tuple[Candle, ...]]:
            seen.append(symbols)
            return {}

        async def fake_index(index: str) -> frozenset[str]:
            assert index == "nifty500"
            return frozenset({"RELIANCE", "TCS"})

        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", capturing_fetch)
        monkeypatch.setattr(opportunities_module, "fetch_index_constituents", fake_index)
        await opportunities_module.run_scan_once(OpportunitiesSettings(universe="nifty500"))

        assert seen == [{"RELIANCE", "TCS"}]


class TestTurnoverFilterIntegration:
    async def test_thin_symbols_are_excluded_before_ranking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fetch_liquid_and_thin(
            start: object, end: object, symbols: object = None
        ) -> dict[str, tuple[Candle, ...]]:
            return {
                "LIQUID": _liquid_candles("LIQUID", close=1000.0, volume=1_000_000),  # 100cr/day
                "THIN": _liquid_candles("THIN", close=10.0, volume=10),  # 100/day, every day
            }

        seen_symbols: list[object] = []

        def capturing_find(
            candles_by_symbol: dict,  # type: ignore[type-arg]
            asset_class_by_symbol: dict,  # type: ignore[type-arg]
            **kwargs: object,
        ) -> tuple:  # type: ignore[type-arg]
            seen_symbols.append(set(candles_by_symbol))
            return ()

        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", fetch_liquid_and_thin)
        monkeypatch.setattr(opportunities_module, "find_opportunities", capturing_find)
        await opportunities_module.run_scan_once(
            OpportunitiesSettings(universe="watchlist", min_avg_daily_turnover=Decimal("10000000"))
        )

        assert seen_symbols == [{"LIQUID"}]


class TestForwardWindowAndReturnFloor:
    async def test_settings_are_passed_through_to_find_opportunities(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(opportunities_module, "fetch_all_equity_candles", _fake_fetch)
        seen_kwargs: list[dict[str, object]] = []

        def capturing_find(
            candles_by_symbol: dict,
            asset_class_by_symbol: dict,
            **kwargs: object,  # type: ignore[type-arg]
        ) -> tuple:  # type: ignore[type-arg]
            seen_kwargs.append(kwargs)
            return ()

        monkeypatch.setattr(opportunities_module, "find_opportunities", capturing_find)
        await opportunities_module.run_scan_once(
            OpportunitiesSettings(
                universe="watchlist", forward_days=45, min_avg_forward_return_pct=20.0
            )
        )

        assert seen_kwargs == [
            {
                "forward_days": 45,
                "min_avg_forward_return_pct": 20.0,
                "fdr_alpha": 0.1,
                "fundamentals": {},
                "require_fundamentals": False,
            }
        ]
