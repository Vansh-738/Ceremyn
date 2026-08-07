from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ceremyn.domain import Candle, TimeFrame
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


# Two ascending swing peaks (104, then 110, then 118), each a strict fractal pivot
# under the default 2-bar window, each higher than the one before it.
_HIGHS = [100, 102, 104, 103, 101, 105, 108, 110, 107, 104, 112, 115, 118, 114, 110]


class TestDetect:
    def test_empty_candles_returns_empty(self) -> None:
        assert detect(()) == ()

    def test_too_short_for_window_returns_empty(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(_HIGHS[:4])]
        assert detect(candles) == ()

    def test_ascending_swing_highs_detected(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(_HIGHS)]
        patterns = detect(candles)
        assert len(patterns) == 2
        assert all(p.name == "HIGHER_HIGH" for p in patterns)
        assert all(p.direction is PatternDirection.BULLISH for p in patterns)
        assert all(p.source == "swing" for p in patterns)
        # Confirmed FRACTAL_WINDOW bars after each pivot (indices 7 and 12).
        assert patterns[0].detected_at == candles[7 + FRACTAL_WINDOW].timestamp
        assert patterns[1].detected_at == candles[12 + FRACTAL_WINDOW].timestamp

    def test_descending_swing_highs_not_detected(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(reversed(_HIGHS))]
        assert detect(candles) == ()

    def test_tradingsymbol_default_and_override(self) -> None:
        candles = [_candle(i, h) for i, h in enumerate(_HIGHS)]
        assert all(p.tradingsymbol == "RELIANCE" for p in detect(candles))
        overridden = detect(candles, tradingsymbol="NIFTY")
        assert len(overridden) > 0
        assert all(p.tradingsymbol == "NIFTY" for p in overridden)
