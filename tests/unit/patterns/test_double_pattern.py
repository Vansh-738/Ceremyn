from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from ceremyn.domain import Candle, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.double_pattern import DOUBLE_BOTTOM, DOUBLE_TOP, detect

START = datetime(2026, 1, 1, tzinfo=UTC)


def _segment_series(breakpoints: list[tuple[int, float]], *, anchor: str) -> list[Candle]:
    """Linearly interpolate a "primary" price series between `breakpoints`
    (index, value) pairs. `anchor="high"` treats the primary series as highs (low
    = primary - 5); `anchor="low"` treats it as lows (high = primary + 5) --
    mirror shapes for top-pattern vs. bottom-pattern fixtures."""
    candles: list[Candle] = []
    for (i0, v0), (i1, v1) in pairwise(breakpoints):
        for i in range(i0, i1):
            value = v0 + (v1 - v0) * (i - i0) / (i1 - i0)
            candles.append(_candle(i, value, anchor=anchor))
    last_i, last_v = breakpoints[-1]
    candles.append(_candle(last_i, last_v, anchor=anchor))
    return candles


def _candle(i: int, primary: float, *, anchor: str) -> Candle:
    if anchor == "high":
        high, low, close = primary, primary - 5, primary - 2
    else:
        high, low, close = primary + 5, primary, primary + 2
    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(high - 1)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
    )


class TestDoubleTop:
    def test_detected_on_twin_peaks_with_breakdown(self) -> None:
        # Peak (100) at i=5, deep trough (80) at i=15, matching peak (100) at
        # i=25, then a long decline that clears well below the trough's low.
        candles = _segment_series([(0, 90), (5, 100), (15, 80), (25, 100), (45, 60)], anchor="high")
        patterns = detect(candles)
        tops = [p for p in patterns if p.name == DOUBLE_TOP]
        assert len(tops) >= 1
        assert all(p.direction is PatternDirection.BEARISH for p in tops)
        assert all(p.source == "chart_shape" for p in tops)
        assert all(candles[25].timestamp < p.detected_at for p in tops)

    def test_uptrend_with_no_second_peak_not_detected(self) -> None:
        candles = _segment_series([(0, 90), (20, 100), (45, 110)], anchor="high")
        assert not [p for p in detect(candles) if p.name == DOUBLE_TOP]

    def test_too_short_returns_empty(self) -> None:
        assert detect(_segment_series([(0, 90), (5, 100)], anchor="high")) == ()


class TestDoubleBottom:
    def test_detected_on_twin_troughs_with_breakout(self) -> None:
        candles = _segment_series(
            [(0, 110), (5, 100), (15, 120), (25, 100), (45, 140)], anchor="low"
        )
        patterns = detect(candles)
        bottoms = [p for p in patterns if p.name == DOUBLE_BOTTOM]
        assert len(bottoms) >= 1
        assert all(p.direction is PatternDirection.BULLISH for p in bottoms)
        assert all(p.source == "chart_shape" for p in bottoms)
        assert all(candles[25].timestamp < p.detected_at for p in bottoms)

    def test_tradingsymbol_default_and_override(self) -> None:
        candles = _segment_series(
            [(0, 110), (5, 100), (15, 120), (25, 100), (45, 140)], anchor="low"
        )
        assert all(p.tradingsymbol == "RELIANCE" for p in detect(candles))
        overridden = detect(candles, tradingsymbol="NIFTY")
        assert len(overridden) > 0
        assert all(p.tradingsymbol == "NIFTY" for p in overridden)
