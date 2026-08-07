from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ceremyn.domain import Candle, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.chart_shape import detect

START = datetime(2026, 1, 1, tzinfo=UTC)
RIM = 100.0
LEFT_RIM_INDEX = 10
BOTTOM_INDEX = 30
RIGHT_RIM_INDEX = 50
HANDLE_END_INDEX = 60
BREAKOUT_INDEX = 61


def _candle(i: int, high: float, low: float, close: float) -> Candle:
    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(high - 0.5)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
    )


def _cup_and_handle_series(
    *, depth_pct: float = 20.0, tradingsymbol: str = "RELIANCE"
) -> list[Candle]:
    """A hand-shaped cup and handle: lead-in (0-10, rising to the left rim), a
    decline into the cup bottom (11-30), a recovery to the right rim (31-50), a
    flat handle (51-60), then a breakout bar (61) that closes above the rim."""
    depth = RIM * depth_pct / 100
    bottom = RIM - depth
    candles: list[Candle] = []
    for i in range(0, LEFT_RIM_INDEX + 1):  # lead-in, strictly increasing to the rim
        high = RIM - (LEFT_RIM_INDEX - i)
        candles.append(_candle(i, high, high - 5, high - 1))
    for i in range(LEFT_RIM_INDEX + 1, BOTTOM_INDEX + 1):  # decline into the bottom
        high = RIM - (i - LEFT_RIM_INDEX) * (depth / (BOTTOM_INDEX - LEFT_RIM_INDEX))
        candles.append(_candle(i, high, high - 5, high - 1))
    for i in range(BOTTOM_INDEX + 1, RIGHT_RIM_INDEX + 1):  # recovery to the right rim
        high = bottom + (i - BOTTOM_INDEX) * (depth / (RIGHT_RIM_INDEX - BOTTOM_INDEX))
        candles.append(_candle(i, high, high - 5, high - 1))
    for _ in range(RIGHT_RIM_INDEX + 1, HANDLE_END_INDEX + 1):  # flat, shallow handle
        candles.append(_candle(len(candles), 97.0, 94.0, 95.5))
    candles.append(_candle(len(candles), 107.0, 100.0, 105.0))  # breakout: close > rim
    return candles


class TestDetect:
    def test_too_short_returns_empty(self) -> None:
        assert detect(_cup_and_handle_series()[:35]) == ()

    def test_valid_cup_and_handle_detected(self) -> None:
        candles = _cup_and_handle_series()
        patterns = detect(candles)
        assert len(patterns) == 1
        pattern = patterns[0]
        assert pattern.name == "CUP_AND_HANDLE"
        assert pattern.direction is PatternDirection.BULLISH
        assert pattern.source == "chart_shape"
        assert pattern.detected_at == candles[BREAKOUT_INDEX].timestamp

    def test_shallow_dip_not_detected(self) -> None:
        # A 3% dip is far short of MIN_CUP_DEPTH_PCT (12%) -- not a real correction.
        candles = _cup_and_handle_series(depth_pct=3.0)
        assert detect(candles) == ()

    def test_tradingsymbol_default_and_override(self) -> None:
        candles = _cup_and_handle_series()
        assert all(p.tradingsymbol == "RELIANCE" for p in detect(candles))
        overridden = detect(candles, tradingsymbol="NIFTY")
        assert len(overridden) == 1
        assert overridden[0].tradingsymbol == "NIFTY"
