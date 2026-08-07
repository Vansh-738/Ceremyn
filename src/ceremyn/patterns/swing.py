"""Swing-structure (market-structure) pattern detection.

Independent of TA-Lib's single/few-candle formations (see `candlestick.py`): this
looks at the shape of price *swings* across many bars -- Dow Theory's four textbook
market-structure signals, each a newly confirmed swing pivot compared against the
pivot of the same kind before it:

- Higher High / Higher Low: bullish (uptrend continuation / rising support).
- Lower High / Lower Low: bearish (downtrend continuation / falling resistance).
"""

from collections.abc import Sequence
from itertools import pairwise

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns._fractals import pivot_highs, pivot_lows

SOURCE = "swing"
# Bill Williams' Fractals default: a swing pivot is a bar whose high/low exceeds
# every high/low within this many bars on both sides.
FRACTAL_WINDOW = 2


def detect(candles: Sequence[Candle], *, tradingsymbol: str | None = None) -> tuple[Pattern, ...]:
    """Scan `candles` (ascending by time) for confirmed swing-structure pivots.

    A swing pivot can only be confirmed `FRACTAL_WINDOW` bars after it forms (once
    its following bars are known not to exceed it) -- `detected_at` is set to that
    confirmation bar, never the pivot bar itself, so no occurrence claims to "know"
    a swing pivot before it was actually knowable.
    """
    if len(candles) < 2 * FRACTAL_WINDOW + 1:
        return ()
    symbol = tradingsymbol or candles[0].tradingsymbol
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    detected: list[Pattern] = []
    for prev_idx, idx in pairwise(pivot_highs(highs, FRACTAL_WINDOW)):
        name = "HIGHER_HIGH" if highs[idx] > highs[prev_idx] else "LOWER_HIGH"
        direction = PatternDirection.BULLISH if name == "HIGHER_HIGH" else PatternDirection.BEARISH
        detected.append(_pivot_pattern(candles, symbol, idx, name, direction))
    for prev_idx, idx in pairwise(pivot_lows(lows, FRACTAL_WINDOW)):
        name = "HIGHER_LOW" if lows[idx] > lows[prev_idx] else "LOWER_LOW"
        direction = PatternDirection.BULLISH if name == "HIGHER_LOW" else PatternDirection.BEARISH
        detected.append(_pivot_pattern(candles, symbol, idx, name, direction))
    return tuple(detected)


def _pivot_pattern(
    candles: Sequence[Candle], symbol: str, idx: int, name: str, direction: PatternDirection
) -> Pattern:
    return Pattern(
        name=name,
        tradingsymbol=symbol,
        detected_at=candles[idx + FRACTAL_WINDOW].timestamp,
        direction=direction,
        source=SOURCE,
    )
