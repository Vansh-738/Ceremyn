"""Head-and-Shoulders reversal pattern detection.

Head and Shoulders (bearish reversal): three peaks -- left shoulder, head (the
highest), right shoulder (similar height to the left shoulder) -- with two troughs
between them forming a "neckline". Confirmed by a close breaking below the
neckline after the right shoulder. Inverse Head and Shoulders (bullish reversal)
is the exact mirror: three troughs, the middle one lowest, confirmed by a close
breaking above the neckline formed by the two peaks between them.
"""

from collections.abc import Sequence
from decimal import Decimal

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns._fractals import pivot_highs, pivot_lows

SOURCE = "chart_shape"
HEAD_AND_SHOULDERS = "HEAD_AND_SHOULDERS"
INVERSE_HEAD_AND_SHOULDERS = "INVERSE_HEAD_AND_SHOULDERS"

PIVOT_WINDOW = 3
MIN_SPAN_BARS = 15  # shortest left-shoulder-to-right-shoulder gap considered
MAX_SPAN_BARS = 130  # longest left-shoulder-to-right-shoulder gap considered
SHOULDER_TOLERANCE_PCT = Decimal("8.0")  # the two shoulders must sit within this % of each other
MIN_HEAD_PROMINENCE_PCT = Decimal("3.0")  # the head must clear the shoulders by at least this %
CONFIRM_MAX_BARS = 30  # how long after the right shoulder a neckline break may confirm


def detect(candles: Sequence[Candle], *, tradingsymbol: str | None = None) -> tuple[Pattern, ...]:
    """Scan `candles` (ascending by time) for Head-and-Shoulders and Inverse
    Head-and-Shoulders confirmations."""
    n = len(candles)
    if n < MIN_SPAN_BARS + 2 * PIVOT_WINDOW:
        return ()
    symbol = tradingsymbol or candles[0].tradingsymbol
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    peaks = pivot_highs(highs, PIVOT_WINDOW)
    troughs = pivot_lows(lows, PIVOT_WINDOW)

    tops: set[int] = set()
    for left, head, right in zip(peaks, peaks[1:], peaks[2:], strict=False):
        confirmed = _confirm(candles, highs, lows, left, head, right, troughs, is_top=True)
        if confirmed is not None:
            tops.add(confirmed)
    bottoms: set[int] = set()
    for left, head, right in zip(troughs, troughs[1:], troughs[2:], strict=False):
        confirmed = _confirm(candles, lows, highs, left, head, right, peaks, is_top=False)
        if confirmed is not None:
            bottoms.add(confirmed)

    detected = [
        Pattern(
            name=HEAD_AND_SHOULDERS,
            tradingsymbol=symbol,
            detected_at=candles[i].timestamp,
            direction=PatternDirection.BEARISH,
            source=SOURCE,
        )
        for i in sorted(tops)
    ] + [
        Pattern(
            name=INVERSE_HEAD_AND_SHOULDERS,
            tradingsymbol=symbol,
            detected_at=candles[i].timestamp,
            direction=PatternDirection.BULLISH,
            source=SOURCE,
        )
        for i in sorted(bottoms)
    ]
    return tuple(detected)


def _confirm(
    candles: Sequence[Candle],
    extremes: list[Decimal],
    opposite_extremes: list[Decimal],
    left: int,
    head: int,
    right: int,
    neckline_pivots: list[int],
    *,
    is_top: bool,
) -> int | None:
    """Validate a candidate (left shoulder, head, right shoulder) triple and look
    for its confirming neckline break. Returns the confirming bar's index, or
    None."""
    span = right - left
    if not (MIN_SPAN_BARS <= span <= MAX_SPAN_BARS):
        return None
    head_value, left_value, right_value = extremes[head], extremes[left], extremes[right]
    is_head_extreme = (
        head_value > left_value and head_value > right_value
        if is_top
        else head_value < left_value and head_value < right_value
    )
    if not is_head_extreme:
        return None
    shoulder_high, shoulder_low = max(left_value, right_value), min(left_value, right_value)
    if shoulder_high <= 0:
        return None
    if (shoulder_high - shoulder_low) / shoulder_high * Decimal(100) > SHOULDER_TOLERANCE_PCT:
        return None
    prominence_ref = min(left_value, right_value) if is_top else max(left_value, right_value)
    if prominence_ref <= 0:
        return None
    prominence_pct = (
        (head_value - prominence_ref) / prominence_ref * Decimal(100)
        if is_top
        else (prominence_ref - head_value) / prominence_ref * Decimal(100)
    )
    if prominence_pct < MIN_HEAD_PROMINENCE_PCT:
        return None
    left_neck = [m for m in neckline_pivots if left < m < head]
    right_neck = [m for m in neckline_pivots if head < m < right]
    if not left_neck or not right_neck:
        return None
    pick = min if is_top else max
    left_neckline = pick(opposite_extremes[m] for m in left_neck)
    right_neckline = pick(opposite_extremes[m] for m in right_neck)
    # The conservative neckline reference: price must clear (or fail to clear)
    # both sides of the neckline, not just one.
    neckline = max(left_neckline, right_neckline) if is_top else min(left_neckline, right_neckline)
    return _find_confirmation(candles, right, neckline, is_top=is_top)


def _find_confirmation(
    candles: Sequence[Candle], right: int, neckline: Decimal, *, is_top: bool
) -> int | None:
    n = len(candles)
    limit = min(n - 1, right + CONFIRM_MAX_BARS)
    for i in range(right + 1, limit + 1):
        close = candles[i].close
        if is_top and close < neckline:
            return i
        if not is_top and close > neckline:
            return i
    return None
