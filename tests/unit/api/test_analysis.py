"""Full HTTP flow for the read-only per-symbol analysis router
(`api/analysis.py`). Populates `ceremyn.api.opportunities`'s own cache
directly (the same state a completed background scan would leave behind)
rather than running a real scan -- no network I/O needed.
"""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import ceremyn.api.opportunities as opportunities_module
from ceremyn.api.app import create_app
from ceremyn.config import OpportunitiesSettings, Settings
from ceremyn.domain import Candle, TimeFrame

START = datetime(2026, 1, 1, tzinfo=UTC)


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _candle(symbol: str, i: int, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(
        tradingsymbol=symbol,
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(low)),
        close=Decimal(str(c)),
        volume=100_000,
    )


def _monotonic(symbol: str, n: int) -> tuple[Candle, ...]:
    """Strictly rising, flat bars -- no turning points, so no swing pivots at all."""
    return tuple(_candle(symbol, i, 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i) for i in range(n))


def _smooth_swing(symbol: str, n: int) -> tuple[Candle, ...]:
    """A single wide sine swing (period ~31 bars) -- clean, well-separated peaks
    and troughs the 5-bar Fibonacci pivot window can actually confirm (unlike
    `_oscillating_with_doji`, whose every-5-bar doji spikes tie with each other
    and never become strict pivots)."""
    candles = []
    for i in range(n):
        base = 100 + math.sin(i / 5.0) * 10
        o, c = base, base + 0.2
        h, low = max(o, c) + 1.0, min(o, c) - 1.0
        candles.append(_candle(symbol, i, o, h, low, c))
    return tuple(candles)


def _oscillating_with_doji(symbol: str, n: int, *, doji_every: int = 5) -> tuple[Candle, ...]:
    """Same deterministic fixture as tests/unit/patterns/test_opportunity.py --
    forces a real DOJI (weak, ~0.42 hit rate) and DOJISTAR (~0.56 hit rate)."""
    candles = []
    for i in range(n):
        base = 100 + math.sin(i / 2.0) * 3
        o, c = base, base + 0.3
        h, low = max(o, c) + 1.0, min(o, c) - 1.0
        if i % doji_every == doji_every - 1:
            o, c, h, low = 100.0, 100.02, 108.0, 92.0
        candles.append(_candle(symbol, i, o, h, low, c))
    return tuple(candles)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    opportunities_module._last_scan = None
    opportunities_module._scanning = False
    opportunities_module._last_candles = None
    opportunities_module._last_settings = None


def _seed_cache(
    candles_by_symbol: dict[str, tuple[Candle, ...]], settings: OpportunitiesSettings
) -> None:
    opportunities_module._last_candles = candles_by_symbol
    opportunities_module._last_settings = settings
    opportunities_module._last_scan = (
        datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        (),
        len(candles_by_symbol),
    )


class TestAnalyzeEquity:
    def test_no_scan_completed_yet_returns_503(self) -> None:
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/RELIANCE")
        assert response.status_code == 503

    def test_unknown_symbol_returns_404(self) -> None:
        _seed_cache({"RELIANCE": _oscillating_with_doji("RELIANCE", 60)}, OpportunitiesSettings())
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/NOTASYMBOL")
        assert response.status_code == 404
        assert "NOTASYMBOL" in response.json()["detail"]

    def test_returns_full_pattern_breakdown_for_a_known_symbol(self) -> None:
        candles = _oscillating_with_doji("TEST", 60)
        _seed_cache(
            {"TEST": candles},
            OpportunitiesSettings(forward_days=5, min_avg_forward_return_pct=0.0),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/TEST")

        assert response.status_code == 200
        body = response.json()
        assert body["tradingsymbol"] == "TEST"
        assert body["bars_analyzed"] == 60
        assert body["last_scanned_at"] is not None
        names = {p["pattern_name"] for p in body["patterns"]}
        assert "DOJI" in names
        assert "DOJISTAR" in names

    def test_weak_pattern_is_reported_but_not_opportunity_grade(self) -> None:
        """DOJI's real hit rate here (~0.42) is below chance -- analyze_symbol
        still reports it (unlike find_opportunities), just honestly flagged."""
        candles = _oscillating_with_doji("TEST", 60)
        _seed_cache(
            {"TEST": candles},
            OpportunitiesSettings(forward_days=5, min_avg_forward_return_pct=0.0),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/TEST")
        doji = next(p for p in response.json()["patterns"] if p["pattern_name"] == "DOJI")
        assert doji["is_opportunity_grade"] is False
        assert doji["active_now"] is True

    def test_symbol_lookup_is_case_insensitive(self) -> None:
        candles = _oscillating_with_doji("TEST", 60)
        _seed_cache(
            {"TEST": candles},
            OpportunitiesSettings(forward_days=5, min_avg_forward_return_pct=0.0),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/test")
        assert response.status_code == 200
        assert response.json()["tradingsymbol"] == "TEST"

    def test_includes_fibonacci_levels_when_swing_structure_exists(self) -> None:
        candles = _smooth_swing("TEST", 60)
        _seed_cache(
            {"TEST": candles},
            OpportunitiesSettings(forward_days=5, min_avg_forward_return_pct=0.0),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/TEST")
        fib = response.json()["fibonacci"]
        assert fib is not None
        assert fib["direction"] in {"bullish", "bearish"}
        assert fib["golden_pocket_low"] <= fib["golden_pocket_high"]

    def test_fibonacci_is_none_without_swing_structure(self) -> None:
        candles = _monotonic("TEST", 60)
        _seed_cache(
            {"TEST": candles},
            OpportunitiesSettings(forward_days=5, min_avg_forward_return_pct=0.0),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/TEST")
        assert response.json()["fibonacci"] is None

    def test_uses_the_last_scans_own_thresholds(self) -> None:
        """The endpoint must reuse the cached scan's forward_days/min_avg_forward_
        return_pct, not some hardcoded default."""
        candles = _oscillating_with_doji("TEST", 60)
        _seed_cache(
            {"TEST": candles},
            OpportunitiesSettings(forward_days=5, min_avg_forward_return_pct=1000.0),
        )
        with TestClient(create_app(make_settings())) as client:
            response = client.get("/analysis/equity/TEST")
        # An impossible 1000% bar means nothing can be opportunity-grade.
        assert all(not p["is_opportunity_grade"] for p in response.json()["patterns"])
        assert all(p["forward_days"] == 5 for p in response.json()["patterns"])
