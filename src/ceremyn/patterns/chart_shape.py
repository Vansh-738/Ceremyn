"""Cup-and-Handle chart-shape pattern detection.

The classic bullish continuation pattern (O'Neil): price falls from a "left rim"
high into a rounded "cup" bottom, recovers to a "right rim" near the left rim's
level, pulls back briefly into a shallow "handle", then breaks out above the rim.

This is a fuzzy, multi-week chart shape rather than a single-bar signal, so it is
detected heuristically: candidate rims/bottoms come from fractal pivots (see
`_fractals.py`) rather than checking every possible window, which keeps a
whole-market scan cheap. The thresholds below are documented, reasonable
defaults -- not derived from a fitted model.
"""

from collections.abc import Sequence
from decimal import Decimal

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns._fractals import pivot_highs, pivot_lows

SOURCE = "chart_shape"
PATTERN_NAME = "CUP_AND_HANDLE"

RIM_WINDOW = 3  # fractal window used to find candidate rim/bottom pivots
CUP_MIN_BARS = 30  # shortest cup considered (~6 trading weeks)
CUP_MAX_BARS = 130  # longest cup considered (~6 trading months)
MIN_CUP_DEPTH_PCT = Decimal("12.0")  # a cup must be a genuine correction, not noise
MAX_CUP_DEPTH_PCT = Decimal("50.0")
RIM_TOLERANCE_PCT = Decimal("10.0")  # left/right rim highs must sit within this % of each other
BOTTOM_ZONE = (Decimal("0.25"), Decimal("0.75"))  # cup's low must sit in the span's middle half
HANDLE_MIN_BARS = 5
HANDLE_MAX_BARS = 25
HANDLE_MAX_RETRACE_PCT = Decimal("50.0")  # handle pullback must be shallower than the cup itself


def detect(candles: Sequence[Candle], *, tradingsymbol: str | None = None) -> tuple[Pattern, ...]:
    """Scan `candles` (ascending by time) for Cup-and-Handle breakouts.

    Fires once per breakout bar: the first close that clears the cup's rim after a
    valid handle.
    """
    n = len(candles)
    if n < CUP_MIN_BARS + HANDLE_MIN_BARS + 2 * RIM_WINDOW:
        return ()
    symbol = tradingsymbol or candles[0].tradingsymbol
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    rim_pivots = pivot_highs(highs, RIM_WINDOW)
    bottom_pivots = pivot_lows(lows, RIM_WINDOW)
    if len(rim_pivots) < 2 or not bottom_pivots:
        return ()

    # Different (left, right) rim candidates can validly agree on the very same
    # breakout bar -- that is one real-world occurrence, not several, so dedupe by
    # breakout index before turning it into Patterns (otherwise a single breakout
    # would be double- or triple-counted in the historical hit-rate study).
    breakout_indices: set[int] = set()
    for a, left in enumerate(rim_pivots):
        for right in rim_pivots[a + 1 :]:
            breakout = _candidate_cup(candles, highs, lows, left, right, bottom_pivots)
            if breakout is not None:
                breakout_indices.add(breakout)
    return tuple(
        Pattern(
            name=PATTERN_NAME,
            tradingsymbol=symbol,
            detected_at=candles[i].timestamp,
            direction=PatternDirection.BULLISH,
            source=SOURCE,
        )
        for i in sorted(breakout_indices)
    )


def _candidate_cup(
    candles: Sequence[Candle],
    highs: list[Decimal],
    lows: list[Decimal],
    left: int,
    right: int,
    bottom_pivots: list[int],
) -> int | None:
    """Validate the cup shape between pivots `left` and `right`; if valid, look for
    a handle and breakout after it. Returns the breakout bar's index, or None."""
    span = right - left
    if not (CUP_MIN_BARS <= span <= CUP_MAX_BARS):
        return None
    bottoms_between = [b for b in bottom_pivots if left < b < right]
    if not bottoms_between:
        return None
    bottom = min(bottoms_between, key=lambda b: lows[b])
    if not (BOTTOM_ZONE[0] <= Decimal(bottom - left) / Decimal(span) <= BOTTOM_ZONE[1]):
        return None
    left_high, right_high, bottom_low = highs[left], highs[right], lows[bottom]
    rim = min(left_high, right_high)
    if rim <= 0:
        return None
    if abs(left_high - right_high) / rim * Decimal(100) > RIM_TOLERANCE_PCT:
        return None
    depth_pct = (rim - bottom_low) / rim * Decimal(100)
    if not (MIN_CUP_DEPTH_PCT <= depth_pct <= MAX_CUP_DEPTH_PCT):
        return None
    return _find_handle_breakout(candles, right, rim, depth_pct)


def _find_handle_breakout(
    candles: Sequence[Candle], right_rim: int, rim: Decimal, cup_depth_pct: Decimal
) -> int | None:
    """After the cup's right rim, look for a shallow handle followed by a breakout
    close above `rim`. Returns the breakout bar's index, or None if no valid
    handle/breakout follows within the allowed window."""
    n = len(candles)
    handle_end_limit = min(n - 1, right_rim + HANDLE_MAX_BARS)
    max_retrace = cup_depth_pct * HANDLE_MAX_RETRACE_PCT / Decimal(100)
    handle_low: Decimal | None = None
    for i in range(right_rim + 1, handle_end_limit + 1):
        low = candles[i].low
        if handle_low is None or low < handle_low:
            handle_low = low
        if i - right_rim < HANDLE_MIN_BARS:
            continue
        if rim > 0 and (rim - handle_low) / rim * Decimal(100) > max_retrace:
            return None  # handle pulled back too deep -- this candidate is invalidated
        if candles[i].close > rim:
            return i
    return None
