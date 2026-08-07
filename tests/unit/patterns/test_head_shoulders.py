from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from ceremyn.domain import Candle, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.head_shoulders import (
    HEAD_AND_SHOULDERS,
    INVERSE_HEAD_AND_SHOULDERS,
    detect,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _segment_series(breakpoints: list[tuple[int, float]], *, anchor: str) -> list[Candle]:
    """Linearly interpolate a "primary" price series between `breakpoints`
    (index, value) pairs. `anchor="high"` treats the primary series as highs (low
    = primary - 5); `anchor="low"` treats it as lows (high = primary + 5) --
    mirror shapes for Head-and-Shoulders vs. Inverse fixtures."""
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


class TestHeadAndShoulders:
    def test_detected_on_three_peaks_with_neckline_break(self) -> None:
        # Left shoulder (95) @10, trough @20, head (110, the highest) @30,
        # trough @40, right shoulder (~95) @50, then a decline through the neckline.
        candles = _segment_series(
            [(0, 80), (10, 95), (20, 75), (30, 110), (40, 75), (50, 95), (70, 50)],
            anchor="high",
        )
        patterns = detect(candles)
        tops = [p for p in patterns if p.name == HEAD_AND_SHOULDERS]
        assert len(tops) >= 1
        assert all(p.direction is PatternDirection.BEARISH for p in tops)
        assert all(p.source == "chart_shape" for p in tops)
        assert all(candles[50].timestamp < p.detected_at for p in tops)

    def test_three_equal_peaks_have_no_head_and_are_not_detected(self) -> None:
        # A triple top, not a head-and-shoulders: no peak is meaningfully higher.
        candles = _segment_series(
            [(0, 80), (10, 95), (20, 75), (30, 95), (40, 75), (50, 95), (70, 50)],
            anchor="high",
        )
        assert not [p for p in detect(candles) if p.name == HEAD_AND_SHOULDERS]

    def test_too_short_returns_empty(self) -> None:
        assert detect(_segment_series([(0, 80), (10, 95)], anchor="high")) == ()


class TestInverseHeadAndShoulders:
    def test_detected_on_three_troughs_with_neckline_break(self) -> None:
        candles = _segment_series(
            [(0, 120), (10, 105), (20, 125), (30, 90), (40, 125), (50, 105), (70, 150)],
            anchor="low",
        )
        patterns = detect(candles)
        bottoms = [p for p in patterns if p.name == INVERSE_HEAD_AND_SHOULDERS]
        assert len(bottoms) >= 1
        assert all(p.direction is PatternDirection.BULLISH for p in bottoms)
        assert all(p.source == "chart_shape" for p in bottoms)
        assert all(candles[50].timestamp < p.detected_at for p in bottoms)

    def test_tradingsymbol_default_and_override(self) -> None:
        candles = _segment_series(
            [(0, 120), (10, 105), (20, 125), (30, 90), (40, 125), (50, 105), (70, 150)],
            anchor="low",
        )
        assert all(p.tradingsymbol == "RELIANCE" for p in detect(candles))
        overridden = detect(candles, tradingsymbol="NIFTY")
        assert len(overridden) > 0
        assert all(p.tradingsymbol == "NIFTY" for p in overridden)
