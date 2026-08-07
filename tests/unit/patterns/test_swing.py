from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ceremyn.domain import Candle, Pattern, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.swing import FRACTAL_WINDOW, detect

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i: int, high: float) -> Candle:
    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(high - 1)),
        high=Decimal(str(high)),
        low=Decimal(str(high - 3)),
        close=Decimal(str(high - 0.5)),
    )


# Three ascending swing peaks (104, then 110, then 118), each a strict fractal
# pivot under the default 2-bar window, each higher than the one before it. Lows
# track highs via a constant offset, so the valleys of this same zigzag give two
# ascending swing lows (98, then 101) -- fewer than the peaks, since a valley
# needs its own 2-bar-clear window and this series only has two that qualify.
_ASCENDING = [100, 102, 104, 103, 101, 105, 108, 110, 107, 104, 112, 115, 118, 114, 110]


def _by_name(patterns: tuple[Pattern, ...], name: str) -> list[Pattern]:
    return [p for p in patterns if p.name == name]


class TestDetect:
    def test_empty_candles_returns_empty(self) -> None:
        assert detect(()) == ()

    def test_too_short_for_window_returns_empty(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(_ASCENDING[:4])]
        assert detect(candles) == ()

    def test_ascending_series_detects_higher_highs_and_higher_lows(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(_ASCENDING)]
        patterns = detect(candles)
        higher_highs = _by_name(patterns, "HIGHER_HIGH")
        higher_lows = _by_name(patterns, "HIGHER_LOW")
        assert len(patterns) == 3
        assert len(higher_highs) == 2
        assert len(higher_lows) == 1
        assert all(p.direction is PatternDirection.BULLISH for p in patterns)
        assert all(p.source == "swing" for p in patterns)
        # Confirmed FRACTAL_WINDOW bars after each pivot (indices 7 and 12).
        assert higher_highs[0].detected_at == candles[7 + FRACTAL_WINDOW].timestamp
        assert higher_highs[1].detected_at == candles[12 + FRACTAL_WINDOW].timestamp

    def test_descending_series_detects_lower_highs_and_lower_lows(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(reversed(_ASCENDING))]
        patterns = detect(candles)
        assert len(patterns) == 3
        assert len(_by_name(patterns, "LOWER_HIGH")) == 2
        assert len(_by_name(patterns, "LOWER_LOW")) == 1
        assert all(p.direction is PatternDirection.BEARISH for p in patterns)
        assert not _by_name(patterns, "HIGHER_HIGH")
        assert not _by_name(patterns, "HIGHER_LOW")

    def test_tradingsymbol_default_and_override(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(_ASCENDING)]
        assert all(p.tradingsymbol == "RELIANCE" for p in detect(candles))
        overridden = detect(candles, tradingsymbol="NIFTY")
        assert len(overridden) > 0
        assert all(p.tradingsymbol == "NIFTY" for p in overridden)
