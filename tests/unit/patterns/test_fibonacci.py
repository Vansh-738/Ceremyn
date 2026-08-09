from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ceremyn.domain import Candle, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.fibonacci import FRACTAL_WINDOW, compute_levels

START = datetime(2026, 1, 1, tzinfo=UTC)

# A down-leg trough at index 6 (100), followed by an up-leg peak at index 18
# (160) -- the only two fractal pivots this series has under the 5-bar window.
_DOWN_THEN_UP = [
    130,
    125,
    120,
    115,
    110,
    105,
    100,
    105,
    110,
    115,
    120,
    125,
    130,
    135,
    140,
    145,
    150,
    155,
    160,
    155,
    150,
    145,
    140,
    135,
    130,
]


def _candle(i: int, price: float) -> Candle:
    return Candle(
        tradingsymbol="RELIANCE",
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(price)),
        high=Decimal(str(price)),
        low=Decimal(str(price)),
        close=Decimal(str(price)),
    )


class TestComputeLevels:
    def test_empty_candles_returns_none(self) -> None:
        assert compute_levels(()) is None

    def test_too_short_for_window_returns_none(self) -> None:
        candles = [_candle(i, p) for i, p in enumerate(_DOWN_THEN_UP[: 2 * FRACTAL_WINDOW])]
        assert compute_levels(candles) is None

    def test_monotonic_series_has_no_swing_structure(self) -> None:
        # Strictly increasing: every bar has a smaller left neighbor, so nothing
        # is ever a strict low pivot either -- no turning points at all.
        candles = [_candle(i, 100.0 + i) for i in range(30)]
        assert compute_levels(candles) is None

    def test_bullish_leg_from_trough_to_peak(self) -> None:
        candles = [_candle(i, p) for i, p in enumerate(_DOWN_THEN_UP)]
        levels = compute_levels(candles)
        assert levels is not None
        assert levels.direction is PatternDirection.BULLISH
        assert levels.swing_start == Decimal("100")
        assert levels.swing_start_at == candles[6].timestamp
        assert levels.swing_end == Decimal("160")
        assert levels.swing_end_at == candles[18].timestamp
        assert levels.as_of == candles[-1].timestamp
        assert levels.level_23_6 == Decimal("145.840")
        assert levels.level_38_2 == Decimal("137.080")
        assert levels.level_50_0 == Decimal("130.000")
        assert levels.level_61_8 == Decimal("122.920")
        assert levels.level_78_6 == Decimal("112.840")
        assert levels.golden_pocket_low == Decimal("122.920")
        assert levels.golden_pocket_high == Decimal("130.000")

    def test_bearish_leg_from_peak_to_trough(self) -> None:
        # Time-reversed: the peak (160) now comes before the trough (100).
        candles = [_candle(i, p) for i, p in enumerate(reversed(_DOWN_THEN_UP))]
        levels = compute_levels(candles)
        assert levels is not None
        assert levels.direction is PatternDirection.BEARISH
        assert levels.swing_start == Decimal("160")
        assert levels.swing_end == Decimal("100")
        assert levels.level_23_6 == Decimal("114.160")
        assert levels.level_38_2 == Decimal("122.920")
        assert levels.level_50_0 == Decimal("130.000")
        assert levels.level_61_8 == Decimal("137.080")
        assert levels.level_78_6 == Decimal("147.160")
        assert levels.golden_pocket_low == Decimal("130.000")
        assert levels.golden_pocket_high == Decimal("137.080")

    def test_tradingsymbol_default_and_override(self) -> None:
        candles = [_candle(i, p) for i, p in enumerate(_DOWN_THEN_UP)]
        levels = compute_levels(candles)
        assert levels is not None and levels.tradingsymbol == "RELIANCE"
        overridden = compute_levels(candles, tradingsymbol="NIFTY")
        assert overridden is not None and overridden.tradingsymbol == "NIFTY"
