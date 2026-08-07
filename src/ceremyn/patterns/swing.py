"""Swing-structure (market-structure) pattern detection.

Independent of TA-Lib's single/few-candle formations (see `candlestick.py`): this
looks at the shape of price *swings* across many bars. A "Higher High" is Dow
Theory's textbook uptrend-continuation signal -- a newly confirmed swing high that
exceeds the swing high before it.
"""

from collections.abc import Sequence
from itertools import pairwise

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns._fractals import pivot_highs

SOURCE = "swing"
PATTERN_NAME = "HIGHER_HIGH"
# Bill Williams' Fractals default: a swing high is a bar whose high exceeds every
# high within this many bars on both sides.
FRACTAL_WINDOW = 2


def detect(candles: Sequence[Candle], *, tradingsymbol: str | None = None) -> tuple[Pattern, ...]:
    """Scan `candles` (ascending by time) for confirmed Higher-High swing points.

    A swing high can only be confirmed `FRACTAL_WINDOW` bars after it forms (once
    its following bars are known not to exceed it) -- `detected_at` is set to that
    confirmation bar, never the pivot bar itself, so no occurrence claims to "know"
    a swing high before it was actually knowable.
    """
    if len(candles) < 2 * FRACTAL_WINDOW + 1:
        return ()
    symbol = tradingsymbol or candles[0].tradingsymbol
    highs = [c.high for c in candles]
    pivots = pivot_highs(highs, FRACTAL_WINDOW)

    detected: list[Pattern] = []
    for prev_idx, idx in pairwise(pivots):
        if highs[idx] > highs[prev_idx]:
            confirmed_at = candles[idx + FRACTAL_WINDOW].timestamp
            detected.append(
                Pattern(
                    name=PATTERN_NAME,
                    tradingsymbol=symbol,
                    detected_at=confirmed_at,
                    direction=PatternDirection.BULLISH,
                    source=SOURCE,
                )
            )
    return tuple(detected)
