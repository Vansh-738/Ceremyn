import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ceremyn.domain import Candle, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.candlestick import available_patterns, detect

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
    )


def _oscillating_series(n: int) -> list[Candle]:
    """TA-Lib's pattern functions need a lookback of "normal" bars to establish an
    average body/range size before a forced pattern at the end reads as unusual --
    a bare 1-2 bar series never fires (verified empirically). A deterministic
    sine-wave filler avoids relying on randomness for a reproducible test."""
    candles = []
    for i in range(n):
        base = 100 + math.sin(i / 2.0) * 3
        open_, close = base, base + 0.3
        high = max(open_, close) + 1.0
        low = min(open_, close) - 1.0
        candles.append(_candle(i, open_, high, low, close))
    return candles


class TestDetect:
    def test_empty_candles_returns_empty(self) -> None:
        assert detect(()) == ()

    def test_doji_detected_on_forced_final_bar(self) -> None:
        candles = _oscillating_series(20)
        last = candles[-1]
        candles[-1] = _candle(19, 100.0, 108.0, 92.0, 100.02)  # near-identical open/close
        patterns = detect(candles)
        doji = next((p for p in patterns if p.name == "DOJI"), None)
        assert doji is not None
        assert doji.detected_at == candles[-1].timestamp
        assert doji.tradingsymbol == "RELIANCE"
        assert doji.source == "candlestick"
        assert last.timestamp == candles[-1].timestamp  # sanity: same bar position

    def test_bullish_engulfing_detected(self) -> None:
        candles = _oscillating_series(20)
        # bar -2: red/down candle; bar -1: bigger green candle engulfing it.
        candles[-2] = _candle(18, 105.0, 106.0, 99.0, 100.0)
        candles[-1] = _candle(19, 99.5, 108.0, 99.0, 107.0)
        patterns = detect(candles)
        engulfing = [p for p in patterns if p.name == "ENGULFING"]
        bullish_at_last_bar = [
            p
            for p in engulfing
            if p.detected_at == candles[-1].timestamp and p.direction is PatternDirection.BULLISH
        ]
        assert len(bullish_at_last_bar) == 1

    def test_tradingsymbol_defaults_to_candles_own(self) -> None:
        candles = _oscillating_series(20)
        candles[-1] = _candle(19, 100.0, 108.0, 92.0, 100.02)
        patterns = detect(candles)
        assert all(p.tradingsymbol == "RELIANCE" for p in patterns)

    def test_tradingsymbol_override(self) -> None:
        candles = _oscillating_series(20)
        candles[-1] = _candle(19, 100.0, 108.0, 92.0, 100.02)
        patterns = detect(candles, tradingsymbol="NIFTY")
        assert all(p.tradingsymbol == "NIFTY" for p in patterns)
        assert len(patterns) > 0


class TestAvailablePatterns:
    def test_returns_known_ta_lib_patterns(self) -> None:
        names = available_patterns()
        assert "DOJI" in names
        assert "ENGULFING" in names
        assert "HAMMER" in names
        assert len(names) >= 50  # TA-Lib ships ~61 as of this writing
        assert names == tuple(sorted(names))  # deterministic, stable ordering
