"""Candlestick pattern detection via TA-Lib's CDL* functions.

TA-Lib ships ~60 well-established, widely-used candlestick pattern recognizers
(Doji, Hammer, Engulfing, Morning/Evening Star, ...) rather than a hand-rolled
"top N patterns" list -- reuse, not reinvention. Each function returns one integer
per bar: 0 (no signal), +100 (bullish), or -100 (bearish). Some patterns (e.g.
engulfing) are bullish in one occurrence and bearish in another under the very same
function, so direction is read per-occurrence from that sign -- a separate static
"this pattern is always bullish" table would be wrong for those.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import talib

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection

SOURCE = "candlestick"

# Every TA-Lib candlestick recognizer, keyed by its human-readable name
# (e.g. "CDLHAMMER" -> "HAMMER"). Built once at import time.
_CDL_FUNCTIONS: dict[str, Any] = {
    name[len("CDL") :]: getattr(talib, name) for name in dir(talib) if name.startswith("CDL")
}


def available_patterns() -> tuple[str, ...]:
    """Every candlestick pattern name this module can detect."""
    return tuple(sorted(_CDL_FUNCTIONS))


def detect(candles: Sequence[Candle], *, tradingsymbol: str | None = None) -> tuple[Pattern, ...]:
    """Scan `candles` (ascending by time) for every known candlestick pattern.

    Returns one `Pattern` per (bar, pattern) where TA-Lib signaled a hit. Prices are
    converted to float only here, at the numerical-kernel boundary -- `Candle` itself
    stays `Decimal`.
    """
    if not candles:
        return ()
    symbol = tradingsymbol or candles[0].tradingsymbol
    opens = np.array([float(c.open) for c in candles], dtype=np.float64)
    highs = np.array([float(c.high) for c in candles], dtype=np.float64)
    lows = np.array([float(c.low) for c in candles], dtype=np.float64)
    closes = np.array([float(c.close) for c in candles], dtype=np.float64)

    detected: list[Pattern] = []
    for name, fn in _CDL_FUNCTIONS.items():
        values = fn(opens, highs, lows, closes)
        for i, value in enumerate(values):
            if value == 0:
                continue
            detected.append(
                Pattern(
                    name=name,
                    tradingsymbol=symbol,
                    detected_at=candles[i].timestamp,
                    direction=PatternDirection.BULLISH if value > 0 else PatternDirection.BEARISH,
                    source=SOURCE,
                )
            )
    return tuple(detected)
