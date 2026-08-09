"""Fibonacci retracement levels from the most recent confirmed swing leg.

Reuses the same fractal pivot detection `swing.py` uses for market structure,
but with a materially wider window: retracement levels are meant to anchor on a
significant primary swing, not the tightest local wiggle.
"""

from collections.abc import Sequence
from decimal import Decimal

from ceremyn.domain import Candle, FibonacciLevels
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns._fractals import pivot_highs, pivot_lows

FRACTAL_WINDOW = 5
RATIOS = (Decimal("0.236"), Decimal("0.382"), Decimal("0.5"), Decimal("0.618"), Decimal("0.786"))


def compute_levels(
    candles: Sequence[Candle],
    *,
    tradingsymbol: str | None = None,
    fractal_window: int = FRACTAL_WINDOW,
) -> FibonacciLevels | None:
    """Levels spanning the most recent confirmed swing leg: whichever of the last
    confirmed pivot high and the last confirmed pivot low comes later is the leg's
    extreme (0% retracement); the other is its origin (100% retracement). None if
    there isn't at least one confirmed pivot of each kind, or the two coincide or
    are the same price (no genuine move to retrace).
    """
    if len(candles) < 2 * fractal_window + 1:
        return None
    symbol = tradingsymbol or candles[0].tradingsymbol
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    high_pivots = pivot_highs(highs, fractal_window)
    low_pivots = pivot_lows(lows, fractal_window)
    if not high_pivots or not low_pivots:
        return None

    last_high, last_low = high_pivots[-1], low_pivots[-1]
    if last_high == last_low:
        return None
    if last_high > last_low:
        start_idx, end_idx = last_low, last_high
        swing_start, swing_end = lows[start_idx], highs[end_idx]
        direction = PatternDirection.BULLISH
    else:
        start_idx, end_idx = last_high, last_low
        swing_start, swing_end = highs[start_idx], lows[end_idx]
        direction = PatternDirection.BEARISH

    diff = swing_end - swing_start
    if diff == 0:
        return None

    level_23_6, level_38_2, level_50_0, level_61_8, level_78_6 = (
        swing_end - diff * ratio for ratio in RATIOS
    )
    golden_pocket_low, golden_pocket_high = sorted((level_50_0, level_61_8))

    return FibonacciLevels(
        tradingsymbol=symbol,
        as_of=candles[-1].timestamp,
        direction=direction,
        swing_start=swing_start,
        swing_start_at=candles[start_idx].timestamp,
        swing_end=swing_end,
        swing_end_at=candles[end_idx].timestamp,
        level_23_6=level_23_6,
        level_38_2=level_38_2,
        level_50_0=level_50_0,
        level_61_8=level_61_8,
        level_78_6=level_78_6,
        golden_pocket_low=golden_pocket_low,
        golden_pocket_high=golden_pocket_high,
    )
