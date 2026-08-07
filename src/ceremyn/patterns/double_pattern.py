"""Double Top / Double Bottom reversal pattern detection.

Double Top (bearish reversal): two peaks at roughly the same level (an "M" shape)
with a meaningful trough between them, confirmed by a close breaking below that
trough. Double Bottom (bullish reversal) is the exact mirror -- a "W" shape,
confirmed by a close breaking above the peak between the two troughs.

Like `chart_shape.py`, candidate peaks/troughs come from fractal pivots rather than
checking every window, and thresholds below are documented, reasonable defaults --
not derived from a fitted model.
"""

from collections.abc import Sequence
from decimal import Decimal

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns._fractals import pivot_highs, pivot_lows

SOURCE = "chart_shape"
DOUBLE_TOP = "DOUBLE_TOP"
DOUBLE_BOTTOM = "DOUBLE_BOTTOM"

PIVOT_WINDOW = 3  # fractal window used to find candidate peak/trough pivots
MIN_SPAN_BARS = 10  # shortest gap between the two peaks/troughs considered
MAX_SPAN_BARS = 90  # longest gap between the two peaks/troughs considered
PEAK_TOLERANCE_PCT = Decimal("4.0")  # the twin peaks/troughs must sit within this % of each other
MIN_MIDPOINT_DEPTH_PCT = Decimal("5.0")  # the trough/peak between them must be a real move
CONFIRM_MAX_BARS = 30  # how long after the second peak/trough a breakout/breakdown may confirm


def detect(candles: Sequence[Candle], *, tradingsymbol: str | None = None) -> tuple[Pattern, ...]:
    """Scan `candles` (ascending by time) for Double Top and Double Bottom breaks."""
    n = len(candles)
    if n < MIN_SPAN_BARS + 2 * PIVOT_WINDOW:
        return ()
    symbol = tradingsymbol or candles[0].tradingsymbol
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    peaks = pivot_highs(highs, PIVOT_WINDOW)
    troughs = pivot_lows(lows, PIVOT_WINDOW)

    tops: set[int] = set()
    for i, first in enumerate(peaks):
        for second in peaks[i + 1 :]:
            confirmed = _confirm_double(candles, highs, lows, first, second, troughs, is_top=True)
            if confirmed is not None:
                tops.add(confirmed)
    bottoms: set[int] = set()
    for i, first in enumerate(troughs):
        for second in troughs[i + 1 :]:
            confirmed = _confirm_double(candles, lows, highs, first, second, peaks, is_top=False)
            if confirmed is not None:
                bottoms.add(confirmed)

    detected = [
        Pattern(
            name=DOUBLE_TOP,
            tradingsymbol=symbol,
            detected_at=candles[i].timestamp,
            direction=PatternDirection.BEARISH,
            source=SOURCE,
        )
        for i in sorted(tops)
    ] + [
        Pattern(
            name=DOUBLE_BOTTOM,
            tradingsymbol=symbol,
            detected_at=candles[i].timestamp,
            direction=PatternDirection.BULLISH,
            source=SOURCE,
        )
        for i in sorted(bottoms)
    ]
    return tuple(detected)


def _confirm_double(
    candles: Sequence[Candle],
    extremes: list[Decimal],
    opposite_extremes: list[Decimal],
    first: int,
    second: int,
    midpoint_pivots: list[int],
    *,
    is_top: bool,
) -> int | None:
    """Validate a candidate pair of peaks (`is_top=True`) or troughs
    (`is_top=False`) and look for its confirming break. Returns the confirming
    bar's index, or None."""
    span = second - first
    if not (MIN_SPAN_BARS <= span <= MAX_SPAN_BARS):
        return None
    higher, lower = max(extremes[first], extremes[second]), min(extremes[first], extremes[second])
    if higher <= 0:
        return None
    if (higher - lower) / higher * Decimal(100) > PEAK_TOLERANCE_PCT:
        return None
    level = lower if is_top else higher
    between = [m for m in midpoint_pivots if first < m < second]
    if not between:
        return None
    midpoint = (
        min(between, key=lambda m: opposite_extremes[m])
        if is_top
        else max(between, key=lambda m: opposite_extremes[m])
    )
    midpoint_value = opposite_extremes[midpoint]
    depth_pct = (
        (level - midpoint_value) / level * Decimal(100)
        if is_top
        else (midpoint_value - level) / level * Decimal(100)
    )
    if depth_pct < MIN_MIDPOINT_DEPTH_PCT:
        return None
    return _find_confirmation(candles, second, midpoint_value, is_top=is_top)


def _find_confirmation(
    candles: Sequence[Candle], second: int, breakout_level: Decimal, *, is_top: bool
) -> int | None:
    n = len(candles)
    limit = min(n - 1, second + CONFIRM_MAX_BARS)
    for i in range(second + 1, limit + 1):
        close = candles[i].close
        if is_top and close < breakout_level:
            return i
        if not is_top and close > breakout_level:
            return i
    return None
